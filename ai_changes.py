"""The AI team's change log: what differs between two plans for the same gameweek (injury/doubt flags,
transfer set, captain), why (cause), and how the log collapses reversals. Pure functions on plan dicts; split out of
ai_team.py (which re-exports these names so `ai_team.diff_plans` etc. keep working)."""
from __future__ import annotations


def _flag_text(p):
    bits = []
    if p.get("avail", 1) < 1:
        bits.append(f"{int(p['avail'] * 100)}% fit" + (f" - {p['news']}" if p.get("news") else ""))
    bits.extend(p.get("risks") or [])
    return "; ".join(bits)


def _pairs(plan):
    return [(t["out_id"], t["in_id"]) for t in plan.get("transfers", [])]


def _move_text(t):
    return f"{t['out']}→{t['in']} ({t['gain']:+.1f})"


def _transfer_cause(prev, new, vals, ctx_ref):
    pold = {p["id"]: p for p in prev["squad"]}
    ids = {i for t in prev.get("transfers", []) + new.get("transfers", []) for i in (t["out_id"], t["in_id"])}
    for i in ids:
        if i in pold and i in vals and _flag_text(pold[i]) != _flag_text(vals[i]):
            return "injury/fitness", None
    pref = prev.get("model_ref")
    if pref and ctx_ref and pref != ctx_ref:
        return "model update", ctx_ref
    for i in ids:
        if i in pold and i in vals and pold[i].get("cost") != vals[i]["cost"]:
            return "price", None
    return "inputs changed", None


def diff_plans(prev, new, vals, now, model_ref=None):
    """Human-readable changes between two plans for the same gameweek (the daily check): new injuries /
    doubts / rotation risks on squad players, ONE entry when the set of transfers changes (not a squad diff),
    and captaincy."""
    out, at = [], now.isoformat()
    pold = {p["id"]: p for p in prev["squad"]}
    pnew = {p["id"]: p for p in new["squad"]}
    for i, p in pnew.items():
        if i in pold and _flag_text(pold[i]) != _flag_text(p) and _flag_text(p):
            out.append({"at": at, "gw": new["gw"], "kind": "risk", "text": f"{p['name']}: {_flag_text(p)}"})
    pp, np_ = _pairs(prev), _pairs(new)
    if set(pp) != set(np_):
        dropped = [t for t in prev.get("transfers", []) if (t["out_id"], t["in_id"]) not in set(np_)]
        added = [t for t in new.get("transfers", []) if (t["out_id"], t["in_id"]) not in set(pp)]
        if len(added) == len(new.get("transfers", [])) and len(added) == 1 and not dropped:
            text = "Now " + _move_text(added[0])
        elif not added and len(dropped) == 1:
            text = "Dropped " + _move_text(dropped[0])
        else:
            text = "Now: " + ", ".join(_move_text(t) for t in new.get("transfers", [])) if new.get("transfers") else "Now rolling the transfer"
            if dropped:
                text += " · Dropped: " + ", ".join(_move_text(t) for t in dropped)
        cause, ref = _transfer_cause(prev, new, vals, model_ref or new.get("model_ref"))
        mv = lambda ts: [{"out": t["out"], "in": t["in"], "gain": t["gain"], "out_id": t["out_id"], "in_id": t["in_id"]} for t in ts]
        out.append({"at": at, "gw": new["gw"], "kind": "transfer", "text": text, "cause": cause, "cause_ref": ref,
                    "moves": mv(new.get("transfers", [])), "was": mv(prev.get("transfers", []))})
    if prev["captain"] != new["captain"]:
        out.append({"at": at, "gw": new["gw"], "kind": "captain", "text": f"Captain {pold[prev['captain']]['name'] if prev['captain'] in pold else '?'} → {pnew[new['captain']]['name']}"})
    return out


def _entry_pairs(moves):
    return {(m.get("out_id", m.get("out")), m.get("in_id", m.get("in"))) for m in moves or []}


def merge_changes(changes, entries):
    """Append new log entries, collapsing reversals: a transfer entry that restores the set from before the last
    transfer entry of the same gameweek (A->B->A) removes that entry instead of being added; one equal to the last
    logged set adds nothing."""
    changes = list(changes)
    reverted = False
    for e in entries:
        if e.get("kind") == "captain" and reverted:
            continue                     # the captain change of a reversal is undone with it
        if e.get("kind") == "transfer":
            last = next((k for k in range(len(changes) - 1, -1, -1)
                         if changes[k].get("kind") == "transfer" and changes[k].get("gw") == e["gw"]), None)
            if last is not None:
                lp = _entry_pairs(changes[last].get("moves"))
                if _entry_pairs(e.get("moves")) == lp:
                    continue
                if _entry_pairs(e.get("moves")) == _entry_pairs(changes[last].get("was")):
                    at = changes[last]["at"]
                    changes = [c for k, c in enumerate(changes) if k != last and not (
                        c.get("kind") == "captain" and c.get("gw") == e["gw"] and c.get("at") == at)]
                    reverted = True
                    continue
        changes.append(e)
    return changes


def watch_locked(plan, vals, now):
    """After the lock nothing can change, but flag squad players whose fitness/rotation news moved."""
    out = []
    for p in plan["squad"]:
        v = vals.get(p["id"])
        if not v:
            continue
        cur = {"avail": v["avail"], "news": v["news"], "risks": v["risks"]}
        if _flag_text(cur) and _flag_text(cur) != _flag_text(p) and not any(
                c.get("player") == p["id"] and c.get("text") == _flag_text(cur) for c in plan.setdefault("alerts", [])):
            plan["alerts"].append({"player": p["id"], "text": _flag_text(cur)})
            out.append({"at": now.isoformat(), "gw": plan["gw"], "kind": "after-lock",
                        "text": f"{p['name']} (locked in): {_flag_text(cur)}"})
    return out

"""Decision log: the lab's final pre-deadline recommendation for each gameweek, frozen at the deadline, then
scored against what the manager actually did once FPL has finished the gameweek.

The recommendation is exactly what the Plan tab shows: the planner's first-gameweek moves (the DO THIS transfer
tile) applied to the current squad, the XI / bench re-picked on expected points (same rule as ai_team.pick_xi, and
the same as the Plan tab's pitch view), the planner's captain and the Plan lineup's vice where still in the XI.

Stored in its own committed file (rec_log.json / bacalhau-rec_log.json) and copied into data.js as
"decision_log" for the page. Pure functions take their inputs; only update() talks to the FPL API (via `get`)."""
from __future__ import annotations
import json, os, subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import ai_team

ROOT = Path(__file__).resolve().parent
ET = ZoneInfo("America/Toronto")
HIT = 4
XI_MIN = {"DEF": 3, "MID": 2, "FWD": 1}
XI_MAX = {"DEF": 5, "MID": 5, "FWD": 3}
POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def log_path(data_file):
    """data.js -> rec_log.json, bacalhau-data.js -> bacalhau-rec_log.json."""
    data_file = Path(data_file)
    stem = data_file.name[:-len("-data.js")] if data_file.name.endswith("-data.js") else ""
    return data_file.with_name((stem + "-" if stem else "") + "rec_log.json")


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def save(path, log):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(log, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, path)


def code_sha():
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha[:12]
    try:
        return subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def et_text(dt):
    return dt.astimezone(ET).strftime("%Y-%m-%d %-I:%M %p ET")


def pick_xi(players):
    """Best legal XI on xp: 1 GK, the position minimums, then best xP up to the maximums. Bench = spare GK first,
    then outfield by xP. Same rule as ai_team.pick_xi and the Plan tab's pitch view. players: [{name,pos,xp}]."""
    by = {p: sorted([x for x in players if x["pos"] == p], key=lambda x: -x["xp"]) for p in ("GKP", "DEF", "MID", "FWD")}
    xi = by["GKP"][:1]
    cnt = {"DEF": 0, "MID": 0, "FWD": 0}
    for p in ("DEF", "MID", "FWD"):
        for x in by[p][:XI_MIN[p]]:
            xi.append(x); cnt[p] += 1
    for x in sorted([x for x in players if x["pos"] != "GKP" and x not in xi], key=lambda x: -x["xp"]):
        if len(xi) < 11 and cnt[x["pos"]] < XI_MAX[x["pos"]]:
            xi.append(x); cnt[x["pos"]] += 1
    bench = by["GKP"][1:] + sorted([x for x in players if x["pos"] != "GKP" and x not in xi], key=lambda x: -x["xp"])
    return xi, bench


def _bare(n):
    n = str(n or "")
    for t in (" (C)", " (VC)"):
        if n.endswith(t):
            return n[:-len(t)]
    return n


def _id_lookup(boot):
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    by_key, by_name = {}, {}
    for e in boot["elements"]:
        by_key[(e["web_name"], teams[e["team"]])] = e["id"]
        by_name.setdefault(e["web_name"], []).append(e["id"])
    return lambda name, club=None: by_key.get((name, club)) or ((by_name.get(name) or [None])[0] if len(by_name.get(name) or []) == 1 else None)


def build_snapshot(data, boot, now, sha=None):
    """The current recommendation for the next gameweek, from the data.js sections the Plan tab renders.
    Returns None when the inputs are missing (no squad / no planner)."""
    plan, pl = data.get("plan") or {}, data.get("planner") or {}
    gw = (data.get("deadline") or {}).get("next_gw") or plan.get("next_gw")
    rows = plan.get("rows") or []
    steps = pl.get("steps") or []
    if not gw or len(rows) != 15 or not steps or steps[0].get("gw") != gw:
        return None
    s0, xp0 = steps[0], pl.get("xp0") or {}
    idof = _id_lookup(boot)
    moves = s0.get("moves") or []
    outs = {m["out"] for m in moves}
    squad = [{"name": r[1], "pos": r[0], "club": r[2], "xp": float(xp0.get(r[1]) or 0)} for r in rows if r[1] not in outs]
    pos_by_name = data.get("pos_by_name") or {}
    for m in moves:
        squad.append({"name": m["in"], "pos": m.get("pos") or pos_by_name.get(m["in"]), "club": m.get("in_club"),
                      "xp": float((m.get("xp_in") or [0])[0] or 0), "in": True})
    for p in squad:
        p["id"] = idof(p["name"], p["club"])
    if len(squad) != 15 or any(p["id"] is None or p["pos"] not in ("GKP", "DEF", "MID", "FWD") for p in squad):
        return None
    xi, bench = pick_xi(squad)
    xi_names = [p["name"] for p in xi]
    ranked = sorted(xi, key=lambda p: -p["xp"])
    cap = s0.get("captain") if s0.get("captain") in xi_names else ranked[0]["name"]
    lx = (plan.get("xis") or {}).get(f"gw{gw}") or {}
    vc_plan = next((_bare(n) for n in (lx.get("xi") or []) if str(n).endswith(" (VC)")), None)
    vice = vc_plan if vc_plan in xi_names and vc_plan != cap else next(p["name"] for p in ranked if p["name"] != cap)
    by = {p["name"]: p for p in squad}
    hits = int(s0.get("hits") or 0)
    order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    xi_sorted = sorted(xi, key=lambda p: (order[p["pos"]], -p["xp"]))
    return {
        "gw": gw, "status": "pending", "source": "plan", "backfilled": False,
        "saved_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"), "saved_at_et": et_text(now), "code_sha": sha,
        "transfers": [{"out": m["out"], "out_id": idof(m["out"], m.get("out_club")), "in": m["in"], "in_id": by[m["in"]]["id"]} for m in moves],
        "hits": hits, "hit_cost": hits * HIT,
        "squad": [{k: p[k] for k in ("id", "name", "pos", "club", "xp")} for p in xi_sorted + bench],
        "xi": [p["id"] for p in xi_sorted], "bench": [p["id"] for p in bench],
        "captain": by[cap]["id"], "vice": by[vice]["id"], "captain_name": cap, "vice_name": vice,
        "chip": None, "chip_note": "The model plans no chips (chips stay your call).",
        "xp": round(sum(p["xp"] for p in xi) + by[cap]["xp"] - hits * HIT, 1),
        "ft": pl.get("ft"),
    }


# --------------------------------------------------------------------------- scoring
def _side(squad, xi, bench, captain, vice, chip, hit_cost, live, final=True):
    plan = {"squad": squad, "xi": list(xi), "bench": list(bench), "captain": captain, "vice": vice,
            "chip": chip, "hit_cost": hit_cost}
    r = ai_team.score_plan(plan, live, final)
    got = lambda i: (live.get(i) or {}).get("points", 0)
    if chip == "bboost":       # bench boost: the four on the bench count too
        r["bench_pts"] = 0     # score_plan already added them (Bench Boost)
    cap_line = next((l for l in r["lines"] if l["mult"] > 1), None)
    r["captain_id"] = cap_line["id"] if cap_line else None
    r["captain_pts"] = cap_line["pts"] if cap_line else 0
    r["captain_mult"] = cap_line["mult"] if cap_line else 1
    r["captain_extra"] = r["captain_pts"] * (r["captain_mult"] - 1)
    r["got"] = got
    return r


def _transfer_net(moves, live):
    got = lambda i: (live.get(i) or {}).get("points", 0)
    return [{"out": m["out"], "in": m["in"], "out_pts": got(m.get("out_id")), "in_pts": got(m.get("in_id")),
             "net": got(m.get("in_id")) - got(m.get("out_id"))} for m in moves]


def score_entry(rec, actual, live):
    """Compare a frozen recommendation with what the manager did. actual = {"picks": [FPL picks], "chip",
    "points" (FPL GW points before hits), "hit_cost", "transfers": [{out,out_id,in,in_id}]}; live = {id:
    {"minutes","points"}}. The difference is split into captain, transfers and lineup (the rest: XI/bench/autosubs)."""
    names = {p["id"]: p["name"] for p in rec["squad"]}
    m = _side(rec["squad"], rec["xi"], rec["bench"], rec["captain"], rec["vice"], rec.get("chip"), rec.get("hit_cost", 0), live)
    picks = sorted(actual["picks"], key=lambda p: p["position"])
    a_squad = [{"id": p["element"], "name": p.get("name") or str(p["element"]), "pos": p["pos"]} for p in picks]
    a_cap = next((p["element"] for p in picks if p.get("is_captain")), picks[0]["element"])
    a_vice = next((p["element"] for p in picks if p.get("is_vice_captain")), a_cap)
    chip = actual.get("chip")
    y = _side(a_squad, [p["element"] for p in picks[:11]], [p["element"] for p in picks[11:]], a_cap, a_vice,
              chip if chip in ("3xc", "bboost") else None, actual.get("hit_cost", 0), live)
    you_gross = actual["points"] if actual.get("points") is not None else y["gross"]
    you = you_gross - actual.get("hit_cost", 0)
    model = m["points"]
    yt, mt = _transfer_net(actual.get("transfers") or [], live), _transfer_net(rec.get("transfers") or [], live)
    t_you = sum(t["net"] for t in yt) - actual.get("hit_cost", 0)
    t_model = sum(t["net"] for t in mt) - rec.get("hit_cost", 0)
    c_diff = y["captain_extra"] - m["captain_extra"]
    t_diff = t_you - t_model
    diff = you - model
    a_names = {p["id"]: p["name"] for p in a_squad}
    out = {
        "you": you, "model": model, "diff": diff,
        "verdict": "Same" if diff == 0 else (f"You +{diff}" if diff > 0 else f"Model +{-diff}"),
        "captain": {"you": a_names.get(y["captain_id"]), "you_pts": y["captain_pts"], "you_mult": y["captain_mult"],
                    "model": names.get(m["captain_id"]), "model_pts": m["captain_pts"], "model_mult": m["captain_mult"], "diff": c_diff},
        "transfers": {"you": yt, "you_hits": actual.get("hit_cost", 0), "you_net": t_you,
                      "model": mt, "model_hits": rec.get("hit_cost", 0), "model_net": t_model, "diff": t_diff},
        "lineup": {"diff": diff - c_diff - t_diff, "you_bench_pts": y["bench_pts"], "model_bench_pts": m["bench_pts"],
                   "you_autosubs": y["autosubs"], "model_autosubs": m["autosubs"]},
        "chip": {"you": chip, "model": rec.get("chip")},
        "model_lines": [{k: l[k] for k in ("name", "pts", "mult", "played")} for l in m["lines"]],
    }
    if y["gross"] != you_gross:
        out["you_check"] = y["gross"]     # our own recount of your picks, if it differs from FPL's total
    return out


# Recommendations saved on code with a known fault: shown, but not counted in the you-vs-model totals (short sha -> what was wrong)
KNOWN_ISSUES = {"ed83669": "Saved before the 17 Oct fix: a news 'rotation risk' tag cut Haaland's expected points by 20% (any Champions League mention triggered it), so the captain pick was wrong for a reason that is now fixed."}
MIN_CLEAN_WEEKS = 8      # fewer clean weeks than this is too few to call a winner (a week's gap is mostly luck)


def _counts(e):
    """A scored week counts towards the comparison only when it is like for like: a real frozen recommendation (not rebuilt afterwards from an
    old snapshot) and no Wildcard / Free Hit played by the manager (those weeks are a different decision, not a transfer comparison)."""
    s = e.get("score") or {}
    return (not e.get("backfilled") and (s.get("chip") or {}).get("you") not in ("wildcard", "freehit")
            and (e.get("code_sha") or "")[:7] not in KNOWN_ISSUES)


def _pairs(moves):
    return sorted((m.get("out"), m.get("in")) for m in (moves or []))


def totals(log):
    scored = [e for e in log.values() if isinstance(e, dict) and e.get("status") == "scored"]
    rows = [e for e in scored if _counts(e)]
    t = {"gws": len(rows), "you": 0, "model": 0, "you_wins": 0, "model_wins": 0, "same": 0,
         "decisions": {k: {"you": 0, "model": 0, "same": 0} for k in ("captain", "transfers", "lineup")}}
    dis = {k: {"n": 0, "you": 0, "model": 0, "points": 0} for k in ("captain", "transfers", "lineup")}     # where the two actually chose differently
    for e in rows:
        s = e["score"]
        t["you"] += s["you"]; t["model"] += s["model"]
        t["you_wins" if s["diff"] > 0 else "model_wins" if s["diff"] < 0 else "same"] += 1
        for k in t["decisions"]:
            d = s[k]["diff"]
            t["decisions"][k]["you" if d > 0 else "model" if d < 0 else "same"] += 1
        differ = {"captain": (s["captain"].get("you") != s["captain"].get("model")),
                  "transfers": _pairs(s["transfers"].get("you")) != _pairs(s["transfers"].get("model")),
                  "lineup": s["lineup"]["diff"] != 0}
        for k, yes in differ.items():
            if yes:
                x, d = dis[k], s[k]["diff"]
                x["n"] += 1; x["points"] += d
                if d > 0: x["you"] += 1
                elif d < 0: x["model"] += 1
    t["diff"] = t["you"] - t["model"]
    for x in dis.values():
        x["avg"] = round(x["points"] / x["n"], 1) if x["n"] else None
    t["disagree"] = dis
    t["all"] = {"gws": len(scored), "you": sum(e["score"]["you"] for e in scored), "model": sum(e["score"]["model"] for e in scored)}
    t["excluded"] = {"backfilled": sum(1 for e in scored if e.get("backfilled")),
                     "chip": sum(1 for e in scored if not e.get("backfilled") and (e["score"].get("chip") or {}).get("you") in ("wildcard", "freehit")),
                     "known_issue": sum(1 for e in scored if not e.get("backfilled") and (e.get("code_sha") or "")[:7] in KNOWN_ISSUES)}
    diffs = [e["score"]["diff"] for e in rows]
    n = len(diffs)
    mean = sum(diffs) / n if n else 0.0
    sd = (sum((x - mean) ** 2 for x in diffs) / (n - 1)) ** 0.5 if n > 1 else None
    t["noise"] = {"n": n, "needed": MIN_CLEAN_WEEKS, "enough": n >= MIN_CLEAN_WEEKS, "sd": round(sd, 1) if sd is not None else None,
                  "mean": round(mean, 1), "se": round(sd / n ** 0.5, 1) if sd is not None else None}
    return t


# --------------------------------------------------------------------------- refresh entry point
def _actual(get, boot, team_id, gw):
    pos = {e["id"]: POS[e["element_type"]] for e in boot["elements"]}
    name = {e["id"]: e["web_name"] for e in boot["elements"]}
    pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
    eh = pk.get("entry_history") or {}
    # the net change from last gameweek's 15 (a Wildcard / Free Hit week can list dozens of swaps and undos):
    # players who left vs players who arrived, paired position by position
    transfers = []
    if gw > 1:
        try:
            prev = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw - 1}/picks/")
            if prev.get("active_chip") == "freehit" and gw > 2:     # a Free Hit squad reverts: compare with the week before
                prev = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw - 2}/picks/")
            before = {p["element"] for p in (prev.get("picks") or [])}
        except Exception:
            before = set()
        now_ids = {p["element"] for p in pk.get("picks") or []}
        if before:
            transfers = net_moves(before, now_ids, pos, name)
    picks = [{**p, "pos": pos.get(p["element"]), "name": name.get(p["element"])} for p in pk.get("picks") or []]
    return {"picks": picks, "chip": pk.get("active_chip"), "points": eh.get("points"), "hit_cost": eh.get("event_transfers_cost") or 0,
            "transfers": transfers}


def net_moves(before, after, pos, name):
    """Pair the players who left with the ones who arrived, same position, in id order."""
    out_ids, in_ids = sorted(set(before) - set(after)), sorted(set(after) - set(before))
    moves = []
    for p in ("GKP", "DEF", "MID", "FWD"):
        o = [i for i in out_ids if pos.get(i) == p]; n = [i for i in in_ids if pos.get(i) == p]
        moves += [{"out": name.get(a), "out_id": a, "in": name.get(b), "in_id": b} for a, b in zip(o, n)]
    return moves


def _live(get, gw):
    j = get(f"https://fantasy.premierleague.com/api/event/{gw}/live/")
    return {el["id"]: {"minutes": (el.get("stats") or {}).get("minutes") or 0, "points": (el.get("stats") or {}).get("total_points") or 0}
            for el in j.get("elements") or []}


def update(log, data, boot, team_id, get, now=None, sha=None):
    """One refresh: (1) overwrite the next gameweek's snapshot while its deadline is still ahead (frozen after),
    (2) freeze anything whose deadline has passed, (3) score every frozen gameweek FPL has finished and checked."""
    now = now or datetime.now(timezone.utc)
    log = {k: v for k, v in (log or {}).items() if k.startswith("gw")}
    events = {e["id"]: e for e in boot["events"]}
    deadline = lambda g: datetime.fromisoformat(events[g]["deadline_time"].replace("Z", "+00:00")) if g in events else None
    snap = build_snapshot(data, boot, now, sha if sha is not None else code_sha())
    if snap and deadline(snap["gw"]) and now < deadline(snap["gw"]):
        prev = log.get(f"gw{snap['gw']}")
        if not prev or prev.get("status") == "pending":
            log[f"gw{snap['gw']}"] = snap
    for k, e in log.items():
        dl = deadline(e.get("gw"))
        if e.get("status") == "pending" and dl and now >= dl:
            e["status"] = "frozen"
        ev = events.get(e.get("gw")) or {}
        if e.get("status") == "frozen" and ev.get("finished") and ev.get("data_checked"):
            try:
                e["score"] = score_entry(e, _actual(get, boot, team_id, e["gw"]), _live(get, e["gw"]))
                e["status"] = "scored"
                e["scored_at_et"] = et_text(now)
            except Exception as ex:
                e["score_error"] = f"{type(ex).__name__}: {str(ex)[:160]}"
    return dict(sorted(log.items(), key=lambda kv: int(kv[0][2:])))


def view(log):
    """What data.js carries for the page: entries without the bulky per-player lines, plus season totals."""
    rows = []
    for k, e in sorted(log.items(), key=lambda kv: -int(kv[0][2:])):
        r = {x: e.get(x) for x in ("gw", "status", "backfilled", "backfill_note", "saved_at_et", "code_sha", "transfers", "hit_cost",
                                   "captain_name", "vice_name", "chip", "xp")}
        r["known_issue"] = KNOWN_ISSUES.get((e.get("code_sha") or "")[:7])
        if e.get("score"):
            r["score"] = {x: v for x, v in e["score"].items() if x != "model_lines"}
        rows.append(r)
    return {"rows": rows, "totals": totals(log)}


# --------------------------------------------------------------------------- one-off backfill from git history
def _gen_et(s):
    try:
        return et_text(datetime.strptime(str(s), "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc))
    except Exception:
        return None


def backfill_snapshot(old, gw, boot, sha):
    """Reconstruct a gameweek's recommendation from the last data.js committed before its deadline, from the
    Plan tab of the time (before the planner existed): the Plan lineup and armband for that gameweek, with the
    Plan tab's single suggested transfer (if it said TRANSFER) swapped into the out player's slot. No hits, no xP.
    Returns None unless the file clearly holds that gameweek's lineup for a 15-man squad."""
    plan = old.get("plan") or {}
    rows = plan.get("rows") or []
    lx = (plan.get("xis") or {}).get(f"gw{gw}") or {}
    xi_n, bench_n = list(lx.get("xi") or []), list(lx.get("bench") or [])
    if len(rows) != 15 or len(xi_n) != 11 or len(bench_n) != 4:
        return None
    cap = next((_bare(n) for n in xi_n if str(n).endswith(" (C)")), None)
    vice = next((_bare(n) for n in xi_n if str(n).endswith(" (VC)")), None)
    xi_n, bench_n = [_bare(n) for n in xi_n], [_bare(n) for n in bench_n]
    idof = _id_lookup(boot)
    by = {r[1]: {"name": r[1], "pos": r[0], "club": r[2], "xp": None} for r in rows}
    if set(xi_n + bench_n) != set(by) or not cap:
        return None
    tr = plan.get("transfer") or {}
    moves = []
    mv = tr.get("move") if tr.get("action") == "TRANSFER" else None
    if mv and mv.get("out") in by and mv.get("inn"):
        o, i = mv["out"], mv["inn"]
        iid = idof(i)
        if iid is None:
            return None
        el = next(e for e in boot["elements"] if e["id"] == iid)
        by[i] = {"name": i, "pos": POS[el["element_type"]], "club": None, "xp": None}
        xi_n, bench_n = [i if n == o else n for n in xi_n], [i if n == o else n for n in bench_n]
        moves = [{"out": o, "out_id": idof(o, by[o]["club"]), "in": i, "in_id": iid}]
        cap, vice = (i if cap == o else cap), (i if vice == o else vice)
    sq = [by[n] for n in xi_n + bench_n]
    for p in sq:
        p["id"] = idof(p["name"], p["club"])
    if any(p["id"] is None for p in sq):
        return None
    idn = {p["name"]: p["id"] for p in sq}
    return {"gw": gw, "status": "frozen", "source": "plan (backfilled)", "backfilled": True,
            "backfill_note": f"Rebuilt from data.js at {sha}: that day's Plan lineup and armband, plus its suggested transfer if any. No xP or hit plan was stored then.",
            "saved_at": old.get("generated_at"), "saved_at_et": _gen_et(old.get("generated_at")) or old.get("generated_at_et"), "code_sha": sha,
            "transfers": moves, "hits": 0, "hit_cost": 0, "squad": sq, "xi": [idn[n] for n in xi_n], "bench": [idn[n] for n in bench_n],
            "captain": idn[cap], "vice": idn.get(vice) or idn[cap], "captain_name": cap, "vice_name": vice, "chip": None, "xp": None}


def backfill(data_name, boot, gws):
    out = {}
    for gw in gws:
        ev = next((e for e in boot["events"] if e["id"] == gw), None)
        if not ev:
            continue
        sha = subprocess.run(["git", "log", "-1", "--format=%h", f"--before={ev['deadline_time']}", "--", data_name], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if not sha:
            print(f"GW{gw}: no {data_name} before the deadline - skipped"); continue
        raw = subprocess.run(["git", "show", f"{sha}:{data_name}"], cwd=ROOT, capture_output=True, text=True).stdout
        try:
            old = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        except Exception:
            print(f"GW{gw}: {sha} unreadable - skipped"); continue
        snap = backfill_snapshot(old, gw, boot, sha)
        print(f"GW{gw}: {sha} -> {'ok' if snap else 'not reliable, skipped'}")
        if snap:
            out[f"gw{gw}"] = snap
    return out


if __name__ == "__main__":
    import argparse, fplbase
    ap = argparse.ArgumentParser(description="Backfill the decision log from git history, then score it.")
    ap.add_argument("--data", default="data.js")
    ap.add_argument("--team", type=int, required=True)
    ap.add_argument("--gws", default="1-6")
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.gws.split("-"))
    boot = fplbase.get("https://fantasy.premierleague.com/api/bootstrap-static/")
    path = log_path(ROOT / a.data)
    log = load(path)
    for k, v in backfill(a.data, boot, range(lo, hi + 1)).items():
        if k not in log:
            log[k] = v
    raw = (ROOT / a.data).read_text()
    data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    log = update(log, data, boot, a.team, fplbase.get)
    save(path, log)
    print(json.dumps(view(log)["totals"]), [(e["gw"], e["status"], (e.get("score") or {}).get("verdict")) for e in log.values()])

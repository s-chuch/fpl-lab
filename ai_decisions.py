"""Why the AI team made each decision in its plan, as plain data for the AI team > Decision tab.

`build(plan, vals, state, signals)` returns a list of {kind, title, why: [lines], alts: [lines]} for the plan's transfers, captain / vice,
XI / bench and chip. It re-uses the model's own numbers (`vals`: expected points per player; `signals`: news, top-50 ownership, price and
set-piece bonuses) and re-runs the first transfer search to list the next-best moves, so every line is something the model actually saw.
After the gameweek settles the page puts the matching result from `state["reviews"]` (ai_review.py) next to each decision."""
from __future__ import annotations

import ai_team as T


def _best_swaps(squad, buys, bank, vals, signals, k=3):
    """The k best single swaps from the carried squad, by the same score plan_transfers uses (gain = squad score change + signal bonus)."""
    adj = lambda i: (signals.get(i) or {}).get("adj_ai", 0.0)
    cur = T.squad_score(squad, vals)
    best = []
    for out in squad:
        sell = T.sell_price(buys.get(out, vals[out]["cost"]), vals[out]["cost"])
        for v in vals.values():
            if v["pos"] != vals[out]["pos"] or v["id"] in squad or v["avail"] <= 0:
                continue
            if v["value"] + adj(v["id"]) <= vals[out]["value"] + adj(out) or v["cost"] > bank + sell + 1e-9:
                continue
            if not T._club_ok(squad, vals, v["id"], out):
                continue
            gain = T.squad_score([v["id"] if i == out else i for i in squad], vals) - cur + adj(v["id"]) - adj(out)
            best.append((gain, out, v["id"]))
    best.sort(reverse=True)
    return best[:k]


def _fmt(x):
    return f"{x:.1f}"


def build(plan, vals, state, signals=None):
    signals = signals or {}
    name = lambda i: vals[i]["name"]
    out = []
    squad_ids = [int(i) for i in (state.get("squad") or [])]
    # ----- transfers
    tr = plan.get("transfers") or []
    if plan.get("initial"):
        out.append({"kind": "transfer", "title": "Starting squad", "why": ["The first plan builds the best 15 inside the budget on expected points."], "alts": []})
    elif tr:
        buys = {int(k): v for k, v in (state.get("buys") or {}).items()}
        alts = _best_swaps(squad_ids, buys, state.get("bank", 0.0), vals, signals) if squad_ids else []
        chosen = {(m["out_id"], m["in_id"]) for m in tr}
        for m in tr:
            why = [f"Expected gain {m['gain']:+.1f} points over this and next gameweek; a free move needs {T.MIN_FREE_GAIN * T.hurdle_mult():.1f}"
                   + (f", this one is a -4 hit that needs {T.MIN_HIT_GAIN * T.hurdle_mult():.1f}" if m.get("hit") else "") + "."]
            if m.get("xp_in") is not None:
                why.append(f"This gameweek: {m['in']} {_fmt(m['xp_in'])} xP against {m['out']} {_fmt(m['xp_out'])} xP.")
            why += [f"{m['in']}: {r}" for r in m.get("reasons_in") or []] + [f"{m['out']}: {r}" for r in m.get("reasons_out") or []]
            if m.get("adj"):
                why.append(f"Signals (news, top-50 ownership, price, set pieces) moved the gain by {m['adj']:+.2f}, capped at {T.__dict__.get('ADJ_CAP', 1.2)}.")
            why.append(f"Sells {m['out']} for £{m['sell']:.1f}m, buys {m['in']} at £{m['cost_in']:.1f}m.")
            if plan.get("kept_transfers"):
                why.append("Kept from the earlier plan: a new plan only replaces it when it is 0.6 points better.")
            out.append({"kind": "transfer", "title": f"{m['out']} → {m['in']}", "why": why,
                        "alts": [f"{name(o)} → {name(i)} {g:+.1f}" for g, o, i in alts if (o, i) not in chosen][:3]})
    elif squad_ids:
        buys = {int(k): v for k, v in (state.get("buys") or {}).items()}
        alts = _best_swaps(squad_ids, buys, state.get("bank", 0.0), vals, signals)
        need = T.MIN_FREE_GAIN * T.hurdle_mult()
        why = [f"No move: the best swap is worth {alts[0][0]:+.1f}, below the {need:.1f} a free transfer must add, so the free transfer is banked."] if alts else ["No move: no affordable swap improves the squad."]
        out.append({"kind": "transfer", "title": "No transfer", "why": why, "alts": [f"{name(o)} → {name(i)} {g:+.1f}" for g, o, i in alts]})
    # ----- captain and vice
    xi = plan.get("xi") or []
    by_xp = sorted(xi, key=lambda i: -vals[i]["xp"])
    if xi:
        cap, vice = plan["captain"], plan["vice"]
        c = vals[cap]
        why = [f"{c['name']} has the highest expected points in the XI: {_fmt(c['xp'])} xP, {c['fixture']}" + (f" (FDR {c['fdr']})" if c.get("fdr") else "") + "."]
        if len(by_xp) > 1 and by_xp[0] == cap:
            why.append(f"Margin over {name(by_xp[1])}: {c['xp'] - vals[by_xp[1]]['xp']:.2f} points. The armband doubles the player, so a small margin is a coin flip.")
        elif by_xp[0] != cap:
            why.append(f"{name(by_xp[0])} is higher on pure xP; the top managers' captain choice broke the tie (weight {T.captain_elite_weight():.2f}, learned from results).")
        sq = {p["id"]: p for p in plan["squad"]}
        if sq.get(cap, {}).get("why"):
            why.append(sq[cap]["why"])
        e = vals[cap].get("e_cap")
        tops = sorted(((vals[i].get("e_cap") or 0, i) for i in vals), reverse=True)[:1]
        if tops and tops[0][0]:
            why.append(f"Top-50 managers: {name(tops[0][1])} captained by {round(100 * tops[0][0])}%" + (f", {c['name']} by {round(100 * (e or 0))}%." if tops[0][1] != cap else "."))
        why.append(f"Vice {name(vice)} ({_fmt(vals[vice]['xp'])} xP): the best of the rest from a different club, so one match cannot take out both.")
        out.append({"kind": "captain", "title": f"Captain {c['name']}, vice {name(vice)}", "why": why,
                    "alts": [f"{name(i)} {_fmt(vals[i]['xp'])} xP ({vals[i]['fixture']})" for i in by_xp[:4] if i != cap][:3]})
        # ----- XI and bench
        bench = plan.get("bench") or []
        outside = sorted((i for i in (x["id"] for x in plan["squad"]) if i not in xi and vals[i]["pos"] != "GKP"), key=lambda i: -vals[i]["xp"])
        w = [f"Formation {plan.get('formation')}: the legal XI with the most expected points ({plan.get('xp_xi')} including the captain's double)."]
        doubts = [f"{vals[i]['name']} {int(vals[i]['avail'] * 100)}% fit" for i in xi if vals[i]["avail"] < 1]
        if doubts:
            w.append("Fitness doubts in the XI, already discounted in xP: " + ", ".join(doubts) + ".")
        flagged = [f"{vals[i]['name']} ({'; '.join(vals[i].get('risks') or [])})" for i in xi if vals[i].get("risks")]
        if flagged:
            w.append("Rest / minutes / rotation flags applied: " + ", ".join(flagged[:4]) + ".")
        if outside:
            w.append(f"Closest to the XI: {name(outside[0])} {_fmt(vals[outside[0]]['xp'])} xP against the weakest starter {_fmt(min(vals[i]['xp'] for i in xi if vals[i]['pos'] != 'GKP'))}.")
        w.append("Bench order (first on in an auto-sub): " + ", ".join(f"{name(i)} {_fmt(vals[i]['xp'])}" for i in bench) + ".")
        out.append({"kind": "xi", "title": f"XI {plan.get('formation')} and bench", "why": w, "alts": []})
    # ----- chip
    if plan.get("chip") and plan.get("chip_info"):
        out.append({"kind": "chip", "title": f"Chip: {plan['chip_info'].get('name', plan['chip'])}", "why": [plan["chip_info"].get("reason", "")], "alts": []})
    elif plan.get("chip_watch"):
        names = {"wildcard": "Wildcard", "freehit": "Free Hit", "bboost": "Bench Boost", "3xc": "Triple Captain"}
        out.append({"kind": "chip", "title": "No chip this gameweek", "why": [
            f"{names.get(c, c)}: worth {v.get('now')} now, needs {v.get('min')}" + (f"; best ahead GW{v.get('best_gw')} +{v.get('best_later')}" if v.get("best_later") is not None else "") + "."
            for c, v in plan["chip_watch"].items()], "alts": []})
    return out

"""Multi-gameweek transfer planner: from your locked squad, bank and free transfers, search the next few
gameweeks for the transfer path (rolls, single and double moves, hits) that maximises total expected points,
using the same expected-points model as the AI team (ai_team.player_values) for every gameweek.

Beam search: at each gameweek a state can roll, make its best single swaps, or make two swaps (the second
costs a -4 hit when no free transfer is left). States are ranked by the points already banked plus what the
squad would score over the remaining gameweeks if left alone. Chips are not planned (a note says so).
Pure functions plus one builder, so it can be tested offline."""
from __future__ import annotations
import ai_team
from ai_team import BENCH_WEIGHT, HIT_COST, pick_xi, sell_price, tenths

BEAM = 8
SWAPS_PER_STATE = 3
CANDIDATES_PER_POS = 14
MIN_PLAN_GAIN = 1.0       # below this many expected points the plan says "roll" rather than chase noise


def squad_gw_score(ids, vals):
    """Expected points of the best XI for one gameweek, captain doubled, plus a little for the bench."""
    xi, bench = pick_xi(ids, vals, "xp")
    xps = sorted((vals[i]["xp"] for i in xi), reverse=True)
    out_bench = [i for i in bench if vals[i]["pos"] != "GKP"][:3]
    return sum(xps) + xps[0] + BENCH_WEIGHT * sum(vals[i]["xp"] for i in out_bench)


def _club_ok(ids, vals):
    n = {}
    for i in ids:
        n[vals[i]["team"]] = n.get(vals[i]["team"], 0) + 1
    return all(v <= 3 for v in n.values())


def _future(ids, V, k):
    return sum(squad_gw_score(ids, V[j]) for j in range(k, len(V)))


def _swaps(state, V, k, cands, adj):
    """Best single swaps for this state at gameweek k, ranked by the squad's value from k onwards."""
    squad, bank, buys = state["squad"], state["bank"], state["buys"]
    base = _future(squad, V, k)
    vals0 = V[k]
    res = []
    for out in squad:
        sell = tenths(sell_price(buys[out], vals0[out]["cost"]))
        for inn in cands[vals0[out]["pos"]]:
            if inn in squad:
                continue
            cost = tenths(vals0[inn]["cost"])
            if bank + sell < cost:
                continue
            new = [inn if i == out else i for i in squad]
            if not _club_ok(new, vals0):
                continue
            extra = adj.get(inn, 0.0) - adj.get(out, 0.0)      # what the model does not contain (news, price, rivals ...)
            gain = _future(new, V, k) - base + extra
            if gain > 0.05:
                res.append((gain, out, inn, sell, cost, extra))
    res.sort(key=lambda r: -r[0])
    return res[:SWAPS_PER_STATE]


def _apply(state, out, inn, sell, cost, V, k):
    squad = [inn if i == out else i for i in state["squad"]]
    buys = dict(state["buys"])
    buys.pop(out, None)
    buys[inn] = V[k][inn]["cost"]
    return {**state, "squad": squad, "bank": state["bank"] + sell - cost, "buys": buys}


def plan_path(squad, buys, bank, ft, V, beam=BEAM, adj=None):
    """V: [vals for gameweek 0, 1, ...] (each {id: player values with 'xp'}). Returns the best path and the
    do-nothing baseline. bank is in tenths of a million."""
    H = len(V)
    adj = adj or {}
    start = {"squad": list(squad), "bank": bank, "buys": dict(buys), "ft": ft, "banked": 0.0, "steps": []}
    cands_for = {}
    states = [start]
    for k in range(H):
        horizon_sum = {i: sum(V[j][i]["xp"] for j in range(k, H)) for i in V[k]}
        if k not in cands_for:
            cands = {}
            for pos in ("GKP", "DEF", "MID", "FWD"):
                ids = [i for i in V[k] if V[k][i]["pos"] == pos and V[k][i]["avail"] > 0.5]
                cands[pos] = sorted(ids, key=lambda i: -(horizon_sum[i] + adj.get(i, 0.0)))[:CANDIDATES_PER_POS]
            cands_for[k] = cands
        nxt = []
        for st in states:
            options = [(st, [], 0)]
            swaps = _swaps(st, V, k, cands_for[k], adj)
            for gain, out, inn, sell, cost, ex1 in swaps:
                s1 = _apply(st, out, inn, sell, cost, V, k)
                mv1 = {"out": out, "in": inn, "sell": sell / 10, "cost": cost / 10, "adj": round(ex1, 2)}
                options.append((s1, [mv1], 1))
                # a second move on top of the first
                for g2, o2, i2, sl2, c2, ex2 in _swaps(s1, V, k, cands_for[k], adj)[:1]:
                    s2 = _apply(s1, o2, i2, sl2, c2, V, k)
                    options.append((s2, [mv1, {"out": o2, "in": i2, "sell": sl2 / 10, "cost": c2 / 10, "adj": round(ex2, 2)}], 2))
            for s, moves, n in options:
                hits = max(0, n - st["ft"])
                score_now = squad_gw_score(s["squad"], V[k]) - HIT_COST * hits + sum(m["adj"] for m in moves)
                ft_left = max(0, st["ft"] - n)
                new = {**s, "ft": min(5, ft_left + 1), "banked": st["banked"] + score_now,
                       "steps": st["steps"] + [{"k": k, "moves": moves, "hits": hits, "ft_before": st["ft"],
                                                 "ft_after": min(5, ft_left + 1) if k + 1 < H else ft_left,
                                                 "xp": round(squad_gw_score(s["squad"], V[k]), 1), "squad": list(s["squad"]),
                                                 "bank": s["bank"] / 10}]}
                new["rank"] = new["banked"] + (_future(new["squad"], V, k + 1) if k + 1 < H else 0)
                nxt.append(new)
        nxt.sort(key=lambda s: -s["rank"])
        # keep distinct squads/paths only
        seen, states = set(), []
        for s in nxt:
            key = (tuple(sorted(s["squad"])), s["ft"])
            if key in seen:
                continue
            seen.add(key); states.append(s)
            if len(states) >= beam:
                break
    best = max(states, key=lambda s: s["banked"])
    # baseline: roll every week
    base_total = 0.0
    for k in range(H):
        base_total += squad_gw_score(squad, V[k])
    return best, base_total


def build_planner(boot, clone, ds, fix_scan, uwins=None, risk=None, horizon=5, signals=None):
    """Plan the next `horizon` open gameweeks for the user's squad. `clone` is refresh's snapshot of the locked
    squad ({"squad", "buys", "bank", "ft", ...}); `fix_scan(gw)` gives every fixture per team."""
    if not clone:
        return {}
    events = {e["id"]: e for e in boot["events"]}
    start = ds.get("next_gw")
    if not start:
        return {}
    gws = [g for g in range(start, start + horizon) if g in events]
    finished = sum(1 for e in boot["events"] if e.get("finished"))
    locked = ds.get("locked_gw")
    played = max(1, finished + (1 if locked and not events.get(locked, {}).get("finished") else 0))
    V = []
    for idx, g in enumerate(gws):
        # next-match rest and reported rotation only describe the coming gameweek: later gameweeks keep the minutes trend only
        risk_g = risk if (idx == 0 or not risk) else {**risk, "club_rest": {}, "rot_names": {}}
        vals = ai_team.player_values(boot, fix_scan(g), {}, played, uwins, risk_g)
        if idx >= 2:      # injuries/doubts fade with distance: pull availability back towards fit
            for p in vals.values():
                a = p["avail"]
                if 0 < a < 1:
                    p["xp"] = round(p["xp"] / a * (1 - (1 - a) * 0.5 ** (idx - 1)), 2)
        V.append(vals)
    squad = [int(i) for i in clone["squad"]]
    buys = {int(k): float(v) for k, v in clone["buys"].items()}
    signals = signals or {}
    adj = {i: s["adj"] for i, s in signals.items()}
    best, base_total = plan_path(squad, buys, tenths(clone["bank"]), int(clone["ft"]), V, adj=adj)
    names = V[0]
    H = len(V)
    total = best["banked"]
    gain = total - base_total
    total_adj = sum(m.get("adj", 0) for st in best["steps"] for m in st["moves"])
    steps = []
    for st in best["steps"]:
        xi, bench = pick_xi(st["squad"], V[st["k"]], "xp")
        cap = max(xi, key=lambda i: V[st["k"]][i]["xp"])
        steps.append({"gw": gws[st["k"]], "xp": st["xp"], "hits": st["hits"], "ft_before": st["ft_before"], "ft_after": st["ft_after"],
                      "bank": round(st["bank"], 1), "captain": names[cap]["name"],
                      "moves": [{"out": names[m["out"]]["name"], "in": names[m["in"]]["name"], "out_club": names[m["out"]]["club"],
                                 "in_club": names[m["in"]]["club"], "pos": names[m["in"]]["pos"], "sell": m["sell"], "cost": m["cost"],
                                 "adj": m.get("adj", 0), "xp_in": [round(V[j][m["in"]]["xp"], 1) for j in range(st["k"], H)],
                                 "xp_out": [round(V[j][m["out"]]["xp"], 1) for j in range(st["k"], H)],
                                 "fix_in": V[st["k"]][m["in"]]["fixture"], "fix_out": V[st["k"]][m["out"]]["fixture"],
                                 "reasons_in": (signals.get(m["in"]) or {}).get("reasons", []), "reasons_out": (signals.get(m["out"]) or {}).get("reasons", [])} for m in st["moves"]]})
    follow = gain >= MIN_PLAN_GAIN
    if not follow:
        # not worth chasing noise: present rolling every week as the plan
        steps, ft_run = [], int(clone["ft"])
        for k, g in enumerate(gws):
            xi, bench = pick_xi(squad, V[k], "xp")
            cap = max(xi, key=lambda i: V[k][i]["xp"])
            steps.append({"gw": g, "xp": round(squad_gw_score(squad, V[k]), 1), "hits": 0, "ft_before": ft_run,
                          "ft_after": min(5, ft_run + 1), "bank": float(clone["bank"]), "captain": names[cap]["name"], "moves": []})
            ft_run = min(5, ft_run + 1)
    return {"xp0": {names[i]["name"]: round(names[i]["xp"], 2) for i in squad}, "gws": gws, "steps": steps, "plan_xp": round(total if follow else base_total, 1), "roll_xp": round(base_total, 1),
            "gain": round(gain, 1), "gain_model": round(gain - total_adj, 1), "gain_extra": round(total_adj, 1), "recommend": "follow" if follow else "roll",
            "first": steps[0] if steps else None, "ft": int(clone["ft"]), "bank": float(clone["bank"]),
            "note": "Expected points from the program's own model, summed over the horizon with hits (-4) included. Chips are not planned. Treat gains under about 1 point as noise."}

"""Looking back at a settled gameweek: were the AI team's decisions the best it could have made with hindsight, and why not?

`review(plan, result, live, elite)` compares each decision in a locked plan with what players actually scored:
  captain  - the armband against the best player in the XI (and where the model ranked him),
  xi       - the XI played against the best legal XI on actual points, plus the points left on the bench,
  transfers- the points of each player brought in against the one sold, next to the model's expected gap for this gameweek,
  misses   - the biggest gaps between expected and actual points in the XI, with a plain cause (did not play / played little / no returns / big haul),
  elite    - the captain and most-held players of the top-50 managers against the AI's own choices (when their picks for that gameweek are public).
It is data only: `learn.fit_transfers` reads the transfer lines, the Decision tab reads the rest. Everything uses FPL's own live points."""
from __future__ import annotations

import ai_team


def _cause(exp, pts, mins):
    if mins is None:
        return None
    if mins <= 0:
        return "did not play"
    if mins < 60:
        return "played little"
    if pts <= 2 and exp >= 3.5:
        return "played a full game, no returns"
    if pts >= exp + 5:
        return "big haul above expectation"
    return None


def review(plan, result, live, elite=None):
    pos = {p["id"]: p["pos"] for p in plan["squad"]}
    name = {p["id"]: p["name"] for p in plan["squad"]}
    xp = {p["id"]: p["xp"] for p in plan["squad"]}
    pts = lambda i: (live.get(i) or {}).get("points", 0)
    mins = lambda i: (live.get(i) or {}).get("minutes")
    mult = 3 if plan.get("chip") == "3xc" else 2
    out = {"gw": plan["gw"], "final": bool(result.get("final"))}
    # captain
    xi = [l["id"] for l in result.get("lines") or []]
    cap_id = plan["captain"]
    if xi:
        best = max(xi, key=pts)
        rank = sorted(xi, key=lambda i: -xp.get(i, 0)).index(best) + 1
        out["captain"] = {"id": cap_id, "name": name.get(cap_id), "pts": pts(cap_id), "best_id": best, "best": name.get(best), "best_pts": pts(best),
                          "best_xp_rank": rank, "regret": (pts(best) - pts(cap_id)) * (mult - 1), "mult": mult}
        # the vice, and the runner-up by expected points: did the second choice beat the first?
        ranked = sorted(xi, key=lambda i: -xp.get(i, 0))
        if len(ranked) > 1:
            out["captain"]["runner_up"] = {"name": name.get(ranked[1]), "pts": pts(ranked[1])}
    # lineup
    vals = {i: {"pos": pos[i], "pts": float(pts(i))} for i in pos}
    h_xi, h_bench = ai_team.pick_xi(list(pos), vals, "pts")
    played = sum(pts(i) for i in xi)
    out["xi"] = {"pts": played, "hindsight_pts": sum(pts(i) for i in h_xi), "regret": sum(pts(i) for i in h_xi) - played,
                 "bench_pts": result.get("bench_pts", 0), "autosubs": result.get("autosubs") or [],
                 "left_out": [{"name": name[i], "pts": pts(i), "xp": xp.get(i)} for i in sorted((i for i in pos if i not in xi), key=lambda i: -pts(i))[:3] if pts(i) > 0]}
    # transfers: realised against the model's expected gap for this gameweek
    tr = []
    for m in plan.get("transfers") or []:
        a, b = m.get("in_id"), m.get("out_id")
        if a is None or b is None:
            continue
        pred = (m.get("xp_in") - m.get("xp_out")) if m.get("xp_in") is not None and m.get("xp_out") is not None else None
        tr.append({"in": m["in"], "out": m["out"], "pts_in": pts(a), "pts_out": pts(b), "real": pts(a) - pts(b), "pred": None if pred is None else round(pred, 2),
                   "hit": bool(m.get("hit")), "mins_in": mins(a), "mins_out": mins(b)})
    out["transfers"] = tr
    # biggest misses in the XI
    miss = []
    for i in xi:
        e = xp.get(i)
        if e is None or mins(i) is None:
            continue
        gap = pts(i) - e
        c = _cause(e, pts(i), mins(i))
        if abs(gap) >= 4 and c:
            miss.append({"name": name[i], "pos": pos[i], "xp": e, "pts": pts(i), "mins": mins(i), "cause": c})
    out["misses"] = sorted(miss, key=lambda m: -abs(m["pts"] - m["xp"]))[:5]
    # the top-50 managers
    if elite and elite.get("gw") == plan["gw"] and elite.get("n"):
        n = elite["n"]
        cap = elite.get("cap") or {}
        top = max(cap, key=lambda k: cap[k]) if cap else None
        names = elite.get("names") or {}
        held = set(pos)
        miss_owned = sorted((k for k in (elite.get("own") or {}) if int(k) not in held), key=lambda k: -elite["own"][k])[:3]
        out["elite"] = {"n": n, "captain": (names.get(str(top)) or names.get(top) or [None])[0] if top is not None else None,
                        "captain_share": round(cap[top] / n, 2) if top is not None else None,
                        "captain_pts": pts(int(top)) if top is not None else None,
                        "agrees": top is not None and int(top) == cap_id,
                        "not_held": [{"name": (names.get(str(k)) or names.get(k) or ["?"])[0], "share": round(elite["own"][k] / n, 2), "pts": pts(int(k))} for k in miss_owned]}
    return out


def totals(reviews):
    """Running totals across settled gameweeks (shown as context on the Decision tab)."""
    t = {"gws": 0, "captain_regret": 0.0, "xi_regret": 0.0, "bench_pts": 0, "moves": 0, "move_real": 0.0, "move_pred": 0.0, "elite_agree": 0, "elite_n": 0}
    for r in (reviews or {}).values():
        if not r.get("final"):
            continue
        t["gws"] += 1
        t["captain_regret"] += (r.get("captain") or {}).get("regret", 0)
        t["xi_regret"] += (r.get("xi") or {}).get("regret", 0)
        t["bench_pts"] += (r.get("xi") or {}).get("bench_pts", 0)
        for m in r.get("transfers") or []:
            t["moves"] += 1; t["move_real"] += m["real"]; t["move_pred"] += m["pred"] or 0
        if r.get("elite"):
            t["elite_n"] += 1; t["elite_agree"] += int(bool(r["elite"].get("agrees")))
    return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in t.items()}

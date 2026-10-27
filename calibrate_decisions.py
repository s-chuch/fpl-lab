"""Backtest two decision inputs on the vaastav history (same files calibrate.py uses): the weight given to FPL's own forecast
(`ep_next`, in the history `xP`) and the size of gain a free transfer should need.

Run: python calibrate_decisions.py   (needs /tmp/claude-0/calib/<season>.csv; calibrate.load_season downloads them)

Test A  blend = (1-w) x model_xp + w x FPL xP for several w: error against actual points, and what the best-rated player / top 3 / top 10
        by the blend actually scored (the captain and transfer-target use), with a bootstrap over gameweeks.
Test B  every same-position swap (in-price <= out-price + 1.0m): the model's predicted gain (this gameweek + 0.35 x next) against the
        realised gain; the best swap per squad slot (the argmax the AI actually takes); and V, the realised value of the second-best
        swap a squad would have available next week, which is what banking a free transfer buys.
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibrate as C
import ai_team

SEASONS = ("2024-25", "2025-26")
WEIGHTS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
NEXT_W = ai_team.NEXT_WEIGHT


def rows_for(season):
    """{(element, gw): {pos, price, xp, fpl, act}} for every player-gameweek with 270+ prior minutes (fixtures treated as FDR 3, as in calibrate)."""
    by_pl = {}
    for r in C.load_season(season):
        by_pl.setdefault(r["element"], []).append(r)
    out = {}
    for el_id, rows in by_pl.items():
        for t in sorted({int(r["round"]) for r in rows}):
            if t < C.FIRST_GW:
                continue
            prior = [r for r in rows if int(r["round"]) < t]
            if sum(C._f(r["minutes"]) for r in prior) < C.MIN_PRIOR_MINUTES:
                continue
            cur = [r for r in rows if int(r["round"]) == t]
            el = C.build_el(prior)
            fixtures = [{"fdr": 3, "opp": "X", "side": "H" if str(r.get("was_home")) == "True" else "A"} for r in cur]
            last4 = sorted({int(r["round"]) for r in prior})[-4:]
            pts4 = [sum(C._f(r["total_points"]) for r in prior if int(r["round"]) == g) for g in last4]
            form4 = (sum(pts4) / len(pts4)) * len(cur) if pts4 else 0.0      # FPL's `form` (points per game, last ~month), which is what the live `ep_next` equals this season
            apps = [r for r in prior if C._f(r["minutes"]) > 0][-4:]
            uw = {"apps": len(apps), "xg": sum(C._f(r.get("expected_goals")) for r in apps), "xa": sum(C._f(r.get("expected_assists")) for r in apps)} if apps else None
            m_recent = ai_team.model_xp(el, fixtures, t - 1, uw, None) if uw else None
            last_gw = max(int(r["round"]) for r in prior)
            last_pts = sum(C._f(r["total_points"]) for r in prior if int(r["round"]) == last_gw)
            out[(el_id, t)] = {"pos": C.norm_pos(cur[0]["position"]), "last_pts": last_pts, "xp_recent": m_recent, "price": C._f(cur[0].get("value")) / 10.0,
                               "xp": ai_team.model_xp(el, fixtures, t - 1, None, None), "form4": form4,
                               "fpl": sum(C._f(r["xP"]) for r in cur), "act": sum(C._f(r["total_points"]) for r in cur)}
    return out


def test_haul(data):
    """After a 10+ point gameweek: what the model expected, what FPL's form said, and what he actually scored next."""
    groups = {"after a 10+ haul": [], "after 6-9": [], "after 0-5": []}
    for r in data.values():
        k = "after a 10+ haul" if r["last_pts"] >= 10 else "after 6-9" if r["last_pts"] >= 6 else "after 0-5"
        groups[k].append(r)
    out = {}
    for k, v in groups.items():
        out[k] = {"n": len(v), "model": sum(r["xp"] for r in v) / len(v), "form4": sum(r["form4"] for r in v) / len(v),
                  "fpl_xp": sum(r["fpl"] for r in v) / len(v), "actual": mean_se([r["act"] for r in v])}
    return out


def test_recent(data):
    """Weight on the last-four-appearance xG/xA window (the live model uses 0.45): m(u) is linear in u between season-only and the live blend."""
    rows = [r for r in data.values() if r["xp_recent"] is not None]
    res = {}
    for u in (0.0, 0.2, 0.45, 0.7, 1.0):
        pred = [r["xp"] + (u / 0.45) * (r["xp_recent"] - r["xp"]) for r in rows]
        err = [abs(p - r["act"]) for p, r in zip(pred, rows)]
        res[u] = sum(err) / len(err)
    return res


def mean_se(v):
    n = len(v)
    if n < 2:
        return (v[0] if v else 0.0), 0.0
    m = sum(v) / n
    return m, (sum((x - m) ** 2 for x in v) / (n - 1) / n) ** 0.5


def test_a(data, proxy="fpl"):
    gws = sorted({g for (_, g) in data})
    res = {}
    for w in WEIGHTS:
        per_gw = {"top1": [], "top3": [], "top10": []}
        err = []
        for g in gws:
            sub = [(((1 - w) * r["xp"] + w * r[proxy]), r["act"]) for (e, gg), r in data.items() if gg == g]
            if len(sub) < 30:
                continue
            err += [abs(b - a) for b, a in sub]
            sub.sort(key=lambda x: -x[0])
            for k, name in ((1, "top1"), (3, "top3"), (10, "top10")):
                per_gw[name].append(sum(a for _, a in sub[:k]) / k)
        res[w] = {"mae": sum(err) / len(err), **{k: mean_se(v) for k, v in per_gw.items()}, "per_gw": per_gw}
    return res


def paired_diff(res, w, base=0.2, key="top3"):
    """Mean and standard error of (blend w - blend base) per gameweek for the same gameweeks."""
    d = [a - b for a, b in zip(res[w]["per_gw"][key], res[base]["per_gw"][key])]
    return mean_se(d)


def test_b(data, w, seed=7, proxy="fpl"):
    rnd = random.Random(seed)
    gws = sorted({g for (_, g) in data})
    bins = [(0.3, 0.6), (0.6, 1.0), (1.0, 1.5), (1.5, 2.5), (2.5, 4.0), (4.0, 99)]
    all_b = {b: [] for b in bins}
    best_b = {b: [] for b in bins}
    second = []
    best_first = []
    for g in gws:
        if (None, g + 1) and not any(gg == g + 1 for (_, gg) in data):
            continue
        cur = {e: r for (e, gg), r in data.items() if gg == g}
        nxt = {e: r for (e, gg), r in data.items() if gg == g + 1}
        common = [e for e in cur if e in nxt]
        val = lambda e: ((1 - w) * cur[e]["xp"] + w * cur[e][proxy]) + NEXT_W * ((1 - w) * nxt[e]["xp"] + w * nxt[e][proxy])
        real = lambda e: cur[e]["act"] + NEXT_W * nxt[e]["act"]
        by_pos = {}
        for e in common:
            by_pos.setdefault(cur[e]["pos"], []).append(e)
        # all pairs and the best swap per out player
        for pos, ids in by_pos.items():
            ids = [e for e in ids if cur[e]["price"] > 0]
            for o in ids:
                best = None
                for i in ids:
                    if i == o or cur[i]["price"] > cur[o]["price"] + 1.0:
                        continue
                    pg = val(i) - val(o)
                    if pg < 0.3:
                        continue
                    rg = real(i) - real(o)
                    for b in bins:
                        if b[0] <= pg < b[1]:
                            all_b[b].append(rg)
                            break
                    if best is None or pg > best[0]:
                        best = (pg, rg)
                if best:
                    for b in bins:
                        if b[0] <= best[0] < b[1]:
                            best_b[b].append(best[1])
                            break
        # a managed-looking squad: 2/5/5/3 drawn from the better half of each position by blended value
        pool = {}
        for pos, k in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
            ids = sorted(by_pos.get(pos, []), key=lambda e: -val(e))
            pool[pos] = (ids[:max(k + 2, len(ids) // 2)], k)
        for _ in range(60):
            squad = [e for pos, (ids, k) in pool.items() for e in rnd.sample(ids, min(k, len(ids)))]
            swaps = []
            for o in squad:
                top = None
                for i in by_pos[cur[o]["pos"]]:
                    if i in squad or cur[i]["price"] > cur[o]["price"] + 1.0:
                        continue
                    pg = val(i) - val(o)
                    if top is None or pg > top[0]:
                        top = (pg, real(i) - real(o), i)
                if top:
                    swaps.append((top[0], top[1], o, top[2]))
            swaps.sort(reverse=True)
            used_o, used_i, picked = set(), set(), []
            for s in swaps:
                if s[2] in used_o or s[3] in used_i:
                    continue
                used_o.add(s[2]); used_i.add(s[3]); picked.append(s)
                if len(picked) == 2:
                    break
            if len(picked) == 2:
                best_first.append(picked[0][1]); second.append(picked[1][1])
    return {"all": {b: mean_se(v) + (len(v),) for b, v in all_b.items() if v},
            "best": {b: mean_se(v) + (len(v),) for b, v in best_b.items() if v},
            "first": mean_se(best_first), "second": mean_se(second), "second_pred": None}


def test_caps(data):
    """Variants of how FPL's form (the live ep_next) enters: raw at w, or capped at c x the model's own number so a hot week cannot pull a player far above it."""
    variants = [("w=0.2 raw (live)", 0.2, None), ("w=0.1 raw", 0.1, None), ("w=0.0", 0.0, None),
                ("w=0.2 cap 1.5x", 0.2, 1.5), ("w=0.2 cap 1.25x", 0.2, 1.25), ("w=0.3 cap 1.25x", 0.3, 1.25), ("w=0.3 cap 1.5x", 0.3, 1.5)]
    gws = sorted({g for (_, g) in data})
    out = {}
    for name, w, cap in variants:
        def bl(r):
            f = r["form4"] if cap is None else min(r["form4"], cap * r["xp"] + 0.5)
            return (1 - w) * r["xp"] + w * f
        err = [abs(bl(r) - r["act"]) for r in data.values()]
        haul = [r for r in data.values() if r["last_pts"] >= 10]
        bias = sum(bl(r) - r["act"] for r in haul) / len(haul)
        tops = {1: [], 3: [], 10: []}
        for g in gws:
            sub = sorted(((bl(r), r["act"]) for (e, gg), r in data.items() if gg == g), key=lambda x: -x[0])
            if len(sub) < 30:
                continue
            for k in tops:
                tops[k].append(sum(a for _, a in sub[:k]) / k)
        out[name] = {"mae": sum(err) / len(err), "haul_bias": bias, **{f"top{k}": mean_se(v) for k, v in tops.items()}}
    return out


def chasing():
    for sn in SEASONS:
        data = rows_for(sn)
        print(f"\n== {sn}: after a big week, what happens next")
        for k, r in test_haul(data).items():
            print(f"{k:18} n={r['n']:5}  model {r['model']:.2f}  FPL form {r['form4']:.2f}  FPL xP {r['fpl_xp']:.2f}  actual {r['actual'][0]:.2f}±{r['actual'][1]:.2f}")
        print("last-four-appearance weight -> MAE:", {u: round(m, 4) for u, m in test_recent(data).items()})
        print("how FPL form enters (haul bias = prediction minus actual for players after a 10+ week):")
        for name, r in test_caps(data).items():
            print(f"  {name:18} MAE {r['mae']:.3f}  haul bias {r['haul_bias']:+.2f}  top1 {r['top1'][0]:.2f}  top3 {r['top3'][0]:.2f}±{r['top3'][1]:.2f}  top10 {r['top10'][0]:.2f}±{r['top10'][1]:.2f}")


def main():
    out = {}
    for s in SEASONS:
        data = rows_for(s)
        out[s] = {}
        for proxy, label in (("form4", "FPL form (what the live ep_next equals)"), ("fpl", "FPL's real xP (history only)")):
            a = test_a(data, proxy)
            out[s][proxy] = {"a": {w: {k: v for k, v in r.items() if k != "per_gw"} for w, r in a.items()},
                             **{f"paired_{k}": {w: paired_diff(a, w, key=k) for w in WEIGHTS if w != 0.2} for k in ("top1", "top3", "top10")}}
            print(f"\n== {s} · {label}: {len(data)} player-gameweeks")
            print("w     MAE   top1 (se)        top3 (se)        top10 (se)")
            for w in WEIGHTS:
                r = a[w]
                print(f"{w:.1f}  {r['mae']:.3f}  {r['top1'][0]:.2f} ({r['top1'][1]:.2f})   {r['top3'][0]:.2f} ({r['top3'][1]:.2f})   {r['top10'][0]:.2f} ({r['top10'][1]:.2f})")
            for key in ("top1", "top3", "top10"):
                print(f"vs w=0.2 {key} (paired, mean diff / se):", {w: f"{d[0]:+.2f}/{d[1]:.2f}" for w, d in out[s][proxy][f"paired_{key}"].items()})
        for w in (0.0, 0.2):
            b = test_b(data, w, proxy="form4")
            out[s][f"b_form_{w}"] = {"all": {str(k): v for k, v in b["all"].items()}, "best": {str(k): v for k, v in b["best"].items()}, "first": b["first"], "second": b["second"]}
            print(f"\n-- swaps, form weight {w}: predicted gain bin -> realised gain (mean, se, n)")
            print(" all pairs:", {f"{k[0]}-{k[1]}": f"{m:.2f}±{se:.2f} n={n}" for k, (m, se, n) in b["all"].items()})
            print(" best per out player:", {f"{k[0]}-{k[1]}": f"{m:.2f}±{se:.2f} n={n}" for k, (m, se, n) in b["best"].items()})
            print(f" a squad's best swap realised {b['first'][0]:.2f}±{b['first'][1]:.2f}; second-best {b['second'][0]:.2f}±{b['second'][1]:.2f}")
    return out


if __name__ == "__main__":
    if "--chasing" in sys.argv:
        chasing()
        sys.exit(0)
    json.dump(main(), open(Path(__file__).resolve().parent / "docs" / "decision_backtest.json", "w"), indent=1, default=str)

"""How fast do over- and underperformers return to their expected numbers? Backtest on the vaastav history (same files as calibrate.py).

An attacker (MID / FWD, 180+ minutes) is "flagged" the first gameweek his season goals + assists minus xG + xA reaches +OVER (or -UNDER).
For each flagged player we look at what he did in the next 4 and next 8 gameweeks he played in (period gap = G+A minus xGI) and where his
season gap stands afterwards. Written to regression_baseline.json, which refresh.py ships as data["regression"]["baseline"].
Run: python calibrate_regression.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibrate as C

SEASONS = ("2024-25", "2025-26")
OVER, UNDER, MIN_MIN = 2.0, -1.5, 180
OUT = Path(__file__).resolve().parent / "regression_baseline.json"


def _gw_rows(rows):
    by = {}
    for r in rows:
        g = by.setdefault(int(r["round"]), {"min": 0.0, "ga": 0.0, "xgi": 0.0})
        g["min"] += C._f(r.get("minutes"))
        g["ga"] += C._f(r.get("goals_scored")) + C._f(r.get("assists"))
        g["xgi"] += C._f(r.get("expected_goals")) + C._f(r.get("expected_assists"))
    return by


def events(season):
    by_pl = {}
    for r in C.load_season(season):
        by_pl.setdefault(r["element"], []).append(r)
    out = {"over": [], "under": []}
    for rows in by_pl.values():
        if C.norm_pos(rows[0]["position"]) not in ("MID", "FWD"):
            continue
        g = _gw_rows(rows)
        gws = sorted(g)
        cum = {"min": 0.0, "ga": 0.0, "xgi": 0.0}
        flagged = set()
        for i, t in enumerate(gws):
            for k in cum:
                cum[k] += g[t][k]
            gap = cum["ga"] - cum["xgi"]
            if cum["min"] < MIN_MIN or t < 5:
                continue
            for side, hit in (("over", gap >= OVER), ("under", gap <= UNDER)):
                if hit and side not in flagged:
                    flagged.add(side)
                    nxt = gws[i + 1:]
                    if len(nxt) < 4:
                        continue
                    ev = {"gap": gap, "gw": t}
                    for n in (4, 8):
                        part = nxt[:n]
                        if len(part) < n:
                            continue
                        period = sum(g[x]["ga"] - g[x]["xgi"] for x in part)
                        ev[f"p{n}"] = period
                        ev[f"after{n}"] = gap + period
                    out[side].append(ev)
    return out


def summarise(evs):
    res = {}
    for side, lst in evs.items():
        row = {"n": len(lst), "gap_at_flag": round(sum(e["gap"] for e in lst) / len(lst), 2) if lst else None}
        for n in (4, 8):
            sub = [e for e in lst if f"p{n}" in e]
            if sub:
                m = sum(e[f"p{n}"] for e in sub) / len(sub)
                se = (sum((e[f"p{n}"] - m) ** 2 for e in sub) / max(1, len(sub) - 1) / len(sub)) ** 0.5
                row[f"next{n}"] = {"n": len(sub), "period_gap": round(m, 2), "se": round(se, 2),
                                   "gap_after": round(sum(e[f"after{n}"] for e in sub) / len(sub), 2),
                                   "share_moved_toward_zero": round(sum(1 for e in sub if abs(e[f"after{n}"]) < abs(e["gap"])) / len(sub), 2)}
        res[side] = row
    return res


def main():
    allev = {"over": [], "under": []}
    per = {}
    for s in SEASONS:
        e = events(s)
        per[s] = summarise(e)
        for k in allev:
            allev[k] += e[k]
    doc = {"over_at": OVER, "under_at": UNDER, "min_minutes": MIN_MIN, "seasons": list(SEASONS), "both": summarise(allev), "per_season": per}
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print(json.dumps(doc["both"], indent=1)); print(json.dumps(per))


if __name__ == "__main__":
    main()

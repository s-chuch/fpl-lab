"""Backtest ai_team.model_xp against real FPL outcomes and fit a small per-position linear calibration.

Run: python calibrate.py   (downloads vaastav/Fantasy-Premier-League merged_gw.csv to /tmp/claude-0/calib,
fits on 2024-25, grades on 2025-26, writes calibration.json). Runtime code imports apply_calibration().
"""
import csv
import json
import math
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CACHE = Path("/tmp/claude-0/calib")
URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{s}/gws/merged_gw.csv"
OUT = Path(__file__).resolve().parent / "calibration.json"
FIT_SEASON, HOLD_SEASON = "2024-25", "2025-26"
ETYPE = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
POSITIONS = ("GKP", "DEF", "MID", "FWD")
MIN_PRIOR_MINUTES, FIRST_GW = 270, 6


POS_ALIAS = {"GK": "GKP", "AM": "MID"}   # vaastav labels: 2024-25 uses GK and a few AM


def norm_pos(p):
    return POS_ALIAS.get(p, p)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------- pure helpers ----------
def build_el(rows):
    """FPL-bootstrap-like element dict from a player's per-fixture rows (all before the target GW)."""
    mins = sum(_f(r.get("minutes")) for r in rows)
    per90 = lambda k: (sum(_f(r.get(k)) for r in rows) * 90.0 / mins) if mins > 0 else 0.0
    pos = norm_pos(rows[0]["position"]) if rows else "MID"
    return {"element_type": ETYPE.get(pos, 3), "minutes": mins, "status": "a",
            "expected_goals_per_90": per90("expected_goals"), "expected_assists_per_90": per90("expected_assists"),
            "clean_sheets_per_90": per90("clean_sheets"),
            "expected_goals_conceded_per_90": per90("expected_goals_conceded"),
            "saves_per_90": per90("saves"), "defensive_contribution_per_90": per90("defensive_contribution"),
            "bonus": sum(_f(r.get("bonus")) for r in rows)}


def fit_linear(xs, ys, shrink=0.0):
    """OLS y = a + b x; b is pulled toward 1 by `shrink` (0..1), a re-fitted so the means still match."""
    n = len(xs)
    if n < 2:
        return 0.0, 1.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return my - mx, 1.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    b = (1 - shrink) * b + shrink * 1.0
    return my - b * mx, b


def apply_calibration(cal, pos, xp):
    """Calibrated xP for one player (never below 0). cal=None or unknown position -> xp unchanged."""
    p = ((cal or {}).get("per_position") or {}).get(pos)
    if not p:
        return xp
    return max(0.0, p["a"] + p["b"] * xp)


apply = apply_calibration


def _ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2.0 + 1
        i = j + 1
    return r


def _pearson(x, y):
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else 0.0


def metrics(pred, actual):
    n = len(pred)
    if not n:
        return {"n": 0}
    err = [p - a for p, a in zip(pred, actual)]
    a, b = fit_linear(pred, actual)
    return {"n": n, "mae": round(sum(abs(e) for e in err) / n, 4), "rmse": round(math.sqrt(sum(e * e for e in err) / n), 4),
            "pearson": round(_pearson(pred, actual), 4), "spearman": round(_pearson(_ranks(pred), _ranks(actual)), 4),
            "mean_pred": round(sum(pred) / n, 4), "mean_actual": round(sum(actual) / n, 4),
            "slope": round(b, 4), "intercept": round(a, 4)}


def elite_bias(pred, actual, frac=0.1):
    """Mean (pred - actual) over the top `frac` of players by pred."""
    k = max(1, int(len(pred) * frac))
    idx = sorted(range(len(pred)), key=lambda i: -pred[i])[:k]
    return round(sum(pred[i] - actual[i] for i in idx) / k, 4)


# ---------- data ----------
def load_season(season):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{season}.csv"
    if not path.exists():
        urllib.request.urlretrieve(URL.format(s=season), path)
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def backtest(season):
    """List of dicts {pos, gw, xp, fpl_xp, form, actual} for every player-GW with >=270 prior minutes."""
    import ai_team
    by_pl = {}
    for r in load_season(season):
        by_pl.setdefault(r["element"], []).append(r)
    out = []
    for rows in by_pl.values():
        gws = sorted({int(r["round"]) for r in rows})
        for t in gws:
            if t < FIRST_GW:
                continue
            prior = [r for r in rows if int(r["round"]) < t]
            if sum(_f(r["minutes"]) for r in prior) < MIN_PRIOR_MINUTES:
                continue
            cur = [r for r in rows if int(r["round"]) == t]
            el = build_el(prior)
            fixtures = [{"fdr": 3, "opp": "X", "side": "H" if str(r.get("was_home")) == "True" else "A"} for r in cur]
            games = {r["round"] for r in prior}
            form = sum(_f(r["total_points"]) for r in prior) / max(1, len(games))
            out.append({"pos": norm_pos(cur[0]["position"]), "gw": t, "xp": ai_team.model_xp(el, fixtures, t - 1, None, None),
                        "fpl_xp": sum(_f(r["xP"]) for r in cur), "form": form * len(cur),
                        "actual": sum(_f(r["total_points"]) for r in cur)})
    return out


def _col(rows, k, pos=None):
    return [r[k] for r in rows if pos is None or r["pos"] == pos]


def _eval(rows, cal, pos=None):
    sub = [r for r in rows if pos is None or r["pos"] == pos]
    act = [r["actual"] for r in sub]
    cald = [apply_calibration(cal, r["pos"], r["xp"]) for r in sub]
    out = {"uncalibrated": metrics([r["xp"] for r in sub], act), "calibrated": metrics(cald, act),
           "fpl_xp": metrics([r["fpl_xp"] for r in sub], act), "form_baseline": metrics([r["form"] for r in sub], act)}
    out["uncalibrated"]["elite_bias"] = elite_bias([r["xp"] for r in sub], act)
    out["calibrated"]["elite_bias"] = elite_bias(cald, act)
    return out


def main():
    fit_rows, hold_rows = backtest(FIT_SEASON), backtest(HOLD_SEASON)
    per = {}
    for pos in POSITIONS:
        sub = [r for r in fit_rows if r["pos"] == pos]
        a, b = fit_linear(_col(sub, "xp"), _col(sub, "actual"), 0.0)
        # shrink b toward 1 if the fit is extreme (unstable)
        if not 0.6 <= b <= 2.0:
            a, b = fit_linear(_col(sub, "xp"), _col(sub, "actual"), 0.5)
        per[pos] = {"a": round(a, 4), "b": round(b, 4), "n": len(sub)}
    cal = {"per_position": per}
    last = max(r["gw"] for r in hold_rows)
    res = {"overall": _eval(hold_rows, cal), **{p: _eval(hold_rows, cal, p) for p in POSITIONS}}
    doc = {"version": 1, "fitted_on": FIT_SEASON, "holdout": f"{HOLD_SEASON} GW{FIRST_GW}-{last}", "per_position": per,
           "metrics": {"holdout": res["overall"], "holdout_by_position": {p: res[p] for p in POSITIONS}},
           "generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"fit {FIT_SEASON} n={len(fit_rows)}; holdout {doc['holdout']} n={len(hold_rows)}")
    print("pos  a       b       n")
    for p in POSITIONS:
        print(f"{p:4} {per[p]['a']:7.3f} {per[p]['b']:6.3f} {per[p]['n']:6d}")
    print(f"{'holdout':8}{'model':>9}{'MAE':>7}{'RMSE':>7}{'r':>7}{'rho':>7}{'mean':>7}{'slope':>7}{'elite':>7}")
    for key in ("overall",) + POSITIONS:
        for name in ("uncalibrated", "calibrated", "fpl_xp", "form_baseline"):
            m = res[key][name]
            print(f"{key:8}{name[:11]:>12}{m['mae']:7.3f}{m['rmse']:7.3f}{m['pearson']:7.3f}{m['spearman']:7.3f}"
                  f"{m['mean_pred']:7.2f}{m['slope']:7.2f}{m.get('elite_bias', float('nan')):7.2f}")
        print(f"{'':8}{'actual mean':>12}{res[key]['uncalibrated'].get('mean_actual', 0):30.2f}")


if __name__ == "__main__":
    main()

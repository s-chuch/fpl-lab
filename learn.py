"""The model learns from this season's own results.

Every refresh saves each relevant player's inputs and the model's expected points for the next gameweek
(`player_log.json`, column `xp`, the model's number before any correction), and once FPL settles the gameweek
the points he actually scored (`o_pts`). This module compares the two per position and, once there is enough
evidence, nudges future expected points towards what really happens:

    corrected = a + b * model_xp        (per position)

The correction is conservative on purpose: it is pulled towards "no change" until hundreds of player-gameweeks
back it, b is kept between 0.7 and 1.3, and a stays within +-1 point. It is written to `learned.json`, which
`ai_team.adjust_xp` reads, so the AI team, Target, Predictions and the Plan all use the same corrected number.
Backtests on 2 seasons of history showed the model's own knobs (minutes shrink, priors) change nothing
meaningful, so the learnable part is this bias, not the tuning constants."""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path

FILE = Path(__file__).resolve().parent / "learned.json"
POSITIONS = ("GKP", "DEF", "MID", "FWD")
K_SHRINK = 600          # rows at which the learned correction counts for half
MIN_ROWS = 150          # per position before anything is applied
B_RANGE, A_RANGE = (0.7, 1.3), (-1.0, 1.0)


def _ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx < 1e-9:
        return my - mx, 1.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def collect(plog):
    """{pos: [(model xp, actual points)]} from every graded gameweek in player_log."""
    out = {p: [] for p in POSITIONS}
    for g in (plog.get("gws") or {}).values():
        if not g.get("graded"):
            continue
        cols = g.get("cols") or []
        try:
            ip, ix, io = cols.index("pos"), cols.index("xp"), cols.index("o_pts")
        except ValueError:
            continue
        for r in g.get("rows") or []:
            if len(r) > io and r[ip] in out and r[ix] is not None and r[io] is not None:
                out[r[ip]].append((float(r[ix]), float(r[io])))
    return out


START_K = 40            # graded doubted player-gameweeks in a fitness band before it moves at all (and half-way at 2x this)
START_BANDS = (("25", 0.0, 0.375), ("50", 0.375, 0.625), ("75", 0.625, 0.95))     # by FPL chance of playing (fit players are 0.95+)
START_MULT = (0.5, 1.5)


def collect_start(plog):
    """[(avail, model start chance before any correction, started 0/1)] from graded gameweeks that logged p_start."""
    out = []
    for g in (plog.get("gws") or {}).values():
        if not g.get("graded"):
            continue
        cols = g.get("cols") or []
        try:
            ia, ip, io = cols.index("avail"), cols.index("p_start"), cols.index("o_start")
        except ValueError:
            continue
        for r in g.get("rows") or []:
            if len(r) > io and r[ip] is not None and r[io] is not None and r[ia] is not None:
                out.append((float(r[ia]), float(r[ip]), int(r[io])))
    return out


def fit_start(plog):
    """How well the start model did, by fitness band, and the multiplier that would fix each doubt band (shrunk; applied from START_K rows).
    -> (per-band dict read by start_model, calibration for the Scorecard)."""
    rows = collect_start(plog)
    per = {}
    for name, lo, hi in START_BANDS:
        sub = [r for r in rows if lo <= r[0] < hi and r[0] > 0]
        n = len(sub)
        row = {"n": n, "mult": 1.0, "applied": False}
        if n:
            pred, act = sum(r[1] for r in sub) / n, sum(r[2] for r in sub) / n
            row.update({"pred": round(pred, 3), "actual": round(act, 3)})
            if pred > 0:
                ratio = act / pred
                k = n / (n + START_K)
                row["mult"] = round(max(START_MULT[0], min(START_MULT[1], 1 + (ratio - 1) * k)), 3)
                row["applied"] = n >= START_K
        per[name] = row
    cal = []
    for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
        sub = [r for r in rows if lo <= r[1] < hi]
        if sub:
            cal.append({"lo": lo, "hi": min(hi, 1.0), "n": len(sub), "pred": round(sum(r[1] for r in sub) / len(sub), 3), "actual": round(sum(r[2] for r in sub) / len(sub), 3)})
    brier = round(sum((r[1] - r[2]) ** 2 for r in rows) / len(rows), 4) if rows else None
    return per, {"n": len(rows), "brier": brier, "bands": cal}


def gw_summary(plog):
    """Per graded gameweek: players, mean model xp, mean actual, mean absolute error; plus the latest gameweek's biggest misses (ids; the page adds names)."""
    by, misses = [], None
    for key, g in sorted((plog.get("gws") or {}).items(), key=lambda kv: int(kv[0])):
        if not g.get("graded"):
            continue
        cols = g.get("cols") or []
        try:
            ii, ip, ix, io, im = (cols.index(c) for c in ("id", "pos", "xp", "o_pts", "o_min"))
        except ValueError:
            continue
        rows = [r for r in g.get("rows") or [] if len(r) > io and r[ix] is not None and r[io] is not None]
        if not rows:
            continue
        by.append({"gw": int(key), "n": len(rows), "xp": round(sum(r[ix] for r in rows) / len(rows), 2), "actual": round(sum(r[io] for r in rows) / len(rows), 2),
                   "mae": round(sum(abs(r[ix] - r[io]) for r in rows) / len(rows), 2)})
        played = [r for r in rows if (r[im] or 0) > 0]          # a player who did not play is a minutes miss, not a points-model miss
        ranked = sorted(played, key=lambda r: r[io] - r[ix])
        pick = lambda r: {"id": r[ii], "pos": r[ip], "xp": round(r[ix], 1), "actual": r[io], "min": r[im]}
        misses = {"gw": int(key), "under": [pick(r) for r in ranked[::-1][:5]], "over": [pick(r) for r in ranked[:5]]}
    return by, misses


def fit(plog, now=None):
    data = collect(plog)
    per, before, after = {}, [], []
    for pos in POSITIONS:
        pts = data[pos]
        n = len(pts)
        row = {"n": n, "a": 0.0, "b": 1.0, "applied": False}
        if n >= 20:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            a, b = _ols(xs, ys)
            k = n / (n + K_SHRINK)
            b_s = 1 + (b - 1) * k
            b_s = max(B_RANGE[0], min(B_RANGE[1], b_s))
            a_s = (sum(ys) / n - b_s * sum(xs) / n) * k
            a_s = max(A_RANGE[0], min(A_RANGE[1], a_s))
            row.update({"a_raw": round(a, 3), "b_raw": round(b, 3), "mean_xp": round(sum(xs) / n, 2), "mean_actual": round(sum(ys) / n, 2),
                        "mae": round(sum(abs(x - y) for x, y in pts) / n, 2)})
            if n >= MIN_ROWS:
                row.update({"a": round(a_s, 3), "b": round(b_s, 3), "applied": True})
            before += [abs(x - y) for x, y in pts]
            after += [abs(max(0.0, row["a"] + row["b"] * x) - y) for x, y in pts]
        per[pos] = row
    doc = {"version": 1, "updated": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "gws": sorted(g["gw"] for g in (plog.get("gws") or {}).values() if g.get("graded")),
            "per_position": per,
            "mae_before": round(sum(before) / len(before), 3) if before else None,
            "mae_after": round(sum(after) / len(after), 3) if after else None,
            "applied": any(r["applied"] for r in per.values())}
    doc["by_gw"], doc["misses"] = gw_summary(plog)
    doc["start"], doc["start_cal"] = fit_start(plog)
    return doc


def update(plog, path=FILE):
    doc = fit(plog)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n")
    os.replace(tmp, path)
    return doc


def load(path=FILE):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}

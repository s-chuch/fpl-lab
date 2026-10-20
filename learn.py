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
            row.update({"a_raw": round(a, 3), "b_raw": round(b, 3), "mean_xp": round(sum(xs) / n, 2), "mean_actual": round(sum(ys) / n, 2)})
            if n >= MIN_ROWS:
                row.update({"a": round(a_s, 3), "b": round(b_s, 3), "applied": True})
            before += [abs(x - y) for x, y in pts]
            after += [abs(max(0.0, row["a"] + row["b"] * x) - y) for x, y in pts]
        per[pos] = row
    return {"version": 1, "updated": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "gws": sorted(g["gw"] for g in (plog.get("gws") or {}).values() if g.get("graded")),
            "per_position": per,
            "mae_before": round(sum(before) / len(before), 3) if before else None,
            "mae_after": round(sum(after) / len(after), 3) if after else None,
            "applied": any(r["applied"] for r in per.values())}


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

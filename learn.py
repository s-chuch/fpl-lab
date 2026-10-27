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


# --------------------------------------------------------------------------- which ingredient is wrong?
FACTOR_K = 80           # flagged player-gameweeks at which a learned multiplier counts for half (against today's constant)
FACTOR_MIN = 60         # flagged player-gameweeks before it is used at all
FACTOR_RANGE = (0.6, 1.1)
TOP_XP = 5.0            # corrected expected points from which a player is in the captain pool
TOP_K, TOP_MIN, TOP_RANGE = 120, 40, (-1.5, 1.5)
ELITE_K, ELITE_MIN, ELITE_PRIOR = 300, 150, 0.4
CAP_K, CAP_MIN, CAP_MAX = 200, 60, 0.5


def _named(plog):
    """Every graded row as a dict keyed by column name (only gameweeks that saved the column set)."""
    for g in (plog.get("gws") or {}).values():
        if not g.get("graded"):
            continue
        cols = g.get("cols") or []
        if "o_pts" not in cols or "xp" not in cols:
            continue
        for r in g.get("rows") or []:
            if len(r) >= len(cols):
                yield dict(zip(cols, r))


def _corrected(row, per):
    c = (per or {}).get(row.get("pos")) or {}
    x = float(row["xp"])
    return max(0.0, c.get("a", 0.0) + c.get("b", 1.0) * x) if c.get("applied") and x > 0 else x


def fit_factors(plog, priors=None):
    """Test each hand-set multiplier (rest, minutes falling, reported rotation) against results: actual points of players carrying only that
    flag, against what the model would have said without it, relative to the same ratio for players with no flag at all (same position).
    Shrunk towards today's constant, bounded, used from FACTOR_MIN flagged player-gameweeks."""
    if priors is None:
        import ai_team
        priors = {"rest": ai_team.REST_FACTOR, "minutes": ai_team.MINUTES_FALLING_FACTOR, "rotation": ai_team.ROTATION_REPORTED_FACTOR}
    rows = [r for r in _named(plog) if r.get("fac") is not None and r.get("xp") is not None and r.get("o_pts") is not None and r["fac"] > 0]
    out = {}
    base = {}
    for pos in POSITIONS:
        sub = [r for r in rows if r["pos"] == pos and abs(r["fac"] - 1.0) < 1e-6 and r["xp"] > 0]
        den = sum(r["xp"] for r in sub)
        base[pos] = (sum(r["o_pts"] for r in sub) / den) if den > 0 else None
    flag = {"rest": lambda r: r.get("f_rest", 0) >= 1 and not r.get("f_min") and not r.get("f_rot"),
            "minutes": lambda r: r.get("f_min") and not r.get("f_rest") and not r.get("f_rot"),
            "rotation": lambda r: r.get("f_rot") and not r.get("f_rest") and not r.get("f_min")}
    for label, prior in priors.items():
        sel = [r for r in rows if flag[label](r) and r["xp"] > 0]
        n = len(sel)
        row = {"n": n, "prior": prior, "factor": prior, "applied": False}
        if n:
            num = wsum = 0.0
            counts = []
            for pos in POSITIONS:
                ps = [r for r in sel if r["pos"] == pos]
                den = sum(r["xp"] / r["fac"] for r in ps)
                if not ps or den <= 0 or not base.get(pos):
                    continue
                num += len(ps) * (sum(r["o_pts"] for r in ps) / den) / base[pos]
                wsum += len(ps)
                counts += [max(1, r.get("f_rest", 1)) if label == "rest" else 1 for r in ps]
            if wsum:
                total = num / wsum                         # the combined effect of every copy of this flag, relative to unflagged
                per_flag = total ** (1.0 / (sum(counts) / len(counts)))
                k = n / (n + FACTOR_K)
                f = prior + (per_flag - prior) * k
                f = max(FACTOR_RANGE[0], min(FACTOR_RANGE[1], f))
                row.update({"raw": round(per_flag, 3), "factor": round(f, 3), "applied": n >= FACTOR_MIN})
        out[label] = row
    return out


def fit_top(plog, per):
    """Do the players the model rates highest (the captain pool) score what it says? A shrunk, bounded shift for corrected xp >= TOP_XP."""
    res = []
    for r in _named(plog):
        if r.get("xp") is None or r.get("o_pts") is None:
            continue
        c = _corrected(r, per)
        if c >= TOP_XP:
            res.append(r["o_pts"] - c)
    n = len(res)
    row = {"n": n, "shift": 0.0, "applied": False, "min_xp": TOP_XP}
    if n:
        raw = sum(res) / n
        s = max(TOP_RANGE[0], min(TOP_RANGE[1], raw * n / (n + TOP_K)))
        row.update({"raw": round(raw, 3), "shift": round(s, 3), "applied": n >= TOP_MIN})
    return row


def _slope(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    return (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx) if sxx > 1e-9 else 0.0


def fit_elite(plog, per):
    """Do players the top-50 managers hold / captain beat the model's number? Own weight replaces the hand-set 0.4 in the transfer bonus
    (bonus = weight x min(1, ownership / 50%)); the captain weight is a bounded tie-break on the AI's captain choice."""
    rows = [r for r in _named(plog) if r.get("e_own") is not None and r.get("xp") is not None and r.get("o_pts") is not None]
    out = {"own_n": len(rows), "own_weight": ELITE_PRIOR, "own_applied": False, "cap_n": 0, "cap_weight": 0.0, "cap_applied": False}
    if len(rows) >= 20:
        res = {}
        for r in rows:
            res.setdefault(r["pos"], []).append(r["o_pts"] - _corrected(r, per))
        mean = {p: sum(v) / len(v) for p, v in res.items()}
        xs = [r["e_own"] for r in rows]
        ys = [r["o_pts"] - _corrected(r, per) - mean[r["pos"]] for r in rows]
        slope = _slope(xs, ys)                               # points per 100% of the top 50 owning him
        k = len(rows) / (len(rows) + ELITE_K)
        w = max(0.0, min(1.2, ELITE_PRIOR + (slope * 0.5 - ELITE_PRIOR) * k))
        out.update({"own_slope": round(slope, 3), "own_weight": round(w, 3), "own_applied": len(rows) >= ELITE_MIN})
    pool = [r for r in rows if r.get("e_cap") is not None and _corrected(r, per) >= 4.0]
    out["cap_n"] = len(pool)
    if len(pool) >= 20:
        slope = _slope([r["e_cap"] for r in pool], [r["o_pts"] - _corrected(r, per) for r in pool])
        k = len(pool) / (len(pool) + CAP_K)
        out.update({"cap_slope": round(slope, 3), "cap_weight": round(max(0.0, min(CAP_MAX, slope * k)), 3), "cap_applied": len(pool) >= CAP_MIN})
    return out


def fit_transfers(reviews):
    """Realised points of the players brought in against the model's expected gap, over every settled gameweek's transfers (the AI's own ledger).
    If the model keeps promising more than the moves deliver, the free-move hurdle is raised (x1 to x2)."""
    pred = real = 0.0
    n = 0
    for rv in (reviews or {}).values():
        for m in rv.get("transfers") or []:
            if m.get("pred") is None or m.get("real") is None:
                continue
            pred += m["pred"]; real += m["real"]; n += 1
    row = {"n": n, "mult": 1.0, "applied": False}
    if n and pred > 0:
        ratio = real / pred
        k = n / (n + 10)
        mult = 1.0 + (1.0 / max(0.5, min(1.0, ratio)) - 1.0) * k
        row.update({"ratio": round(ratio, 3), "mult": round(max(1.0, min(2.0, mult)), 3), "applied": n >= 10 and ratio < 0.8})
    return row


def fit(plog, now=None, reviews=None):
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
    doc["factors"] = fit_factors(plog)
    doc["top"] = fit_top(plog, per)
    doc["elite"] = fit_elite(plog, per)
    doc["transfers"] = fit_transfers(reviews)
    doc["start"], doc["start_cal"] = fit_start(plog)
    return doc


def update(plog, path=FILE, reviews=None):
    doc = fit(plog, reviews=reviews)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n")
    os.replace(tmp, path)
    return doc


def load(path=FILE):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}

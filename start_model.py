"""Chance a player starts next gameweek: the model fitted by calibrate_start.py (start_model.json) on his starts / minutes history,
times a fitness multiplier for doubts and a factor for reported rotation.

* base: logistic on season starts / minutes share and his last three matches (backtest Brier 0.1445 vs 0.158 for the hand-built
  formulas it replaced; days of rest and home/away added nothing, so they are not used).
* fitness: FPL's chance of playing is the chance he plays at all, and a doubt who does play often starts on the bench, so the start
  chance is cut harder than the percentage: DOUBT_PRIOR (a judgement from FPL community evidence; no flag history exists to fit it).
  `learned.json` ("start" block, written by learn.py) moves each band once this season's graded results back it.
* reported rotation (news verdict): the existing 0.8 factor, passed in by the caller."""
from __future__ import annotations
import json
import math
from pathlib import Path

import fitness

ROOT = Path(__file__).resolve().parent
DOUBT_PRIOR = ((0, 0.0), (25, 0.15), (50, 0.35), (75, 0.70), (100, 1.0))
BANDS = ((0, 37), (38, 62), (63, 87))           # FPL percentages grouped for learning: 25 / 50 / 75 (100 = fit, never adjusted)
MIN_TEAM_MATCHES = 3       # (the fit used players with 270+ prior minutes, but backtested on players with less it still calibrates: low minutes who started 2 of the last 3 -> said 54%, did 58%)
REC_W = (0.2, 0.3, 0.5)


def _load(name):
    try:
        return json.loads((ROOT / name).read_text())
    except (OSError, ValueError):
        return {}


MODEL = _load("start_model.json")


def _learned():
    L = (_load("learned.json").get("start") or {})
    return {k: v["mult"] for k, v in L.items() if v.get("applied")}


LEARNED = _learned()


def band_of(pct):
    """'25' / '50' / '75' for a doubt, None for a fit player."""
    if pct >= 100:
        return None
    for (lo, hi), name in zip(BANDS, ("25", "50", "75")):
        if lo <= pct <= hi:
            return name
    return "75"


def doubt_factor(pct, learned=None):
    """Multiplier on the start chance for FPL's chance of playing (0-100): prior table, linear between points, times the learned band correction."""
    pct = max(0.0, min(100.0, float(pct)))
    f = 1.0
    for (x0, y0), (x1, y1) in zip(DOUBT_PRIOR, DOUBT_PRIOR[1:]):
        if x0 <= pct <= x1:
            f = y0 + (y1 - y0) * (pct - x0) / (x1 - x0)
            break
    b = band_of(pct)
    L = LEARNED if learned is None else learned
    return max(0.0, min(1.0, f * L.get(b, 1.0))) if b else f


def features(starts, mins, team_matches):
    """starts / mins: per match he could have played, oldest first (at least 3). Same arithmetic as calibrate_start.features_from."""
    ss = sum(starts) / team_matches
    ms = sum(mins) / (90.0 * team_matches)
    rec = sum(w * s for w, s in zip(REC_W, starts[-3:])) / sum(REC_W)
    m3 = sum(min(90, m) / 90.0 for m in mins[-3:]) / 3.0
    return [ss, ms, starts[-1], starts[-2], starts[-3], rec, m3]


def base_start(el, recent, team_matches):
    """Chance he starts if fully fit. recent = [{"min", "starts"}] for his last gameweeks (oldest first); team_matches = matches his club has played."""
    tm = max(1, int(team_matches or 0))
    season_min = float(el.get("minutes") or 0)
    ss = min(1.0, (el.get("starts") or 0) / tm)
    if not MODEL or tm < MIN_TEAM_MATCHES or not recent or len(recent) < 3:
        return max(0.0, min(1.0, 0.5 * min(1.0, season_min / (90.0 * tm)) + 0.5 * ss))     # new / returning player: his season share
    r = recent[-3:]
    starts = [min(1, int(x.get("starts") or (1 if (x.get("min") or 0) >= 60 else 0))) for x in r]
    mins = [min(90, float(x.get("min") or 0)) for x in r]
    # season totals feed ss / ms; the last three matches feed the rest
    ss_, ms_ = ss, min(1.0, season_min / (90.0 * tm))
    rec = sum(w * s for w, s in zip(REC_W, starts)) / sum(REC_W)
    m3 = sum(m / 90.0 for m in mins) / 3.0
    x = [ss_, ms_, starts[2], starts[1], starts[0], rec, m3]
    z = MODEL["weights"][0] + sum(w * (v - mu) / sd for w, v, mu, sd in zip(MODEL["weights"][1:], x, MODEL["mu"], MODEL["sd"]))
    return 1.0 / (1.0 + math.exp(-z))


def start_prob(el, recent, team_matches, rotation_factor=1.0, learned=None):
    """-> {"p": corrected start chance, "raw": before the learned correction, "base": fully fit, "fit": fitness pct, "doubt": factor}."""
    pct, _src = fitness.chance(el)
    base = base_start(el, recent, team_matches)
    prior = doubt_factor(pct, learned={})                     # the prior table only (what is logged and learned from)
    raw = max(0.0, min(1.0, base * prior * rotation_factor))
    p = max(0.0, min(1.0, base * doubt_factor(pct, learned) * rotation_factor))
    return {"p": p, "raw": raw, "base": base, "fit": pct, "doubt": prior}

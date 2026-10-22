"""Fit the "will he start?" model on real FPL history and write start_model.json.

Run: python calibrate_start.py   (uses the vaastav merged_gw.csv files that calibrate.py downloads to /tmp/claude-0/calib).
Target: did the player start the gameweek (FPL `starts` > 0). Features come only from earlier gameweeks, so it is a true forecast:
season starts share, season minutes share, started the last match / 2 / 3 matches ago, a recency-weighted last-3 starts figure and the
last-3 minutes share. Logistic regression with a light ridge penalty, fitted on 2024-25 and graded on 2025-26 (Brier score against the
base rate and against the older hand-built formulas), then refitted on both seasons for use.

Backtest findings (see CLAUDE.md): recent minutes / starts history carries the signal; days of rest and home/away add nothing."""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibrate as C

OUT = Path(__file__).resolve().parent / "start_model.json"
FEATURES = ["ss", "ms", "s1", "s2", "s3", "rec", "m3"]
REC_W = (0.2, 0.3, 0.5)
MIN_PRIOR_MINUTES, FIRST_ROUND, MIN_TEAM_MATCHES = 270, 5, 3


def history(season):
    rows = C.load_season(season)
    pl, team_k = defaultdict(dict), defaultdict(dict)
    for r in rows:
        rd = int(r["round"])
        k = datetime.fromisoformat(r["kickoff_time"].replace("Z", "+00:00"))
        d = pl[r["element"]].setdefault(rd, {"min": 0.0, "st": 0, "team": r["team"]})
        d["min"] += float(r["minutes"]); d["st"] = max(d["st"], int(float(r["starts"] or 0)))
        t = team_k[r["team"]]
        if rd not in t or k < t[rd]:
            t[rd] = k
    return pl, team_k


def features_from(starts, mins, team_matches):
    """Same arithmetic the live site uses (start_model.features): `starts` / `mins` are per team match, oldest first."""
    pm = sum(mins)
    ss = sum(starts) / team_matches
    ms = pm / (90.0 * team_matches)
    l = starts[-3:]
    rec = sum(w * s for w, s in zip(REC_W, l)) / sum(REC_W)
    m3 = sum(min(90, m) / 90.0 for m in mins[-3:]) / 3.0
    return [ss, ms, starts[-1], starts[-2], starts[-3], rec, m3]


def dataset(season):
    pl, team_k = history(season)
    X, y = [], []
    for rds in pl.values():
        for t, cur in rds.items():
            if t < FIRST_ROUND:
                continue
            tr = sorted(r for r in team_k[cur["team"]] if r < t)
            if len(tr) < MIN_TEAM_MATCHES:
                continue
            prior = [rds.get(r) for r in tr]
            mins = [(p["min"] if p else 0.0) for p in prior]
            if sum(mins) < MIN_PRIOR_MINUTES:
                continue
            starts = [(1 if (p and p["st"]) else 0) for p in prior]
            X.append(features_from(starts, mins, len(tr))); y.append(1 if cur["st"] > 0 else 0)
    return np.array(X), np.array(y)


def irls(X, y, l2=1.0, it=60):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.c_[np.ones(len(X)), (X - mu) / sd]
    w = np.zeros(Z.shape[1])
    pen = np.diag(np.r_[0, np.ones(Z.shape[1] - 1)])
    for _ in range(it):
        p = 1 / (1 + np.exp(-Z @ w))
        W = p * (1 - p) + 1e-9
        w = w + np.linalg.solve((Z.T * W) @ Z + l2 * pen, Z.T @ (y - p) - l2 * np.r_[0, w[1:]])
    return w, mu, sd


def predict(model, X):
    w, mu, sd = model
    return 1 / (1 + np.exp(-(np.c_[np.ones(len(X)), (X - mu) / sd] @ w)))


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def bands(p, y, n=5):
    return [{"pred": round(float(p[i].mean()), 3), "actual": round(float(y[i].mean()), 3), "n": int(len(i))} for i in np.array_split(np.argsort(p), n)]


def old_formulas(X):
    """The two hand-built figures this replaced: minutes-share x rest (rest ignored here: it never mattered) and the 40/60 starts blend."""
    ss, ms, rec, m3 = X[:, 0], X[:, 1], X[:, 5], X[:, 6]
    a = np.clip(np.minimum(1, 0.5 * ms + 0.5 * m3), 0, 1)
    b = np.clip(0.4 * ss + 0.6 * rec, 0, 1)
    return a, b


def main():
    Xa, ya = dataset(C.FIT_SEASON)
    Xb, yb = dataset(C.HOLD_SEASON)
    m = irls(Xa, ya)
    p = predict(m, Xb)
    a, b = old_formulas(Xb)
    metrics = {"holdout_n": int(len(yb)), "base_rate": round(float(yb.mean()), 4),
               "brier_model": round(brier(p, yb), 4), "brier_minutes_share": round(brier(a, yb), 4),
               "brier_starts_blend": round(brier(b, yb), 4), "brier_constant": round(brier(np.full(len(yb), ya.mean()), yb), 4),
               "calibration": bands(p, yb)}
    final = irls(np.vstack([Xa, Xb]), np.concatenate([ya, yb]))
    doc = {"version": 1, "features": FEATURES, "rec_weights": list(REC_W), "weights": [round(float(x), 5) for x in final[0]],
           "mu": [round(float(x), 5) for x in final[1]], "sd": [round(float(x), 5) for x in final[2]],
           "fitted_on": f"{C.FIT_SEASON} + {C.HOLD_SEASON} (holdout metrics: fit {C.FIT_SEASON}, graded {C.HOLD_SEASON})",
           "metrics": metrics, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print(json.dumps(metrics, indent=1))
    print("weights", dict(zip(["bias"] + FEATURES, doc["weights"])))


if __name__ == "__main__":
    main()

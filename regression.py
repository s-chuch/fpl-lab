"""Tracks players flagged as over- or underperforming their expected numbers and shows whether they are actually returning to them.

For every player on the XGA lists (your squad, top over / under, defence running lucky) plus anyone flagged earlier (`regression_log.json`),
FPL's per-gameweek history (element-summary) gives goals, assists, xG, xA, goals conceded and xGC for each match, so the season "gap" can be
rebuilt gameweek by gameweek without having saved anything:
  attackers (MID / FWD): gap = goals + assists - (xG + xA)       positive = running hot
  defenders / keepers  : gap = xGC - goals conceded               positive = running lucky
A positive gap that falls, or a negative one that rises, is regression; the status says which way each player is heading.
`regression_baseline.json` (calibrate_regression.py) records how fast flagged attackers really returned to expectation in two seasons of history."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "regression_log.json"
BASELINE = ROOT / "regression_baseline.json"
MAX_TRACKED = 45
BACK_AT = 1.0            # |gap| under this = back to the mean
MOVE = 0.5               # last-four-gameweek swing needed to call a player heating up or cooling down
KEEP_BACK_GWS = 3        # a player stays on the page this many gameweeks after he is back to the mean


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def series(history, pos, last_gw):
    """[(gw, cumulative gap)] for gameweeks 1..last_gw; per-gameweek gaps are the differences. history = element-summary["history"]."""
    per = {}
    for h in history or []:
        g = int(h["round"])
        if g > last_gw:
            continue
        if pos in ("DEF", "GKP"):
            v = _f(h.get("expected_goals_conceded")) - _f(h.get("goals_conceded")) if _f(h.get("minutes")) > 0 else 0.0
        else:
            v = _f(h.get("goals_scored")) + _f(h.get("assists")) - _f(h.get("expected_goals")) - _f(h.get("expected_assists"))
        per[g] = per.get(g, 0.0) + v
    out, cum = [], 0.0
    for g in range(1, last_gw + 1):
        cum += per.get(g, 0.0)
        out.append((g, round(cum, 2)))
    return out


def status(gaps, over_at=2.0, under_at=1.5):
    """(code, label) from the cumulative gaps. s = +1 for a player ahead of expectation, -1 for one behind."""
    now = gaps[-1][1]
    s = 1 if now >= 0 else -1
    peak = max((abs(v) for _, v in gaps if v * s > 0), default=0.0)
    if abs(now) < BACK_AT and peak >= under_at:
        return "back", "Back to the mean"
    win = [v * s for _, v in gaps[-5:]]                      # the last four gameweeks' movement, signed so that positive = further from the mean
    if win[-1] <= max(win) - MOVE or win[-1] - win[0] <= -MOVE:
        return "reverting", "Cooling" if s > 0 else "Warming up"
    if win[-1] - win[0] >= MOVE:
        return "widening", "Still running hot" if s > 0 else "Still cold"
    return "holding", "Holding"


def _ids(boot, xg):
    by = {}
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    for e in boot["elements"]:
        by[(e["web_name"], teams.get(e["team"]))] = e["id"]
    ids, owned = [], set()
    for src, key in (("rows", "rows"), ("top_over", None), ("top_under", None), ("top_def_lucky", None)):
        for r in xg.get(src) or []:
            i = by.get((r["name"], r["club"]))
            if i is None:
                continue
            if src == "rows":
                owned.add(i)
                if r.get("tag") not in ("overperforming", "underperforming") and r.get("gc_tag") not in ("riding_luck", "unlucky"):
                    continue
            if i not in ids:
                ids.append(i)
    return ids, owned


def load_log(path=LOG):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def save_log(doc, path=LOG):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def build_regression(boot, xg, get, last_gw, log_path=LOG, baseline_path=BASELINE):
    """data["regression"]: one row per tracked player. `get` is the FPL GET helper; `last_gw` the last finished gameweek."""
    if not xg or not last_gw:
        return {}
    log = load_log(log_path)
    flagged = log.get("flagged") or {}
    ids, owned = _ids(boot, xg)
    for k in flagged:                                     # earlier flags stay on the page until they have been back to the mean for a while
        if int(k) not in ids:
            ids.append(int(k))
    ids = ids[:MAX_TRACKED]
    els = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    pos_of = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    def fetch(i):
        try:
            return i, get(f"https://fantasy.premierleague.com/api/element-summary/{i}/").get("history") or []
        except Exception:
            return i, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        hist = dict(pool.map(fetch, ids))
    rows = []
    for i in ids:
        h, el = hist.get(i), els.get(i)
        if h is None or not el:
            continue
        pos = pos_of[el["element_type"]]
        gaps = series(h, pos, last_gw)
        if len(gaps) < 3:
            continue
        code, label = status(gaps)
        now = gaps[-1][1]
        s = 1 if now >= 0 else -1
        peak_gw, peak = max(((g, v) for g, v in gaps), key=lambda gv: gv[1] * s)
        first = next((g for g, v in gaps if v * s >= (2.0 if s > 0 else 1.5)), None)
        rec = flagged.get(str(i))
        if first is not None and code != "back":
            rec = flagged.setdefault(str(i), {"flag_gw": first, "side": "over" if s > 0 else "under", "name": el["web_name"]})
        if code == "back":
            if rec is not None and rec.get("back_gw") is None:
                rec["back_gw"] = last_gw
        elif rec is not None:
            rec["back_gw"] = None
        if code == "back" and rec is None:
            continue                                      # was never flagged: nothing to report
        last4 = round(gaps[-1][1] - gaps[-5][1], 2) if len(gaps) >= 5 else round(gaps[-1][1], 2)
        rows.append({"id": i, "name": el["web_name"], "club": teams.get(el["team"]), "pos": pos, "kind": "luck" if pos in ("DEF", "GKP") else "att",
                     "side": "over" if s > 0 else "under", "gap": now, "peak": round(peak, 2), "peak_gw": peak_gw, "flag_gw": (rec or {}).get("flag_gw", first),
                     "back_gw": (rec or {}).get("back_gw"), "last4": last4, "status": code, "label": label, "yours": i in owned,
                     "owned_pct": _f(el.get("selected_by_percent")), "series": [v for _, v in gaps[-12:]], "first_gw": gaps[-12:][0][0]})
    keep = {}
    for k, rec in flagged.items():                         # drop entries that have been back to the mean for a few gameweeks
        if rec.get("back_gw") is not None and last_gw - rec["back_gw"] >= KEEP_BACK_GWS:
            continue
        keep[k] = rec
    rows = [r for r in rows if not (r["status"] == "back" and r["back_gw"] is not None and last_gw - r["back_gw"] >= KEEP_BACK_GWS)]
    save_log({"flagged": keep, "gw": last_gw}, log_path)
    try:
        base = json.loads(Path(baseline_path).read_text())
    except (OSError, ValueError):
        base = None
    rows.sort(key=lambda r: (r["status"] == "back", -abs(r["gap"])))
    return {"gw": last_gw, "rows": rows, "baseline": base}

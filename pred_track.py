"""Prediction log: what the Predictions box said for each gameweek (top 10 per category), frozen when the deadline passes,
graded against FPL's final numbers once the gameweek is settled, and turned into a hit rate, a calibration factor and a
plain-English "why it missed" count that feed back into the next predictions.

Categories: goals (scores at least one), assists (at least one), clean_sheets (the club concedes none), defcon (reaches the
defensive-contribution threshold). Stored in its own committed file (prediction_log.json / bacalhau-prediction_log.json).
Pure functions take their inputs; only grade() talks to FPL (through the `get` it is given)."""
from __future__ import annotations
import json, os
from pathlib import Path

CATS = ("goals", "assists", "clean_sheets", "defcon")
LABEL = {"goals": "Goals", "assists": "Assists", "clean_sheets": "Clean sheets", "defcon": "DEFCON"}
DEFCON_THR = {2: 10, 3: 12, 4: 12}          # element_type -> defensive contributions needed for the +2
MIN_FOR_SCALE = 30                          # graded picks before a category's probabilities are rescaled
SCALE_RANGE = (0.6, 1.4)
SHRINK = 40                                 # pseudo-picks pulling the scale towards 1


def log_path(data_file):
    data_file = Path(data_file)
    stem = data_file.name[:-len("-data.js")] if data_file.name.endswith("-data.js") else ""
    return data_file.with_name((stem + "-" if stem else "") + "prediction_log.json")


def load(path):
    try:
        d = json.loads(Path(path).read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save(path, log):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(log, separators=(",", ":"), ensure_ascii=False))
    os.replace(tmp, path)


# ---------------------------------------------------------------- calibration
def calibration(log):
    """{cat: {n, mean_p, hit_rate, scale}} from every graded pick. scale = how much to multiply a raw probability by: actual hit
    rate over the average prediction, shrunk towards 1 while there is little history, and only used from MIN_FOR_SCALE picks."""
    out = {}
    for c in CATS:
        n = hits = 0
        sp = 0.0
        for g in (log.get("gws") or {}).values():
            if not g.get("graded"):
                continue
            for pick, res in zip((g.get("picks") or {}).get(c, []), (g.get("results") or {}).get(c, [])):
                n += 1
                hits += 1 if res.get("hit") else 0
                sp += pick.get("raw", pick.get("p", 0)) / 100.0
        row = {"n": n, "mean_p": round(100 * sp / n) if n else None, "hit_rate": round(100 * hits / n) if n else None, "scale": 1.0}
        if n >= MIN_FOR_SCALE and sp > 0:
            raw = (hits / n) / (sp / n)
            row["scale"] = round(max(SCALE_RANGE[0], min(SCALE_RANGE[1], 1 + (raw - 1) * n / (n + SHRINK))), 3)
        out[c] = row
    return out


def scales(log):
    return {c: v["scale"] for c, v in calibration(log).items()}


# ---------------------------------------------------------------- recording
def record(log, gw, picks, now):
    """Store (or refresh, until the deadline passes) the predictions for `gw`. `picks` = {cat: [{id|club, name, p, raw, ...}]}.
    A graded gameweek is never touched."""
    gws = log.setdefault("gws", {})
    g = gws.get(str(gw))
    if g and g.get("graded"):
        return log
    gws[str(gw)] = {"gw": gw, "made_at": now.isoformat(), "picks": picks, "graded": False}
    return log


# ---------------------------------------------------------------- grading
def grade_pick(cat, pick, live, fixtures, boot_el):
    """-> {hit, why} for one pick. live = {element id: stats}; fixtures = this gameweek's finished fixtures; boot_el = {id: element}."""
    if cat == "clean_sheets":
        tid = pick.get("team")
        mine = [f for f in fixtures if tid in (f["team_h"], f["team_a"])]
        if not mine:
            return {"hit": False, "why": "no match played"}
        conceded = [(f["team_a_score"] if f["team_h"] == tid else f["team_h_score"]) or 0 for f in mine]
        if any(c == 0 for c in conceded):
            return {"hit": True, "why": "kept a clean sheet"}
        return {"hit": False, "why": f"conceded {sum(conceded)}"}
    st = live.get(pick["id"]) or {}
    mins = int(st.get("minutes") or 0)
    el = boot_el.get(pick["id"]) or {}
    tid = el.get("team")
    mine = [f for f in fixtures if tid in (f["team_h"], f["team_a"])]
    scored = sum((f["team_h_score"] if f["team_h"] == tid else f["team_a_score"]) or 0 for f in mine)
    if cat in ("goals", "assists"):
        n = int(st.get("goals_scored" if cat == "goals" else "assists") or 0)
        word = "goal" if cat == "goals" else "assist"
        if n > 0:
            return {"hit": True, "why": f"{n} {word}{'s' if n > 1 else ''}"}
        if mins == 0:
            return {"hit": False, "why": "did not play"}
        if mins < 60:
            return {"hit": False, "why": f"only {mins} minutes"}
        return {"hit": False, "why": "team did not score" if scored == 0 else f"played {mins} min, team scored {scored}, no {word}"}
    if cat == "defcon":
        v = int(st.get("defensive_contribution") or 0)
        thr = DEFCON_THR.get(el.get("element_type"), 12)
        if v >= thr:
            return {"hit": True, "why": f"{v} contributions (needed {thr})"}
        if mins == 0:
            return {"hit": False, "why": "did not play"}
        if mins < 60:
            return {"hit": False, "why": f"only {mins} minutes"}
        return {"hit": False, "why": f"{v} of {thr} contributions"}
    return {"hit": False, "why": ""}


def grade(log, boot, get):
    """Grade every finished, data-checked gameweek that has a frozen prediction and no grade yet."""
    done = {e["id"] for e in boot["events"] if e.get("finished") and e.get("data_checked")}
    boot_el = {e["id"]: e for e in boot["elements"]}
    for key, g in (log.get("gws") or {}).items():
        if g.get("graded") or g["gw"] not in done:
            continue
        try:
            live = {x["id"]: x["stats"] for x in get(f"https://fantasy.premierleague.com/api/event/{g['gw']}/live/").get("elements", [])}
            fixtures = [f for f in get(f"https://fantasy.premierleague.com/api/fixtures/?event={g['gw']}") if f.get("finished") or f.get("finished_provisional")]
        except Exception:
            continue
        g["results"] = {c: [grade_pick(c, p, live, fixtures, boot_el) for p in g["picks"].get(c, [])] for c in CATS}
        g["graded"] = True
    return log


# ---------------------------------------------------------------- earlier method (before the Predictions box)
LEGACY_FILE = Path(__file__).resolve().parent / "legacy_predictions.json"


def grade_legacy(leg, boot, get):
    """Grade the stored DEFCON top-10 lists (name + club) of earlier gameweeks once FPL has settled them."""
    done = {e["id"] for e in boot["events"] if e.get("finished") and e.get("data_checked")}
    short = {t["id"]: t["short_name"] for t in boot["teams"]}
    by_key = {(e["web_name"], short[e["team"]]): e for e in boot["elements"]}
    boot_el = {e["id"]: e for e in boot["elements"]}
    for g in (leg.get("gws") or {}).values():
        if g.get("graded") or g["gw"] not in done:
            continue
        try:
            live = {x["id"]: x["stats"] for x in get(f"https://fantasy.premierleague.com/api/event/{g['gw']}/live/").get("elements", [])}
        except Exception:
            continue
        res = []
        for p in g["picks"]:
            el = by_key.get((p["name"], p["club"]))
            res.append(grade_pick("defcon", {"id": el["id"]}, live, [], boot_el) if el else {"hit": False, "why": "player not found"})
        g["results"] = {"defcon": res}
        g["graded"] = True
    return leg


def legacy_view(leg, volume_log):
    """Earlier-method scorecard: the old chance-volume goal / assist lists (volume_log, only players who played count) and the stored
    DEFCON top-10s."""
    ga = []
    for k in sorted((volume_log or {}), key=lambda x: int(x[2:])):
        e = volume_log[k] or {}
        if not e.get("graded"):
            continue
        row = {"gw": e["gw"], "rebuilt": bool(e.get("backfilled"))}
        for kind, name in (("goal", "goals"), ("assist", "assists")):
            pl = [f for f in e.get("flags", []) if f["kind"] == kind and f.get("played")]
            row[name] = [sum(1 for f in pl if (f.get("got") or 0) > 0), len(pl)]
        ga.append(row)
    dc = []
    for g in sorted((leg.get("gws") or {}).values(), key=lambda g: g["gw"]):
        if g.get("graded"):
            rs = g["results"]["defcon"]
            dc.append({"gw": g["gw"], "defcon": [sum(1 for r in rs if r["hit"]), len(rs)]})
    def tot(rows, k):
        return [sum(r[k][0] for r in rows), sum(r[k][1] for r in rows)] if rows else [0, 0]
    return {"goals_assists": ga, "defcon": dc, "total": {"goals": tot(ga, "goals"), "assists": tot(ga, "assists"), "defcon": tot(dc, "defcon")},
            "pending": [g["gw"] for g in (leg.get("gws") or {}).values() if not g.get("graded")]}


# ---------------------------------------------------------------- what the page shows
def view(log, boot_players=None):
    gws = sorted((log.get("gws") or {}).values(), key=lambda g: g["gw"])
    graded = [g for g in gws if g.get("graded")]
    cal = calibration(log)
    per_gw = []
    for g in graded:
        row = {"gw": g["gw"]}
        for c in CATS:
            rs = g["results"].get(c, [])
            row[c] = [sum(1 for r in rs if r["hit"]), len(rs)]
        per_gw.append(row)
    total = {c: [cal[c]["n"] and round(cal[c]["n"] * cal[c]["hit_rate"] / 100), cal[c]["n"]] for c in CATS}
    n_all = sum(t[1] for t in total.values()); h_all = sum(t[0] for t in total.values())
    why = {}
    for c in CATS:
        cnt = {}
        for g in graded:
            for r in g["results"].get(c, []):
                if not r["hit"]:
                    k = ("did not play or played under an hour" if ("did not play" in r["why"] or r["why"].startswith("only ")) else
                         "team did not score" if r["why"] == "team did not score" else
                         "played, team scored, he did not" if "team scored" in r["why"] else
                         "club conceded" if r["why"].startswith("conceded") else
                         "fell short of the threshold" if "contributions" in r["why"] else "other")
                    cnt[k] = cnt.get(k, 0) + 1
        why[c] = sorted(cnt.items(), key=lambda kv: -kv[1])
    last = None
    if graded:
        g = graded[-1]
        last = {"gw": g["gw"], "picks": {c: [{**p, **r} for p, r in zip(g["picks"].get(c, []), g["results"].get(c, []))] for c in CATS}}
    return {"graded": len(graded), "pending": [g["gw"] for g in gws if not g.get("graded")], "per_gw": per_gw, "total": total,
            "overall": [h_all, n_all], "calibration": cal, "why": why, "last": last}

"""Prediction log: what the Predictions box said for each gameweek (top 10 per category), frozen when the deadline passes,
graded against FPL's final numbers once the gameweek is settled, and turned into a hit rate, a calibration factor and a
plain-English "why it missed" count that feed back into the next predictions.

Categories: goals (scores at least one), assists (at least one), clean_sheets (the club concedes none), defcon (reaches the
defensive-contribution threshold). Stored in its own committed file (prediction_log.json / bacalhau-prediction_log.json).
Pure functions take their inputs; only grade() talks to FPL (through the `get` it is given)."""
from __future__ import annotations
import json, os
from datetime import datetime, timedelta
from pathlib import Path

CATS = ("goals", "assists", "gi", "clean_sheets", "defcon")
LABEL = {"goals": "Goals", "assists": "Assists", "gi": "Goal or assist", "clean_sheets": "Clean sheets", "defcon": "DEFCON"}
TARGET = "target"          # the Target tab's 1-GW top 10, saved beside the predictions and graded on goals / assists / either
DEFCON_THR = {2: 10, 3: 12, 4: 12}
GOAL_PTS = {1: 6, 2: 6, 3: 5, 4: 4}          # FPL points per goal by element_type
ASSIST_PTS = 3          # element_type -> defensive contributions needed for the +2
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
    except FileNotFoundError:
        return {}
    return d if isinstance(d, dict) else {}      # a corrupt file raises: section() records it instead of the history being reset


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
                if "raw" not in pick:
                    n -= 1
                    hits -= 1 if res.get("hit") else 0
                    continue
                sp += pick["raw"] / 100.0
        row = {"n": n, "hits": hits, "mean_p": round(100 * sp / n) if n else None, "hit_rate": round(100 * hits / n) if n else None, "scale": 1.0}
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
def atk_pts(st, el):
    """Attacking points a player made: goals x (6/6/5/4) + assists x 3."""
    return int(st.get("goals_scored") or 0) * GOAL_PTS.get((el or {}).get("element_type"), 4) + int(st.get("assists") or 0) * ASSIST_PTS


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
    if cat == "ap":
        pts = atk_pts(st, el)
        g, a = int(st.get("goals_scored") or 0), int(st.get("assists") or 0)
        return {"hit": pts > 0, "pts": pts, "exp": pick.get("ap"), "why": f"{g} goal{'s' if g != 1 else ''}, {a} assist{'s' if a != 1 else ''} = {pts} pts" if pts else ("did not play" if mins == 0 else f"{mins} min, no goal or assist")}
    if cat == "gi":
        g, a = int(st.get("goals_scored") or 0), int(st.get("assists") or 0)
        if g + a > 0:
            return {"hit": True, "pts": atk_pts(st, el), "why": f"{g} goal{'s' if g != 1 else ''}, {a} assist{'s' if a != 1 else ''}"}
        if mins == 0:
            return {"hit": False, "why": "did not play"}
        if mins < 60:
            return {"hit": False, "why": f"only {mins} minutes"}
        return {"hit": False, "pts": 0, "why": "team did not score" if scored == 0 else f"played {mins} min, team scored {scored}, no goal or assist"}
    if cat in ("goals", "assists"):
        n = int(st.get("goals_scored" if cat == "goals" else "assists") or 0)
        word = "goal" if cat == "goals" else "assist"
        if n > 0:
            return {"hit": True, "pts": atk_pts(st, el), "why": f"{n} {word}{'s' if n > 1 else ''}"}
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


def near_miss(cat, proc):
    """A pick that missed on the result but still got the chances: shots on target / a big chance for a goal, a big chance created
    or two chances created for an assist. proc = {shots, sot, big, cc, big_cc} for the gameweek."""
    if not proc:
        return False
    g = proc.get("sot", 0) >= 1 or proc.get("big", 0) >= 1
    a = proc.get("big_cc", 0) >= 1 or proc.get("cc", 0) >= 2
    return g if cat == "goals" else a if cat == "assists" else (g or a)


def proc_text(proc):
    bits = []
    if proc.get("shots"):
        bits.append(f"{proc['shots']} shot{'s' if proc['shots'] != 1 else ''} ({proc.get('sot', 0)} on target)")
    if proc.get("big"):
        bits.append(f"{proc['big']} big chance{'s' if proc['big'] != 1 else ''}")
    if proc.get("cc"):
        bits.append(f"{proc['cc']} chance{'s' if proc['cc'] != 1 else ''} created")
    if proc.get("big_cc"):
        bits.append(f"{proc['big_cc']} big chance{'s' if proc['big_cc'] != 1 else ''} created")
    return ", ".join(bits)


def add_process(cat, pick, res, process):
    """Attach the shots / chances he had (Understat) to a graded result; flag a miss that was a near miss."""
    proc = (process or {}).get(pick.get("id"))
    if proc is None or cat not in ("goals", "assists", "gi", "ap", TARGET):
        return res
    res["proc"] = proc
    if not res.get("hit") and near_miss(cat, proc):
        res["near"] = True
        res["why"] = f"{res.get('why', '')} · but {proc_text(proc)}".strip(" ·")
    return res


def grade(log, boot, get, process=None):
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
        proc = None
        if process and fixtures:
            try:
                ks = sorted(f["kickoff_time"] for f in fixtures if f.get("kickoff_time"))
                if ks:
                    t0 = datetime.fromisoformat(ks[0].replace("Z", "+00:00")) - timedelta(hours=2)
                    t1 = datetime.fromisoformat(ks[-1].replace("Z", "+00:00")) + timedelta(hours=1)
                    proc = process(t0.strftime("%Y-%m-%d %H:%M:%S"), t1.strftime("%Y-%m-%d %H:%M:%S"))
            except Exception:        # Understat is optional: grade on results alone
                proc = None
        g["results"] = {c: [add_process(c, p, grade_pick(c, p, live, fixtures, boot_el), proc) for p in g["picks"].get(c, [])] for c in CATS}
        g["results"][TARGET] = [add_process(TARGET, p, grade_target(p, live, boot_el), proc) for p in g["picks"].get(TARGET, [])]
        g["results"]["rotation"] = [{**grade_rotation(p, live), "kind": p.get("kind") or "unspecified"} for p in g["picks"].get("rotation", [])]
        g["results"]["ap"] = [add_process("ap", p, grade_pick("ap", p, live, fixtures, boot_el), proc) for p in g["picks"].get("ap", [])]
        g["graded"] = True
    return log


def grade_rotation(pick, live):
    """A predicted rotation came off when he did not start, or played under an hour."""
    st = live.get(pick.get("id")) or {}
    starts, m = int(st.get("starts") or 0), int(st.get("minutes") or 0)
    if starts == 0:
        return {"hit": True, "why": "benched" if m == 0 else f"started on the bench, came on for {m} min"}
    if m < 60:
        return {"hit": True, "why": f"started but off after {m} min"}
    return {"hit": False, "why": f"played {m} min" + (" (full game)" if m >= 85 else " (reduced minutes)")}


def grade_target(pick, live, boot_el=None):
    """A Target pick graded three ways: scored, assisted, either (plus the attacking points he made)."""
    st = live.get(pick.get("id")) or {}
    g, a, m = int(st.get("goals_scored") or 0), int(st.get("assists") or 0), int(st.get("minutes") or 0)
    return {"hit": g + a > 0, "goal": g > 0, "assist": a > 0, "min": m, "started": int(st.get("starts") or 0) > 0, "pts": atk_pts(st, (boot_el or {}).get(pick.get("id"))), "why": f"{g} goal{'s' if g != 1 else ''}, {a} assist{'s' if a != 1 else ''}" if g + a else ("did not play" if m == 0 else f"{m} min, no goal or assist")}


# ---------------------------------------------------------------- per-player snapshot (training data)
PLAYER_FILE = Path(__file__).resolve().parent / "player_log.json"
PLAYER_COLS = ["id", "team", "pos", "cost", "own", "form", "min", "xg90", "xa90", "fdr", "home", "mp", "avail", "xp", "p_goal", "p_assist", "p_gi", "p_cs", "p_dc", "t_rank", "t_score", "sh4", "sot4", "big4", "cc4", "bcc4", "p_start"]
OUTCOME_COLS = ["o_min", "o_goals", "o_assists", "o_dc", "o_pts", "o_start"]


def player_record(plog, gw, rows, now):
    """Save every relevant player's inputs and the model's chances for `gw` (refreshed until the deadline; never once graded)."""
    gws = plog.setdefault("gws", {})
    g = gws.get(str(gw))
    if g and g.get("graded"):
        return plog
    gws[str(gw)] = {"gw": gw, "made_at": now.isoformat(), "cols": PLAYER_COLS, "rows": rows, "graded": False}
    return plog


def player_grade(plog, boot, get):
    """Append what each saved player did (minutes, goals, assists, defensive contributions, points) once FPL has settled the gameweek."""
    done = {e["id"] for e in boot["events"] if e.get("finished") and e.get("data_checked")}
    for g in (plog.get("gws") or {}).values():
        if g.get("graded") or g["gw"] not in done:
            continue
        try:
            live = {x["id"]: x["stats"] for x in get(f"https://fantasy.premierleague.com/api/event/{g['gw']}/live/").get("elements", [])}
        except Exception:
            continue
        for r in g["rows"]:
            st = live.get(r[0]) or {}
            r.extend([int(st.get("minutes") or 0), int(st.get("goals_scored") or 0), int(st.get("assists") or 0), int(st.get("defensive_contribution") or 0), int(st.get("total_points") or 0), 1 if int(st.get("starts") or 0) > 0 else 0])
        g["cols"] = list(g.get("cols") or PLAYER_COLS) + OUTCOME_COLS
        g["graded"] = True
    return plog


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
    total = {c: [cal[c]["hits"], cal[c]["n"]] for c in CATS}
    n_all = sum(t[1] for t in total.values()); h_all = sum(t[0] for t in total.values())
    near = {}
    for c in list(CATS) + [TARGET]:
        miss = nr = 0
        for g in graded:
            for r in g["results"].get(c, []):
                if not r.get("hit") and "proc" in r:
                    miss += 1; nr += 1 if r.get("near") else 0
        near[c] = [nr, miss]
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
    tgt = {"n": 0, "goal": 0, "assist": 0, "gi": 0, "started": 0, "per_gw": []}
    cmp_ = {"goals": [0, 0], "assists": [0, 0], "gi": [0, 0]}
    for g in graded:
        ts = g["results"].get(TARGET, [])
        if not ts:
            continue
        tgt["n"] += len(ts); tgt["goal"] += sum(1 for r in ts if r["goal"]); tgt["assist"] += sum(1 for r in ts if r["assist"]); tgt["gi"] += sum(1 for r in ts if r["hit"]); tgt["started"] += sum(1 for r in ts if r.get("started"))
        tgt["per_gw"].append({"gw": g["gw"], "goal": sum(1 for r in ts if r["goal"]), "assist": sum(1 for r in ts if r["assist"]), "gi": sum(1 for r in ts if r["hit"]), "n": len(ts)})
        for c in ("goals", "assists", "gi"):       # the model's list for the same gameweeks, only where Target was saved too
            rs = g["results"].get(c, [])
            cmp_[c][0] += sum(1 for r in rs if r["hit"]); cmp_[c][1] += len(rs)
    # mean attacking points per pick, for each list over the same gameweeks (where Target was saved too)
    pts = {}
    for key in ("ap", "gi", "goals", "assists", TARGET):
        n_ = s_ = 0
        for g in graded:
            if not g["results"].get(TARGET):
                continue
            for r in g["results"].get(key, []):
                if "pts" in r:
                    n_ += 1; s_ += r["pts"]
        pts[key] = [round(s_ / n_, 2) if n_ else None, n_]
    exp_ap = [pk.get("ap") for g in graded if g["results"].get(TARGET) for pk in g["picks"].get("ap", []) if pk.get("ap") is not None]
    pts["ap_expected"] = round(sum(exp_ap) / len(exp_ap), 2) if exp_ap else None
    rot, rot_kinds = [0, 0], {}
    for g in graded:
        rs = g["results"].get("rotation", [])
        rot[0] += sum(1 for r in rs if r["hit"]); rot[1] += len(rs)
        for r in rs:
            k = rot_kinds.setdefault(r.get("kind") or "unspecified", [0, 0])
            k[0] += 1 if r["hit"] else 0; k[1] += 1
    last = None
    if graded:
        g = graded[-1]
        last = {"gw": g["gw"], "picks": {c: [{**p, **r} for p, r in zip(g["picks"].get(c, []), g["results"].get(c, []))] for c in CATS}}
    return {"graded": len(graded), "pending": [g["gw"] for g in gws if not g.get("graded")], "per_gw": per_gw, "total": total,
            "overall": [h_all, n_all], "calibration": cal, "near": near, "why": why, "last": last, "target": tgt, "model_same_weeks": cmp_, "rotation": rot, "rotation_kinds": rot_kinds, "points": pts}

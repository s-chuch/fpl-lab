"""Signals: xG/xA chance volume and its track record, form/FDR, DEFCON, rotation and congestion, value, injuries, price radar."""
from __future__ import annotations
import json, re
from datetime import datetime, timedelta, timezone
from fplbase import *
from fplbase import _warn, _fixtures_for

def scouting_ok(el, finished_gws):
    """Is a player a sensible scouting suggestion? A real sample (at least 270 minutes and 45% of the minutes available so far),
    fit (FPL status available, chance of playing 75%+ when given), so injured or barely-playing players do not top a list."""
    mins = int(el.get("minutes") or 0)
    if mins < max(270, 0.45 * 90 * finished_gws):
        return False
    if el.get("status") not in (None, "a"):
        return False
    ch = el.get("chance_of_playing_next_round")
    return ch is None or ch >= 75


def build_xg_signal(boot, team_id, picks_gw, min_minutes=180, threshold=2.0, top_n=10, exclude=None, next_fixture_map=None):
    """Flag your own squad's players as over/underperforming their underlying
    numbers — a concrete "due for a dry patch" (sell-high) or "still getting
    the chances, patience/buy-low" signal, using FPL's own expected-goals
    data (already in bootstrap-static, no new scraping needed) instead of a
    gut read on "good form". Defenders/keepers also get a goals-conceded vs
    expected-goals-conceded check, since clean-sheet luck is the bigger swing
    for that position than attacking returns.

    Also returns three league-wide top_n leaderboards (regardless of
    ownership): `top` ranked by xGI per 90 (raw underlying attacking
    output, a scouting list), and `top_over`/`top_under` — the same
    over/underperforming regression signal as the squad view, applied
    league-wide, so "who's about to regress" and "who's still due a
    return" aren't only visible for players you already own."""
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}

    def to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def row_of(el):
        mins = int(el.get("minutes") or 0)
        if mins < min_minutes:
            return None  # too small a sample for xG/xA to mean anything
        pos = POS[el["element_type"]]
        goals, assists = int(el.get("goals_scored") or 0), int(el.get("assists") or 0)
        xg, xa = to_float(el.get("expected_goals")) or 0.0, to_float(el.get("expected_assists")) or 0.0
        xgi = to_float(el.get("expected_goal_involvements"))
        if xgi is None:
            xgi = xg + xa
        gi = goals + assists
        diff = round(gi - xgi, 2)
        tag = "overperforming" if diff >= threshold else ("underperforming" if diff <= -threshold else "on_track")
        p90 = mins / 90
        row = {
            "name": el["web_name"], "pos": pos, "club": teams[el["team"]]["short_name"], "minutes": mins,
            "gi_p90": round(gi / p90, 2) if p90 else 0.0,
            "cost": el["now_cost"] / 10, "owned_pct": to_float(el.get("selected_by_percent")) or 0.0,
            "goals": goals, "assists": assists, "xg": round(xg, 2), "xa": round(xa, 2),
            "xgi": round(xgi, 2), "xgi_p90": round(xgi / p90, 2) if p90 else 0.0, "gi": gi, "diff": diff, "tag": tag,
        }
        fx = (next_fixture_map or {}).get(el["team"])
        row["next"] = f"{fx['opp']} ({fx['side']})" if fx else "Blank"
        row["fdr"] = fx.get("fdr") if fx else None
        if pos in ("DEF", "GKP"):
            xgc = to_float(el.get("expected_goals_conceded"))
            if xgc is not None:
                gc = int(el.get("goals_conceded") or 0)
                gc_diff = round(xgc - gc, 2)  # positive = conceding FEWER than expected (riding luck)
                row.update({"goals_conceded": gc, "xgc": round(xgc, 2), "gc_diff": gc_diff,
                            "gc_tag": "riding_luck" if gc_diff >= threshold else ("unlucky" if gc_diff <= -threshold else "on_track")})
        return row

    finished_gws = sum(1 for e in boot["events"] if e.get("finished"))
    all_rows, scout_ok = [], set()
    for el in elements.values():
        r = row_of(el)
        if r:
            all_rows.append(r)
            if scouting_ok(el, finished_gws):
                scout_ok.add((r["name"], r["club"]))
    # The league-wide leaderboards are scouting lists: only players you don't already own
    # (`exclude` = your squad as (name, club) pairs). Your own players stay in `rows` below.
    pool = [r for r in all_rows if (r["name"], r["club"]) not in (exclude or ()) and (r["name"], r["club"]) in scout_ok]
    top = sorted((r for r in pool if r["pos"] != "GKP"), key=lambda r: -r["xgi_p90"])[:top_n]
    # Defenders and keepers score few goals, so a goals+assists gap says little about them: the attacking lists are MID/FWD only and
    # their luck is read from goals conceded vs xGC instead (top_def_lucky).
    att = [r for r in pool if r["pos"] in ("MID", "FWD")]
    top_over = sorted((r for r in att if r["tag"] == "overperforming"), key=lambda r: -r["diff"])[:top_n]
    top_under = sorted((r for r in att if r["tag"] == "underperforming"), key=lambda r: r["diff"])[:top_n]
    top_def_lucky = sorted((r for r in pool if r["pos"] in ("DEF", "GKP") and r.get("gc_tag") == "riding_luck"), key=lambda r: -r.get("gc_diff", 0))[:top_n]

    rows = []
    if picks_gw:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
            for p in pk.get("picks") or []:
                el = elements.get(p["element"])
                r = row_of(el) if el else None
                if r:
                    rows.append(r)
        except Exception as e:
            _warn(f"build_xg_signal: could not load GW{picks_gw} squad: {e}")
    rows.sort(key=lambda r: -abs(r["diff"]))
    notable = [r for r in rows if r["tag"] != "on_track" or r.get("gc_tag") not in (None, "on_track")]
    imminent = _imminent_returns(boot, all_rows, rows, pool, top_n, next_fixture_map)
    return {
        "threshold": threshold, "min_minutes": min_minutes, "top_n": top_n,
        "rows": rows, "notable": notable, "top": top, "top_over": top_over, "top_under": top_under, "top_def_lucky": top_def_lucky,
        "finished_gws": finished_gws,
        "imminent": imminent,
    }

IMMINENT_WINDOW = 4        # last N gameweeks the player actually played in

IMMINENT_XG = 1.0          # xG over the window with no goal => goal "due"

IMMINENT_XA = 0.7          # xA over the window with no assist => assist "due"

def _imminent_returns(boot, all_rows, squad_rows, pool, top_n, next_fixture_map=None):
    """Understat shot data when reachable (real shots on target / big chances), else FPL's own xG/xA."""
    try:
        import understat
        res = _imminent_understat(boot, squad_rows, top_n, understat, next_fixture_map)
        if res:
            return res
    except Exception as e:
        _warn(f"imminent: Understat unavailable, falling back to FPL xG/xA: {e}")
    return _imminent_fpl(boot, all_rows, squad_rows, pool, top_n)

UNDERSTAT_GOAL_SOT = 3      # shots on target over the window with no goal => goal due

UNDERSTAT_GOAL_BIG = 2      # ...or this many big chances (shots worth 0.3+ xG)

UNDERSTAT_ASSIST_CC = 6     # chances created (shots the player set up) with no assist => assist due

UNDERSTAT_ASSIST_BIG = 3    # ...or this many big chances created

ASSIST_DEF_FACTOR = 2       # a defender must clear the assist bar at 2x (12+ chances created or 6+ big)

STARTER_SHARE = 0.55        # season minutes / (90 * finished gameweeks) a player needs to be flagged

def starter_share(el, boot):
    """Share of the available minutes this season (None before any gameweek has finished)."""
    fin = sum(1 for e in boot["events"] if e.get("finished"))
    if not fin:
        return None
    return int(el.get("minutes") or 0) / (90 * fin)

def _imminent_understat(boot, squad_rows, top_n, understat, next_fixture_map=None, windows=None, extra_owned=None):
    """Goal due: the player's last few appearances show real shot volume (shots on target /
    big chances) but no goal. Assist due: chances created (shots they set up, big ones counted
    separately) but no assist. Counts are from Understat's per-shot records (understat.py)."""
    windows = windows if windows is not None else understat.player_windows(2026)
    matched, unmatched = understat.match_to_fpl(windows, boot)
    if len(matched) < 100:
        _warn(f"imminent: only {len(matched)} Understat players matched to FPL; not using it")
        return None
    if unmatched:
        print(f"[understat.py] unmatched: {', '.join(unmatched[:12])}")
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    els = {e["id"]: e for e in boot["elements"]}
    owned = {(r["name"], r["club"]) for r in squad_rows} | set(extra_owned or ())
    goal, assist, due_by = [], [], {}
    for eid, w in matched.items():
        el = els[eid]
        if el["element_type"] == 1 or w["apps"] < 2:
            continue
        share = starter_share(el, boot)
        if share is not None and share < STARTER_SHARE:
            continue    # rotation / bench player: chance volume over a few cameos is noise
        key = (el["web_name"], teams[el["team"]])
        item = {"name": el["web_name"], "pos": POS[el["element_type"]], "club": key[1], "cost": el["now_cost"] / 10,
                "owned_pct": float(el.get("selected_by_percent") or 0), "gws": w["apps"], "shots": w["shots"],
                "sot": w["sot"], "big": w["big"], "goals": w["goals"], "xg": w["xg"],
                "cc": w["cc"], "big_cc": w["big_cc"], "assists": w["assists"], "xa": w["xa"], "eid": eid}
        fx = next_fixture_map.get(el["team"]) if next_fixture_map else None
        item["next"] = f"{fx['opp']} ({fx['side']})" if fx else "Blank"
        item["fdr"] = fx["fdr"] if fx else None
        # Easy next fixture and a low-owned differential rank higher; a blank GW drops a player
        # down, since no fixture means no chance of a return.
        bonus = (3 - fx["fdr"] if fx and fx.get("fdr") else -2) + (1 if item["owned_pct"] < 10 else 0)
        item["bonus"] = bonus
        due = []
        mult = ASSIST_DEF_FACTOR if el["element_type"] == 2 else 1
        if el["element_type"] != 2 and w["goals"] == 0 and (w["sot"] >= UNDERSTAT_GOAL_SOT or w["big"] >= UNDERSTAT_GOAL_BIG):
            due.append("goal"); goal.append(item)
        if w["assists"] == 0 and (w["cc"] >= UNDERSTAT_ASSIST_CC * mult or w["big_cc"] >= UNDERSTAT_ASSIST_BIG * mult):
            due.append("assist"); assist.append(item)
        due_by[key] = due
    for r in squad_rows:
        r["due"] = due_by.get((r["name"], r["club"]), [])
    goal.sort(key=lambda x: -(x["sot"] + 2 * x["big"] + x["xg"] + x["bonus"]))
    assist.sort(key=lambda x: -(x["cc"] + 2 * x["big_cc"] + x["xa"] + x["bonus"]))
    return {"source": "understat", "window": understat.WINDOW, "goal_rule": f"{UNDERSTAT_GOAL_SOT}+ shots on target or {UNDERSTAT_GOAL_BIG}+ big chances",
            "assist_rule": f"{UNDERSTAT_ASSIST_CC}+ chances created or {UNDERSTAT_ASSIST_BIG}+ big chances created (defenders: double)",
            "starter_rule": f"regular starters only ({round(STARTER_SHARE * 100)}%+ of available minutes); goal list is midfielders and forwards",
            "goal": [x for x in goal if (x["name"], x["club"]) not in owned][:top_n],
            "assist": [x for x in assist if (x["name"], x["club"]) not in owned][:top_n]}

def _imminent_fpl(boot, all_rows, squad_rows, pool, top_n):
    """Players whose RECENT underlying numbers say a goal / assist is overdue: plenty of
    expected goals (xG, from the shots and chances FPL's data feed records) or expected
    assists (xA, chances created) across their last few appearances, but no actual goal /
    assist in that window. FPL's public API has no shots-on-target or big-chances-created
    counts, so xG / xA per gameweek (element-summary) is the closest available stand-in:
    xG is built from the quality of every shot, xA from the quality of every chance created."""
    from concurrent.futures import ThreadPoolExecutor
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    by_key = {}
    for e in boot["elements"]:
        by_key[(e["web_name"], teams[e["team"]])] = e["id"]
    wanted = {}
    for r in sorted(pool, key=lambda r: -r["xg"] / max(r["minutes"] / 90, 1))[:40] + sorted(pool, key=lambda r: -r["xa"] / max(r["minutes"] / 90, 1))[:40] + list(squad_rows):
        eid = by_key.get((r["name"], r["club"]))
        if eid:
            wanted[eid] = r
    def window(eid):
        try:
            hist = get(f"https://fantasy.premierleague.com/api/element-summary/{eid}/").get("history", [])
        except Exception as e:
            _warn(f"imminent: could not load element {eid}: {e}")
            return eid, None
        played = [h for h in hist if int(h.get("minutes") or 0) > 0][-IMMINENT_WINDOW:]
        if len(played) < 2:
            return eid, None
        f = lambda k: sum(float(h.get(k) or 0) for h in played)
        return eid, {"gws": len(played), "mins": sum(int(h["minutes"]) for h in played),
                     "xg": round(f("expected_goals"), 2), "xa": round(f("expected_assists"), 2),
                     "goals": int(f("goals_scored")), "assists": int(f("assists"))}
    with ThreadPoolExecutor(max_workers=8) as ex:
        wins = dict(ex.map(window, list(wanted)))
    goal, assist, squad_due = [], [], {}
    for eid, r in wanted.items():
        w = wins.get(eid)
        if not w:
            continue
        item = {"name": r["name"], "pos": r["pos"], "club": r["club"], "cost": r["cost"], "owned_pct": r["owned_pct"], **w}
        due = []
        if w["xg"] >= IMMINENT_XG and w["goals"] == 0 and r["pos"] != "GKP":
            due.append("goal"); goal.append(item)
        if w["xa"] >= IMMINENT_XA and w["assists"] == 0 and r["pos"] != "GKP":
            due.append("assist"); assist.append(item)
        squad_due[(r["name"], r["club"])] = due
    owned_keys = {(r["name"], r["club"]) for r in squad_rows}
    for r in squad_rows:
        r["due"] = squad_due.get((r["name"], r["club"]), [])
    goal.sort(key=lambda x: -x["xg"]); assist.sort(key=lambda x: -x["xa"])
    return {"source": "fpl", "window": IMMINENT_WINDOW, "min_xg": IMMINENT_XG, "min_xa": IMMINENT_XA,
            "goal": [x for x in goal if (x["name"], x["club"]) not in owned_keys][:top_n],
            "assist": [x for x in assist if (x["name"], x["club"]) not in owned_keys][:top_n]}

def backfill_volume_log(log, boot, team_id, top_n=10, first_gw=3):
    """Rebuild the lists as they would have looked before each past gameweek (using only the
    matches played before its deadline, that week's fixtures and the squad you held then) so the
    track record has history. Entries are marked backfilled; grading happens in update_volume_log.
    Ownership % is today's (FPL does not keep history), which only affects the small
    differential bonus in the ranking."""
    import understat
    log = dict(log or {})
    finished = sorted(e["id"] for e in boot["events"] if e.get("finished"))
    todo = [g for g in finished if g >= first_gw and f"gw{g}" not in log]
    if not todo:
        return log
    try:
        fetched = understat.fetch_matches(2026)
    except Exception as e:
        _warn(f"volume_log backfill: Understat unavailable: {e}")
        return log
    teams = {t["id"]: t for t in boot["teams"]}
    els = {e["id"]: e for e in boot["elements"]}
    for g in todo:
        ev = next(e for e in boot["events"] if e["id"] == g)
        cutoff = (ev.get("deadline_time") or "").replace("T", " ").replace("Z", "")
        if not cutoff:
            continue
        try:
            fx = fixture_map(g, teams)
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{g}/picks/")
            owned = {(els[p["element"]]["web_name"], teams[els[p["element"]]["team"]]["short_name"]) for p in pk.get("picks", []) if p["element"] in els}
            res = _imminent_understat(boot, [], top_n, understat, fx, windows=understat.player_windows(2026, before=cutoff, fetched=fetched), extra_owned=owned)
        except Exception as e:
            _warn(f"volume_log backfill GW{g}: {e}")
            continue
        if not res:
            continue
        flags = [{"eid": x["eid"], "name": x["name"], "club": x["club"], "pos": x["pos"], "kind": kind}
                 for kind in ("goal", "assist") for x in res.get(kind, [])]
        log[f"gw{g}"] = {"gw": g, "flags": flags, "graded": False, "backfilled": True}
    return log

def update_volume_log(log, imminent, ds, boot):
    """Track record for the xG/xA "high chance volume" lists. While a gameweek is still open,
    its flags (the players shown in the lists) are recorded and refreshed each run; once its
    deadline passes the entry freezes, and when the gameweek finishes it is graded against FPL's
    live goals/assists (did the flagged player score / assist, and did they play at all), along
    with the league-wide rate for context. Builds a real hit rate over the season."""
    log = dict(log or {})
    gw = ds.get("next_gw")
    els = {e["id"]: e for e in boot["elements"]}
    if imminent and imminent.get("source") == "understat" and gw:
        flags = [{"eid": x["eid"], "name": x["name"], "club": x["club"], "pos": x.get("pos") or POS.get((els.get(x["eid"]) or {}).get("element_type")), "kind": kind}
                 for kind in ("goal", "assist") for x in imminent.get(kind, [])]
        log[f"gw{gw}"] = {"gw": gw, "flags": flags, "graded": False}
    # grade only once FPL has settled the gameweek (finished AND data_checked)
    finished = {e["id"] for e in boot["events"] if e.get("finished") and e.get("data_checked")}
    for entry in log.values():     # backfill the position onto older flags
        for f in entry.get("flags", []):
            if not f.get("pos") and f.get("eid") in els:
                f["pos"] = POS[els[f["eid"]]["element_type"]]
    for key, entry in log.items():
        if entry["gw"] not in finished or (entry.get("graded") and entry.get("baseline_att")):
            continue
        try:
            live = {el["id"]: el["stats"] for el in get(f"https://fantasy.premierleague.com/api/event/{entry['gw']}/live/").get("elements", [])}
        except Exception as e:
            _warn(f"volume_log: could not grade GW{entry['gw']}: {e}")
            continue
        for f in entry["flags"]:
            st = live.get(f["eid"]) or {}
            f["played"] = int(st.get("minutes") or 0) > 0
            f["got"] = int(st.get("goals_scored" if f["kind"] == "goal" else "assists") or 0)
        def rate(group):
            n = len(group) or 1
            return {"players": len(group),
                    "goal": round(sum(1 for st in group if int(st.get("goals_scored") or 0) > 0) / n, 3),
                    "assist": round(sum(1 for st in group if int(st.get("assists") or 0) > 0) / n, 3)}
        outfield = [st for eid, st in live.items() if els.get(eid, {}).get("element_type") != 1 and int(st.get("minutes") or 0) > 0]
        # The flagged players are attacking starters, so the fair yardstick is other attacking starters (not
        # every outfield sub and defender): midfielders/forwards who played 60+ minutes.
        attackers = [st for eid, st in live.items() if els.get(eid, {}).get("element_type") in (3, 4) and int(st.get("minutes") or 0) >= 60]
        entry["baseline"] = rate(outfield)
        entry["baseline_att"] = rate(attackers)
        if entry.get("news"):
            pts = [(live.get(n["id"]) or {}) for n in entry["news"]]
            played = [p for p in pts if p.get("minutes")]
            allp = [st for st in live.values() if st.get("minutes")]
            entry["news_points"] = {"avg": round(sum(p.get("total_points") or 0 for p in played) / len(played), 2) if played else None,
                                    "n": len(played), "field_avg": round(sum(st.get("total_points") or 0 for st in allp) / max(1, len(allp)), 2)}
        entry["graded"] = True
    return log

def update_pred_log(log, ds, boot, plan, ai):
    """Prediction log: what the program said it would do each gameweek, graded once the gameweek is over, so
    its forward calls can be scored instead of trusted. Per gameweek: the Plan tab's captain and the AI team's
    captain, each with the points that player actually scored. Entries freeze at the deadline."""
    log = dict(log or {})
    gw = ds.get("next_gw")
    names = {e["id"]: e["web_name"] for e in boot["elements"]}
    teams_short = {t["id"]: t["short_name"] for t in boot["teams"]}
    ids = {}
    for e in boot["elements"]:
        ids.setdefault(e["web_name"], []).append(e["id"])
    if gw:     # next_gw is by definition a gameweek whose deadline has not passed
        entry = {"gw": gw, "graded": False}
        xi = ((plan or {}).get("xis") or {}).get(f"gw{gw}", {}).get("xi") or []
        cap = next((bare(x) for x in xi if x.endswith(" (C)")), None)
        if cap:
            entry["plan_captain"] = cap
        ap = (ai or {}).get("plan") or {}
        if ap.get("gw") == gw and ap.get("captain"):
            entry["ai_captain"] = names.get(ap["captain"])
            entry["ai_captain_id"] = ap["captain"]
            entry["ai_locked"] = bool(ap.get("locked"))
        # the players the news themes agreed on at the time (3+ sites), to be scored against what they scored
        try:
            themes = fpl_common.load_js_object(ROOT / "news.js")
            by_key = {(e["web_name"], teams_short[e["team"]]): e["id"] for e in boot["elements"]}
            entry["news"] = [{"id": it.get("id") or by_key.get((it.get("player"), it.get("club"))), "name": it.get("player"), "club": it.get("club")}
                             for it in (themes.get("agreed") or [])]
            entry["news"] = [n for n in entry["news"] if n["id"] is not None]
        except Exception as e:
            _warn(f"pred_log: could not record news themes: {e}")
        log[f"gw{gw}"] = entry
    finished = {e["id"] for e in boot["events"] if e.get("finished") and e.get("data_checked")}
    for key, entry in log.items():
        if entry.get("graded") or entry["gw"] not in finished:
            continue
        try:
            live = {el["id"]: el["stats"] for el in get(f"https://fantasy.premierleague.com/api/event/{entry['gw']}/live/").get("elements", [])}
        except Exception as e:
            _warn(f"pred_log: could not grade GW{entry['gw']}: {e}")
            continue
        best = max((st.get("total_points") or 0 for st in live.values()), default=0)
        entry["best_player_points"] = best
        if entry.get("ai_captain_id") is not None:
            entry["ai_captain_points"] = (live.get(entry["ai_captain_id"]) or {}).get("total_points")
        cands = [i for i in ids.get(entry.get("plan_captain"), []) if (live.get(i) or {}).get("minutes")]
        if entry.get("plan_captain") and cands:
            entry["plan_captain_points"] = (live.get(cands[0]) or {}).get("total_points")
        entry["graded"] = True
    return log

def build_form_fdr(boot, next_fixture_map, min_minutes=90, top_n=10, exclude=None):
    """Every qualifying player's recent form (FPL's own rolling average
    points over their last 30 days) against how hard their very next
    fixture is — one number that separates "in form AND an easy game" from
    "in form but walking into a tough one", instead of reading the two
    signals apart. League-wide (like build_value_board), not squad-scoped,
    so it doubles as a scouting list rather than just auditing your own 15.
    Blank-gameweek players (no next_fixture_map entry) get no ratio, since
    dividing by a missing fixture isn't meaningful."""
    teams = {t["id"]: t for t in boot["teams"]}
    rows = []
    for el in boot["elements"]:
        mins = int(el.get("minutes") or 0)
        if mins < min_minutes:
            continue  # too little game time for "form" to mean anything yet
        if (el["web_name"], teams[el["team"]]["short_name"]) in (exclude or ()):
            continue  # already yours: this is a scouting list
        try:
            form = float(el.get("form") or 0)
        except (TypeError, ValueError):
            form = 0.0
        info = next_fixture_map.get(el["team"]) if next_fixture_map else None
        fdr = info["fdr"] if info else None
        fixture = f"{info['opp']} ({info['side']})" if info else "Blank"
        ratio = round(form / fdr, 2) if fdr else None
        rows.append({
            "name": el["web_name"], "pos": POS[el["element_type"]], "club": teams[el["team"]]["short_name"],
            "cost": el["now_cost"] / 10, "owned_pct": float(el.get("selected_by_percent") or 0),
            "form": form, "fdr": fdr, "fixture": fixture, "ratio": ratio,
        })
    rows.sort(key=lambda r: (r["ratio"] is None, -(r["ratio"] or 0)))
    by_pos = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for r in rows:
        if len(by_pos[r["pos"]]) < top_n:
            by_pos[r["pos"]].append(r)
    return {"min_minutes": min_minutes, "top_n": top_n, "by_pos": by_pos}

DEFCON_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12}

def build_defcon(boot, team_id, picks_gw, min_minutes=180, top_n=10, exclude=None):
    """FPL's 2025-26+ Defensive Contribution rule awards 2 pts in any match
    where a player's combined defensive actions clear a position threshold:
    10 (clearances+blocks+interceptions+tackles) for defenders, 12 (the same
    four plus ball recoveries) for midfielders/forwards. bootstrap-static's
    own defensive_contribution_per_90 field is already computed with the
    correct position-specific combination (confirmed against FPL's own field
    docs), so this reuses it directly instead of re-deriving it from the raw
    per-stat counts and risking a wrong recombination. Goalkeepers don't have
    a defensive contribution rule and are skipped.

    Returns both your squad's own rows (`rows`) and a league-wide top_n
    leaderboard (`top`, regardless of ownership) — the squad view audits your
    own 15, the leaderboard is who's actually hitting it hardest league-wide."""
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}

    def to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def row_of(el):
        pos = POS[el["element_type"]]
        if pos not in DEFCON_THRESHOLD:
            return None
        mins = int(el.get("minutes") or 0)
        per90 = to_float(el.get("defensive_contribution_per_90"))
        if mins < min_minutes or per90 is None:
            return None
        threshold = DEFCON_THRESHOLD[pos]
        margin = round(per90 - threshold, 2)
        tag = "reliable" if per90 >= threshold else ("borderline" if per90 >= threshold * 0.75 else "unlikely")
        return {
            "name": el["web_name"], "pos": pos, "club": teams[el["team"]]["short_name"], "minutes": mins,
            "cost": el["now_cost"] / 10, "owned_pct": to_float(el.get("selected_by_percent")) or 0.0,
            "threshold": threshold, "per90": round(per90, 2), "season_total": to_float(el.get("defensive_contribution")),
            "margin": margin, "tag": tag,
        }

    top = []
    for el in elements.values():
        r = row_of(el)
        if r:
            top.append(r)
    top = [r for r in top if (r["name"], r["club"]) not in (exclude or ())]  # leaderboard = players you don't own
    top.sort(key=lambda r: -r["margin"])
    top = top[:top_n]

    rows = []
    if picks_gw:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
            for p in pk.get("picks") or []:
                el = elements.get(p["element"])
                r = row_of(el) if el else None
                if r:
                    rows.append(r)
        except Exception as e:
            _warn(f"build_defcon: could not load GW{picks_gw} squad: {e}")
    rows.sort(key=lambda r: -r["margin"])
    return {"min_minutes": min_minutes, "top_n": top_n, "rows": rows, "top": top}

# FPL's own bootstrap-static/live feeds are Premier League only — no fixture
# calendar for the Champions League, Europa/Conference League, or domestic
# cups. Rather than fabricate one, a "rested" call is upgraded to "rotation"
# only when it's actually backed by text this app already scrapes: FPL's own
# editorial "news" blurb, or the shared "rotation risk" qualifier tag (see
# fpl_common.QUALIFIER_PATTERNS) already applied to news/X coverage.
OTHER_COMP_RE = re.compile(
    r"champions league|europa (?:league|conference)|conference league|uefa|carabao cup|efl cup|fa cup|"
    r"rotat(?:e|ed|ion)|midweek (?:trip|clash|tie|game|fixture)|squad rotation|managed minutes",
    re.I,
)

def _load_theme_file(root, filename, max_age_days=3):
    """news.js themes, or None when the file is stale. The X feed was discontinued (last
    generated 21 Sep) but its old themes were still feeding rotation flags and Plan intel, so a theme
    file only counts while it is at most `max_age_days` old."""
    data = fpl_common.load_js_object(root / filename)
    stamp = (data.get("generated_at") or "").replace(" UTC", "")
    try:
        age = datetime.now(timezone.utc) - datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return data if filename == "news.js" else None
    return data if age <= timedelta(days=max_age_days) else None

def _rotation_flagged_players(root):
    """Players already reported (news.js themes) as rotated for
    another competition — {web_name: explanatory text}. Both files carry the
    same {agreed, split} shape from fpl_common.build_themes, each item tagged
    via the shared qualifiers_near/QUALIFIER_PATTERNS used everywhere else in
    this app for "what is this text actually saying about this player"."""
    flagged = {}
    for filename in ("news.js",):
        data = _load_theme_file(root, filename)
        if data is None:
            continue
        for item in (data.get("agreed") or []) + (data.get("split") or []):
            if item.get("player") and "rotation risk" in (item.get("tags") or []):
                flagged.setdefault(item["player"], item.get("text"))
    return flagged

CONGESTION_DAYS = 3  # rest before the next match at or under this = fatigue risk (a Sat->Tue turnaround is 3)

SQUEEZE_DAYS = 3     # next match followed by another within this many days = rotation risk in the first

COMPETITION_ABBREV = {
    "premier league": "PL", "uefa champions league": "CL", "champions league": "CL",
    "uefa europa league": "EL", "europa league": "EL",
    "uefa europa conference league": "UECL", "europa conference league": "UECL", "conference league": "UECL",
    "fa cup": "FA Cup", "efl cup": "EFL Cup", "carabao cup": "EFL Cup", "league cup": "EFL Cup",
}

def _comp_abbrev(name):
    return COMPETITION_ABBREV.get((name or "").strip().lower(), name or "?")

def build_rotation_risk(boot, team_id, picks_gw, team_recovery=None, lookback=3, start_mins=60, target_gw=None):
    """Minutes trend over the last few finished GWs for each squad player —
    catches a player sliding out of the XI while it's still happening,
    instead of only after the fact via a bench-audit miss the week it costs
    you points. Uses real-world minutes from each GW's live feed,
    independent of who owned the player in FPL that week.

    Cross-referenced against FPL's own injury/suspension status
    (player_availability) so a falling/declining trend is labelled either
    "injury" (status explains the drop), "rotation" (fit per FPL, but a
    Champions League/Europa/domestic-cup tie or general rotation is already
    reported in FPL's own news blurb or scraped news/X coverage), or plain
    "rested" (fit, dropped, and no other-competition explanation found
    anywhere — still worth watching) — and a player who's still nailed on by
    minutes but freshly flagged gets caught too.

    `team_recovery` (fixtures_external.build_team_recovery's per-club output,
    keyed by short_name) adds a fourth, real-data reason: "congestion" — the
    player's club has <=2 days' rest before its next match across ANY
    competition, not just Premier League. Unlike "rotation" (a prose-keyword
    guess against scraped text), this is a fact from actual fixture dates —
    kept as a distinct reason value so the UI can tell them apart. It only
    fills in when nothing else already explains the row (injury/rotation/
    rested take priority — they're either more specific or already confirmed
    by another signal)."""
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}
    if not picks_gw:
        return None
    finished = sorted(e["id"] for e in boot.get("events") or [] if e.get("finished"))
    recent_gws = finished[-lookback:]
    if len(recent_gws) < 2:
        return None  # too early in the season for a trend to mean anything
    try:
        pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
    except Exception as e:
        _warn(f"build_rotation_risk: could not load GW{picks_gw} squad: {e}")
        return None

    minutes_by_gw = {}
    for gw in recent_gws:
        try:
            minutes_by_gw[gw] = {el["id"]: int(el["stats"].get("minutes") or 0) for el in get(f"https://fantasy.premierleague.com/api/event/{gw}/live/").get("elements", [])}
        except Exception as e:
            _warn(f"build_rotation_risk: could not load GW{gw} live data: {e}")
    recent_gws = [g for g in recent_gws if g in minutes_by_gw]  # failed fetch != 0 minutes
    if len(recent_gws) < 2:
        return None

    rotation_flagged = _rotation_flagged_players(ROOT)

    rows = []
    for p in pk.get("picks") or []:
        el = elements.get(p["element"])
        if not el:
            continue
        mins = [minutes_by_gw[gw].get(el["id"], 0) for gw in recent_gws]
        first, last = mins[0], mins[-1]
        earlier_avg = sum(mins[:-1]) / len(mins[:-1])
        if last < start_mins and earlier_avg >= start_mins:
            tag, note = "falling", "was starting, now fringe/bench minutes"
        elif last >= start_mins and first < start_mins:
            tag, note = "rising", "breaking into the side"
        elif all(m >= start_mins for m in mins):
            tag = "declining" if (first - last) >= 20 and mins == sorted(mins, reverse=True) else "starter"
            note = "starts getting shorter each week" if tag == "declining" else "nailed on across the window"
        elif all(m < 20 for m in mins):
            tag, note = "fringe", "fringe involvement across the window"
        else:
            tag, note = "mixed", "minutes bouncing around, no clear trend"
        avail = player_availability(el)
        rotation_note = None
        if OTHER_COMP_RE.search(avail["news"] or ""):
            rotation_note = avail["news"]
        elif el["web_name"] in rotation_flagged:
            rotation_note = rotation_flagged[el["web_name"]]
        reason = None
        if tag in ("falling", "declining"):
            if avail["kind"] in ("out", "doubt"):
                reason = "injury"
            elif rotation_note:
                reason = "rotation"
            else:
                reason = "rested"
        elif avail["kind"] in ("out", "doubt"):
            reason = "injury"  # still nailed by recent minutes, but freshly flagged

        club = teams[el["team"]]["short_name"]
        recovery = (team_recovery or {}).get(club)
        rest_days = recovery.get("rest_days") if recovery else None

        def match_label(m):
            if not m:
                return None
            comp = _comp_abbrev(m.get("competition"))
            try:
                days_until = (datetime.strptime(m["date"], "%Y-%m-%d").date() - datetime.now(ET).date()).days
            except Exception:
                days_until = None
            when = f" in {days_until}d" if days_until is not None and days_until >= 0 else ""
            return f"vs {m['opponent']} ({comp}){when}" if m.get("opponent") else f"{comp}{when}"

        next_match_label = match_label((recovery or {}).get("next_match"))
        fol = (recovery or {}).get("following_match")
        turnaround = fol.get("days_after") if fol else None
        following_label = match_label(fol)
        between_labels = [match_label(m) for m in ((recovery or {}).get("between") or [])]
        # Forward-looking signals, only when nothing more specific explains the row.
        if reason is None and tag == "fringe" and avail["kind"] == "ok":
            reason = "unused"  # fit, but no real minutes anywhere in the window
            rotation_note = rotation_note or f"{max(mins)} min max across the last {len(mins)} GWs - not in the plans"
        if reason is None and rest_days is not None and rest_days <= CONGESTION_DAYS:
            reason = "congestion"
            if not rotation_note:
                rotation_note = (f"{rest_days}d rest before {next_match_label}" if next_match_label else f"Only {rest_days}d rest before its next match") + (f" (after {between_labels[-1]})" if between_labels else "")
        if reason is None and turnaround is not None and turnaround <= SQUEEZE_DAYS:
            reason = "squeeze"  # plays again soon after the next match: the next one is the likelier rotation game
            if not rotation_note:
                rotation_note = f"Plays again {turnaround}d after {next_match_label or 'its next match'}: {following_label}"

        rows.append({
            "name": el["web_name"], "pos": POS[el["element_type"]], "club": club,
            "minutes": mins, "trend": tag, "note": note,
            "avail_kind": avail["kind"], "avail_label": avail["label"], "news": avail["news"],
            "reason": reason, "rotation_note": rotation_note,
            "rest_days": rest_days, "next_match_label": next_match_label,
            "turnaround_days": turnaround, "following_label": following_label, "between_labels": between_labels,
        })
    reason_rank = {"injury": 0, "rested": 1, "rotation": 2, "unused": 3, "congestion": 4, "squeeze": 5}
    def sort_key(r):
        # most actionable first: a flagged/dropped player, then a player nobody is playing, then forward-looking fixture pressure
        pri = reason_rank.get(r["reason"], 6) if r["reason"] is not None else (10 if r["trend"] == "rising" else 11)
        return (pri, r["minutes"][-1] - r["minutes"][0])
    rows.sort(key=sort_key)
    notable = [r for r in rows if r["reason"] is not None or r["trend"] == "rising"]
    return {"gws": recent_gws, "start_mins": start_mins, "target_gw": target_gw, "rows": rows, "notable": notable}

def build_value_board(boot, min_minutes=180, top_n=10, exclude=None):
    """Best points-per-money across the WHOLE player pool, split by position
    (comparing a £4m defender against a £15m forward on raw value isn't a
    fair scouting comparison) — league-wide, not scoped to your squad or
    ownership, since this is a "who's efficient right now" reference, not a
    transfer-target list. Recomputed from current total_points/now_cost on
    every refresh, so it moves with real returns and price changes rather
    than being a one-time snapshot — a player's price rise or a big haul
    shows up here on the next run, same as everywhere else in this app.
    min_minutes filters out small-sample flukes (e.g. a nailed-on cheap
    player who returned big off a single start)."""
    elements = boot["elements"]
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    by_pos = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for el in elements:
        mins = int(el.get("minutes") or 0)
        cost = el["now_cost"] / 10
        if mins < min_minutes or cost <= 0:
            continue
        if (el["web_name"], teams.get(el["team"], "?")) in (exclude or ()):
            continue  # already yours
        pts = int(el.get("total_points") or 0)
        row = {
            "name": el["web_name"], "club": teams.get(el["team"], "?"), "cost": cost,
            "points": pts, "minutes": mins, "owned_pct": float(el.get("selected_by_percent") or 0),
            "value_per_1m": round(pts / cost, 2),
        }
        by_pos[POS[el["element_type"]]].append(row)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda r: -r["value_per_1m"])
        by_pos[pos] = by_pos[pos][:top_n]
    return {"min_minutes": min_minutes, "top_n": top_n, "by_pos": by_pos}

def build_injury_watch(boot, squad_names=None, top_n=15):
    """Highest-ownership players league-wide currently flagged out/doubtful
    by FPL. Ownership %, not true Effective Ownership — FPL doesn't publish
    global captaincy rates to weight it by. A widely-owned player's injury
    matters to a lot more teams than a rarely-owned one's, regardless of
    how good the player is. `squad_names` (your own current squad, from
    build_plan) tags rows that affect you directly, not just the room."""
    teams = {t["id"]: t for t in boot["teams"]}
    squad_names = squad_names or set()
    rows = []
    for el in boot["elements"]:
        avail = player_availability(el)
        if avail["kind"] == "ok":
            continue
        rows.append({
            "id": el["id"], "name": el["web_name"], "club": teams[el["team"]]["short_name"], "pos": POS[el["element_type"]],
            "cost": el["now_cost"] / 10, "owned_pct": float(el.get("selected_by_percent") or 0),
            "status": avail["kind"], "label": avail["label"], "chance": avail["chance"],
            "yours": el["web_name"] in squad_names,
        })
    rows.sort(key=lambda r: -r["owned_pct"])
    # Not sliced to top_n here (unlike every other top-N builder in this
    # file) — main() needs the FULL out/doubt list to cross-reference against
    # mini-league ownership for the Injury tab's league section, since a
    # player with low GLOBAL ownership can still be a big deal to a specific
    # small league. top_n is passed through as a hint for the frontend to
    # slice the global table itself.
    return {"top_n": top_n, "rows": rows}

def build_price_radar(boot, team_id, picks_gw, top_n=8, extra_names=None, exclude=None):
    """Approximate price-change momentum from FPL's own transfer-volume
    fields: transfers_in_event/transfers_out_event (net transfers so far
    today) and cost_change_event/cost_change_start (price change already
    applied today / this season). FPL has never published its exact
    price-change algorithm, so "momentum" here — net transfers today as a
    % of the player's own current owner base (selected_by_percent% of
    total_players) — is a relative signal (a swing on a low-ownership
    player moves the needle far more than the same raw swing on a template
    player), not a guaranteed prediction of tonight's change."""
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}
    total_players = boot.get("total_players") or 0

    def row_of(el):
        inn, out = int(el.get("transfers_in_event") or 0), int(el.get("transfers_out_event") or 0)
        net = inn - out
        owned = float(el.get("selected_by_percent") or 0)
        owners = owned / 100 * total_players
        momentum = round(net / owners * 100, 1) if owners >= 1 else 0.0  # % of the player's own current owners, not a raw count
        season_change = (el.get("cost_change_start") or 0) / 10
        # FPL only ever moves a price by exactly £0.1m in a single change, so
        # "expected" is a direction call off today's momentum sign, not a
        # probability — the size of the move (if one happens) is fixed by
        # the rule itself, not something this needs to estimate.
        # Only a strong swing projects a move: a handful of net transfers is noise (a backtest found 2 of 89
        # "rising" calls right). FPL's counter is for the whole gameweek, not the day.
        # FPL now publishes its own progress towards a price change (price_change_percent: +100 = rise tonight, -100 =
        # fall) and a likelihood bucket; use that when present, and the transfer-momentum rule only as a fallback.
        try:
            fpl_pct = float(el.get("price_change_percent")) if el.get("price_change_percent") not in (None, "") else None
        except (TypeError, ValueError):
            fpl_pct = None
        if fpl_pct is not None:
            expected_change = 0.1 if fpl_pct >= 90 else (-0.1 if fpl_pct <= -90 else 0.0)
        else:
            strong = abs(momentum) >= 5 and abs(net) >= 5000
            expected_change = (0.1 if net > 0 else -0.1) if strong else 0.0
        return {
            "id": el["id"], "name": el["web_name"], "pos": POS[el["element_type"]], "club": teams[el["team"]]["short_name"],
            "fpl_pct": fpl_pct, "fpl_likelihood": ((el.get("price_change_projections") or [{}])[0] or {}).get("likelihood"),
            "cost": el["now_cost"] / 10, "owned_pct": owned, "net_transfers_today": net, "momentum": momentum,
            "changed_today": (el.get("cost_change_event") or 0) != 0,
            "cost_change_today": (el.get("cost_change_event") or 0) / 10,
            "season_change": season_change,
            "expected_change": expected_change,
            "expected_season_change": round(season_change + expected_change, 1),
        }

    squad_ids = set()
    if picks_gw:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
            squad_ids = {p["element"] for p in pk.get("picks") or [] if p.get("element") in elements}
        except Exception as e:
            _warn(f"build_price_radar: could not load GW{picks_gw} squad: {e}")

    squad_rows = sorted((row_of(elements[eid]) for eid in squad_ids), key=lambda r: -abs(r["momentum"]))
    all_rows = [row_of(el) for el in elements.values()]
    movers = [r for r in all_rows if (r["name"], r["club"]) not in (exclude or ())]  # your own players are in `squad`
    if any(r.get("fpl_pct") is not None for r in movers):      # FPL's own progress towards a change, closest first
        rising = sorted((r for r in movers if (r.get("fpl_pct") or 0) > 0), key=lambda r: -r["fpl_pct"])[:top_n]
        falling = sorted((r for r in movers if (r.get("fpl_pct") or 0) < 0), key=lambda r: r["fpl_pct"])[:top_n]
    else:
        rising = sorted((r for r in movers if r["net_transfers_today"] > 0), key=lambda r: -r["momentum"])[:top_n]
        falling = sorted((r for r in movers if r["net_transfers_today"] < 0), key=lambda r: r["momentum"])[:top_n]
    # `watch` is the actual decision set (wildcard-watch names + the wildcard
    # tab's own top-3 target names) rather than the top-N market movers —
    # every one of those names gets a row here even if its price hasn't
    # moved today, since "not currently rising/falling" is itself useful to
    # see for a player you're specifically weighing, not a reason to hide it.
    squad_names = {r["name"] for r in squad_rows}
    watch_names = {n for n in (extra_names or ()) if n not in squad_names}
    watch = [r for r in all_rows if r["name"] in watch_names]
    return {"squad": squad_rows, "rising": rising, "falling": falling, "watch": watch}

def build_price_trend(prev_trend, rows, today, max_days=7):
    """Rough 'how close to a price change' estimate for the decision-set
    players (squad + wildcard-watch) — built from OUR OWN observed momentum
    history across refreshes, not FPL's undisclosed threshold algorithm
    (which was never published, so it can't be modelled directly). The same
    momentum reading is a weaker signal on day one than after several
    consecutive days trending the same way, so this tracks a day-by-day
    history per player (one entry per calendar day — a day with several
    refreshes just overwrites that day's entry, it doesn't inflate the
    streak) and reports how many consecutive most-recent days have leaned
    the same direction with a non-trivial (>=5) momentum reading. Bounded
    to `max_days` per player so this can't grow unbounded over a season."""
    trend = {}
    for r in rows:
        name = f'{r["name"]}|{r["club"]}'     # two players can share a web_name: key on name + club
        prev = prev_trend.get(name) or prev_trend.get(r["name"]) or {}
        history = list(prev.get("history") or [])
        if history and history[-1].get("date") == today:
            history[-1] = {"date": today, "momentum": r["momentum"]}
        else:
            history.append({"date": today, "momentum": r["momentum"]})
        history = history[-max_days:]
        sign = 1 if r["momentum"] > 0 else (-1 if r["momentum"] < 0 else 0)
        streak = 0
        for h in reversed(history):
            h_sign = 1 if h["momentum"] > 0 else (-1 if h["momentum"] < 0 else 0)
            if sign != 0 and h_sign == sign and abs(h["momentum"]) >= 5:
                streak += 1
            else:
                break
        trend[name] = {"history": history, "streak_days": streak, "days_tracked": len(history)}
    return trend


def build_elite_ownership(boot, gw, top_n=50):
    """Ownership and captaincy among the top managers of the overall league (FPL only serves the first 50 of
    the overall table, so this is the top-50 sample, not a top-10k figure). Uses the picks of `gw`, the latest
    locked gameweek, as the best read of what the best managers hold right now."""
    from concurrent.futures import ThreadPoolExecutor
    if not gw:
        return {}
    standings = get("https://fantasy.premierleague.com/api/leagues-classic/314/standings/?page_standing=1")["standings"]["results"][:top_n]
    entries = [r["entry"] for r in standings]
    def picks(e):
        try:
            return get(f"https://fantasy.premierleague.com/api/entry/{e}/event/{gw}/picks/").get("picks") or []
        except Exception as ex:
            _warn(f"elite ownership: entry {e}: {ex}")
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        got = [p for p in pool.map(picks, entries) if p]
    if len(got) < 20:
        raise RuntimeError(f"only {len(got)} top-manager squads readable")
    own, cap = {}, {}
    for squad in got:
        for p in squad:
            own[p["element"]] = own.get(p["element"], 0) + 1
            if p.get("is_captain"):
                cap[p["element"]] = cap.get(p["element"], 0) + 1
    els = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    keep = sorted(own, key=lambda i: -own[i])[:60]
    return {"gw": gw, "n": len(got), "label": f"top {len(got)} of the overall table",
            "own": dict(own), "cap": cap,
            "names": {i: [els[i]["web_name"], teams[els[i]["team"]], POS[els[i]["element_type"]]] for i in set(keep) | set(cap) if i in els}}


def build_set_pieces(boot, mine=None):
    """First-choice penalty, direct free-kick and corner takers per club, from FPL's own taker-order fields."""
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    mine = set(mine or ())
    out = {tid: {"club": teams[tid], "pens": [], "fks": [], "corners": []} for tid in teams}
    for el in boot["elements"]:
        rec = out[el["team"]]
        item = {"name": el["web_name"], "yours": el["id"] in mine, "owned": float(el.get("selected_by_percent") or 0)}
        if el.get("penalties_order") == 1:
            rec["pens"].append(item)
        if el.get("direct_freekicks_order") == 1:
            rec["fks"].append(item)
        if el.get("corners_and_indirect_freekicks_order") == 1:
            rec["corners"].append(item)
    rows = sorted(out.values(), key=lambda r: r["club"])
    return {"rows": rows}

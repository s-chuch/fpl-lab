#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from league_tactics import build_tactics, pick_contenders
from lab_audit import add_roll_rows
import fpl_common
import fixtures_external
import copy
from fplbase import *
from fplbase import _warn, _fixtures_for, _fixtures_cache, _memo
from chips import *
from chips import _chip_week_facts, _best_xi_hindsight, _pair_squads, _rank_text
from signals import *
from signals import (_imminent_returns, _imminent_understat, _imminent_fpl, _load_theme_file,
                     _rotation_flagged_players, _comp_abbrev)
from ai_run import *
from ai_run import _clone_user_team












def format_pick_squad(picks, elements, teams):
    """XI + bench + captain from an entry event picks payload."""
    xi, bench = [], []
    captain = vice = None
    for p in sorted(picks or [], key=lambda x: x.get("position") or 99):
        el = elements.get(p["element"])
        if not el:
            continue
        name = el["web_name"]
        pos = POS[el["element_type"]]
        club = teams[el["team"]]["short_name"]
        item = {"id": p["element"], "name": name, "pos": pos, "club": club, "mult": p.get("multiplier") or 0}
        if p.get("is_captain"):
            captain = name
            item["captain"] = True
        if p.get("is_vice_captain"):
            vice = name
            item["vice"] = True
        if (p.get("position") or 99) <= 11:
            xi.append(item)
        else:
            bench.append(item)
    return {"xi": xi, "bench": bench, "captain": captain, "vice": vice}







def recommend(pos, fdr, cost, minutes, avail=None):
    if avail and avail.get("kind") == "out":
        return "OUT"
    if avail and avail.get("kind") == "doubt":
        ch = avail.get("chance")
        if ch is not None and ch < 50:
            return "OUT"
        return "DOUBT"
    if fdr is None: return "BLANK"
    if minutes < 30: return "SIT"
    if minutes < 60 and cost < 5.5: return "SIT"
    if pos == "GKP": return "START" if fdr <= 3 else "SIT"
    if pos == "DEF":
        if fdr >= 5 or (fdr >= 4 and cost < 5.5): return "SIT"
        return "START"
    if pos == "MID" and ((fdr >= 5 and cost < 8) or (fdr >= 4 and cost < 6.5)): return "SIT"
    if pos == "FWD" and fdr >= 5 and cost < 8: return "SIT"
    return "START"


def score(pos, fdr, form, minutes, cost, avail=None):
    if avail and avail.get("kind") == "out":
        return -99
    if fdr is None: return -99
    if minutes < 30: return -40 + form
    base = form * 2 + (6 - int(fdr)) * 2.2 + min(minutes, 270) / 90 + (0.4 if cost >= 9 else 0)
    if avail and avail.get("kind") == "doubt":
        ch = avail.get("chance")
        # Scale by chance and add a flat penalty so fit players win ties.
        factor = (ch / 100.0) if ch is not None else 0.5
        return base * factor - 8
    return base

def pick_lineup(players, gw_key):
    ranked = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in players:
        info = p["gws"].get(gw_key) or {}
        ranked[p["pos"]].append((info.get("score", -99), p))
    for pos in ranked:
        ranked[pos].sort(key=lambda x: x[0], reverse=True)
    picked, counts = [], {k: 0 for k in MINN}
    def take(p, tag=""):
        picked.append(p["name"] + tag)
        counts[p["pos"]] += 1
    started = lambda: {bare(x) for x in picked}
    if ranked["GKP"]:
        take(ranked["GKP"][0][1])
    for pos, n in MINN.items():
        if pos == "GKP":
            continue
        for _s, p in ranked[pos]:
            if counts[pos] >= n:
                break
            if p["name"] in started():
                continue
            take(p, " (C)" if pos == "FWD" and counts[pos] == 0 else "")
    pool = []
    for pos in ("DEF", "MID", "FWD"):
        for s, p in ranked[pos]:
            if p["name"] not in started():
                pool.append((s, p))
    pool.sort(key=lambda x: x[0], reverse=True)
    for s, p in pool:
        if len(picked) >= 11:
            break
        if counts[p["pos"]] >= MAXX[p["pos"]]:
            continue
        take(p)
    if picked and not any(x.endswith(" (C)") for x in picked):
        picked[0] = picked[0] + " (C)"
    if picked and not any(" (VC)" in x for x in picked):
        for i, name in enumerate(picked):
            if not name.endswith(" (C)"):
                picked[i] = name + " (VC)"
                break
    rest_gk = [p["name"] for _s, p in ranked["GKP"] if p["name"] not in started()]
    rest_of = [p["name"] for _s, p in sorted([(_s, p) for pos in ("DEF", "MID", "FWD") for _s, p in ranked[pos] if p["name"] not in started()], key=lambda x: x[0], reverse=True)]
    return picked[:11], (rest_gk + rest_of)[:4]

def _lineup_by_xp(boot, gw, players, teams, inputs=None):
    """The XI, bench order, captain and vice for a gameweek, all from the program's expected-points model
    (ai_team.player_values with the same Understat / rotation / congestion inputs the AI team uses): the best legal XI
    by this gameweek's expected points, so a blank or doubtful player drops out and the lineup, armband and AI team
    all agree. Returns None if the model cannot run."""
    try:
        import ai_team
        uwins, risk, _live = inputs or ({}, {}, None)
        played = max(1, sum(1 for e in boot["events"] if e.get("finished")))
        vals = ai_team.player_values(boot, fixture_scan(gw, teams), {}, played, uwins, risk)
        ids = [p["id"] for p in players]
        if len(ids) != 15 or any(i not in vals for i in ids):
            return None
        xi, bench = ai_team.pick_xi(ids, vals, "xp")
        ranked = sorted(xi, key=lambda i: -vals[i]["xp"])
        cap, vice = ranked[0], ranked[1]
        name = {p["id"]: p["name"] for p in players}
        tag = lambda i: name[i] + (" (C)" if i == cap else " (VC)" if i == vice else "")
        order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
        xi_sorted = sorted(xi, key=lambda i: (order[vals[i]["pos"]], -vals[i]["xp"]))
        return [tag(i) for i in xi_sorted], [name[i] for i in bench]
    except Exception as e:
        _warn(f"build_plan: lineup by expected points unavailable: {e}")
        return None


def _armband_by_xp(boot, gw, xi, players, teams, inputs=None):
    """Captain and vice-captain = the two highest expected-points players in the XI for that gameweek, from the
    same model (ai_team.player_values, with the same Understat/risk inputs) the AI team and Wildcard watch use,
    so the dashboard shows one captain. Falls back to the XI order's own tags if the model is unavailable."""
    try:
        import ai_team
        uwins, risk, _live = inputs or ({}, {}, None)
        finished = sum(1 for e in boot["events"] if e.get("finished"))
        played = max(1, finished)
        vals = ai_team.player_values(boot, fixture_scan(gw, teams), {}, played, uwins, risk)
        by_name = {p["name"]: p["id"] for p in players}
        clean = [bare(x) for x in xi]
        ranked = sorted(clean, key=lambda n: -(vals.get(by_name.get(n), {}).get("xp") or 0))
        cap, vice = ranked[0], ranked[1] if len(ranked) > 1 else None
        return [n + (" (C)" if n == cap else " (VC)" if n == vice else "") for n in clean]
    except Exception as e:
        _warn(f"build_plan: could not rank the armband by expected points: {e}")
        return xi








def build_plan(boot, team_id, hist=None, chips_used=None, inputs=None):
    teams = {t["id"]: t for t in boot["teams"]}
    elements = {e["id"]: e for e in boot["elements"]}
    events = sorted(boot["events"], key=lambda e: e["id"])
    finished = [e for e in events if e.get("finished")]
    now = datetime.now(timezone.utc)
    # Plan looks only at gameweeks you can still act on: once a GW's deadline has passed its
    # squad is locked, so it drops out and the window rolls to the next two open GWs.
    unfinished = [e for e in events if not e.get("finished")]
    open_gws = [e for e in unfinished if not (parse_deadline(e.get("deadline_time")) and now >= parse_deadline(e.get("deadline_time")))]
    upcoming = (open_gws or unfinished)[:2]
    last_fin = finished[-1] if finished else None
    picks, picks_gw, skipped_fh = [], None, None
    fh_gws = {v for k, v in (chips_used or {}).items() if chip_base(k) == "freehit"}
    for ev in reversed(events):
        if ev["id"] > (last_fin["id"] if last_fin else 0) + 1: continue
        try:
            payload = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{ev['id']}/picks/")
            chip = payload.get("active_chip")
            if chip == "freehit" or ev["id"] in fh_gws:
                skipped_fh = ev["id"]
                continue
            picks = payload.get("picks") or []
            if picks:
                picks_gw = ev["id"]; break
        except Exception as e:
            _warn(f"build_plan: could not load GW{ev['id']} picks: {e}")
            continue
    if not picks:
        return {"note": "Could not load squad picks.", "upcoming": [], "rows": []}
    maps, headers = {}, []
    for ev in upcoming:
        maps[ev["id"]] = fixture_map(ev["id"], teams)
        dl = ev.get("deadline_time") or ""
        dl_dt = parse_deadline(dl)
        headers.append({
            "gw": ev["id"],
            "deadline": fmt_deadline_et(dl) if dl else "",
            "deadline_utc": dl,
            "deadline_passed": bool(dl_dt and now >= dl_dt),
        })
    players, rows, availability = [], [], {}
    for pick in sorted(picks, key=lambda p: (elements[p["element"]]["element_type"], p["element"])):
        el = elements[pick["element"]]
        avail = player_availability(el)
        pos, form, mins, cost = POS[el["element_type"]], float(el.get("form") or 0), int(el.get("minutes") or 0), el["now_cost"] / 10
        gws, row = {}, [pos, el["web_name"], teams[el["team"]]["short_name"]]
        for ev in upcoming:
            info = maps[ev["id"]].get(el["team"])
            fdr = info["fdr"] if info else None
            cell = {
                "fixture": fmt_fix(info),
                "fdr": fdr,
                "call": recommend(pos, fdr, cost, mins, avail),
                "score": round(score(pos, fdr, form, mins, cost, avail), 2),
                "avail": avail["kind"],
                "avail_label": avail["label"],
            }
            gws[f"gw{ev['id']}"] = cell
            row.extend([cell["fixture"], fdr if fdr is not None else "-", cell["call"]])
        players.append({"id": el["id"], "name": el["web_name"], "pos": pos, "gws": gws, "cost": cost, "avail": avail})
        if avail["kind"] != "ok":
            availability[el["web_name"]] = {**avail, "id": el["id"]}
        rows.append(row)
    xis = {}
    for ev in upcoming:
        key = f"gw{ev['id']}"
        xi, bn = _lineup_by_xp(boot, ev["id"], players, teams, inputs) or (None, None)
        if xi is None:                       # model unavailable: the older fixture/form heuristic
            xi, bn = pick_lineup(players, key)
            xi = _armband_by_xp(boot, ev["id"], xi, players, teams, inputs)
        xis[key] = {"xi": xi, "bench": bn}
    for i, ev in enumerate(upcoming):
        started = {bare(n) for n in xis[f"gw{ev['id']}"]["xi"]}
        for r in rows:
            fix = r[3 + i * 3]
            name = r[1]
            avail = availability.get(name) or {}
            if fix == "Blank":
                r[5 + i * 3] = "BLANK"
            elif avail.get("kind") == "out":
                r[5 + i * 3] = "OUT"
            elif avail.get("kind") == "doubt" and name not in started:
                r[5 + i * 3] = "DOUBT"
            else:
                r[5 + i * 3] = "START" if name in started else "SIT"
        for p in players:
            cell = p["gws"].get(f"gw{ev['id']}") or {}
            avail = p.get("avail") or {}
            if cell.get("fixture") == "Blank":
                cell["call"] = "BLANK"
            elif avail.get("kind") == "out":
                cell["call"] = "OUT"
            elif avail.get("kind") == "doubt" and p["name"] not in started:
                cell["call"] = "DOUBT"
            else:
                cell["call"] = "START" if p["name"] in started else "SIT"
    ft = free_transfers_for_next(hist or {})
    fh_used = bool(chip_for_gw(chips_used or {}, "freehit", (upcoming[0]["id"] if upcoming else 0)))
    bench_calls = []
    for ev in upcoming:
        key = f"gw{ev['id']}"
        sits = []
        for p in players:
            cell = p["gws"].get(key) or {}
            if cell.get("call") not in ("SIT", "BLANK", "OUT", "DOUBT"):
                continue
            avail = p.get("avail") or {}
            sits.append({
                "player": p["name"],
                "fixture": cell.get("fixture"),
                "fdr": cell.get("fdr"),
                "call": cell.get("call"),
                "avail": avail.get("kind"),
                "news": avail.get("news") or "",
            })
        def sit_key(x):
            # Prioritise injured/out, then doubtful, then hardest fixtures.
            pri = 0 if x.get("avail") == "out" else (1 if x.get("avail") == "doubt" else 2)
            return (pri, -(x["fdr"] or 0))
        sits.sort(key=sit_key)
        top = sits[0] if sits else None
        if top and top.get("avail") in ("out", "doubt"):
            why = f"{top['player']} {top.get('call')} · {(top.get('news') or top.get('fixture') or '').strip()}"
        elif top:
            why = f"{top['player']} {top['fixture']} FDR {top['fdr']}"
        else:
            why = "No sit"
        bench_calls.append({"gw": ev["id"], "sit": xis[key]["bench"], "worst": top["player"] if top else None, "why": why})
    who = "Shaaland" if team_id == 1360999 else "the original squad"
    action, move, reason = "ROLL", None, f"You have {ft} FT. " + (f"FH unused — roll so the FT returns with {who}." if not fh_used else "No forced move. Bank it.")
    note = f"GW{picks_gw} squad. Last finished {(last_fin or {}).get('id')}."
    if skipped_fh:
        note = f"GW{picks_gw} squad (GW{skipped_fh} was Free Hit; reverted). Last finished {(last_fin or {}).get('id')}."
    # Intel targets the next GW whose deadline has not passed (not stale locked GW themes)
    ds = deadline_state(boot, now)
    intel_gw = ds["intel_gw"]
    # Intel is clear once the news themes are for the gameweek we are planning (or later)
    try:
        _news_gw = fpl_common.load_js_object(ROOT / "news.js").get("gw")
    except Exception:
        _news_gw = None
    intel_clear = bool(intel_gw and _news_gw is not None and int(_news_gw) >= int(intel_gw))
    return {
        "note": note,
        "last_finished": (last_fin or {}).get("id"),
        "squad_from_gw": picks_gw,
        "upcoming": headers,
        "rows": rows,
        "xis": xis,
        "bench_calls": bench_calls,
        "availability": availability,
        "squad_ids": [p["id"] for p in players],
        "transfer": {"ft_available": ft, "action": action, "reason": reason, "move": move, "fh_unused": not fh_used},
        "deadline_passed": ds["deadline_passed"],
        "locked_gw": ds["locked_gw"],
        "next_gw": ds["next_gw"],
        "intel_gw": intel_gw,
        # UI clears Plan themes when news/x gw < intel_gw (locked-GW consensus is stale)
        "intel_clear": intel_clear,
        "intel_note": (
            f"Waiting for GW{intel_gw} intel — GW{ds['locked_gw']} deadline has passed."
            if (not intel_clear) and ds["deadline_passed"] and ds["locked_gw"] and intel_gw
            else None
        ),
    }

def captain_audit(boot, team_id):
    names = {e["id"]: e["web_name"] for e in boot["elements"]}
    out = []
    for ev in boot["events"]:
        if not ev.get("finished"): continue
        gw = ev["id"]
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
            live = get(f"https://fantasy.premierleague.com/api/event/{gw}/live/")
        except Exception as e:
            _warn(f"captain_audit: could not load GW{gw} picks/live: {e}")
            continue
        pts = {el["id"]: el["stats"]["total_points"] for el in live.get("elements", [])}
        cap = next((p for p in pk.get("picks", []) if p.get("is_captain")), None)
        vc = next((p for p in pk.get("picks", []) if p.get("is_vice_captain")), None)
        if not cap: continue
        cap_raw = pts.get(cap["element"], 0)
        vc_raw = pts.get(vc["element"], 0) if vc else 0
        # If the captain didn't play, FPL promotes the vice: grade the pick that
        # actually carried the armband (multiplier >= 2), not the nominal captain.
        eff = cap if (cap.get("multiplier") or 0) >= 2 else (vc if vc and (vc.get("multiplier") or 0) >= 2 else cap)
        mult = eff.get("multiplier")
        if mult is None:
            mult = 2
        cmult = mult if mult >= 2 else 2  # multiplier for the vs_vc/vs_best counterfactuals
        eff_raw = pts.get(eff["element"], 0)
        best_id, best_raw = cap["element"], cap_raw
        for p in pk.get("picks", []):
            raw = pts.get(p["element"], 0)
            if raw > best_raw:
                best_id, best_raw = p["element"], raw
        got = eff_raw * mult
        out.append({"gw": gw, "chip": pk.get("active_chip"), "captain": names.get(cap["element"], "?"), "captain_raw": cap_raw, "got": got, "vc": names.get(vc["element"], "?") if vc else "-", "vc_raw": vc_raw, "best": names.get(best_id, "?"), "best_raw": best_raw, "vs_vc": got - vc_raw * cmult, "vs_best": got - best_raw * cmult})
    return out

def _best_xi(squad):
    """Best legal XI by final points, with the actual captain pinned first —
    same rule _process_xi uses. Bench-audit's "hindsight" is meant to isolate
    the LINEUP decision (who started vs. who was benched), not captaincy,
    which is a separate call graded elsewhere (captain_audit). Without
    pinning, this would silently re-captain to whoever scored highest in the
    chosen XI, so a blank captain week showed up as a "bench miss" here even
    when the actual bench/lineup was fine — bench points have nothing to do
    with captain points."""
    cap_name = next((p["name"] for p in squad if p.get("captain")), None)
    by = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in squad:
        by[p["pos"]].append(p)
    for pos in by:
        by[pos].sort(key=lambda x: (x["name"] != cap_name, -x["pts"]))
    picked, counts = [], {k: 0 for k in MINN}
    if by["GKP"]:
        picked.append(by["GKP"][0]); counts["GKP"] = 1
    have = lambda: {p["name"] for p in picked}
    for pos, n in MINN.items():
        if pos == "GKP":
            continue
        for p in by[pos]:
            if counts[pos] >= n:
                break
            if p["name"] in have():
                continue
            picked.append(p); counts[pos] += 1
    pool = [p for pos in ("DEF", "MID", "FWD") for p in by[pos] if p["name"] not in have()]
    pool.sort(key=lambda x: (x["name"] != cap_name, -x["pts"]))
    for p in pool:
        if len(picked) >= 11:
            break
        if counts[p["pos"]] >= MAXX[p["pos"]]:
            continue
        picked.append(p); counts[p["pos"]] += 1
    return picked

def _process_xi(squad, mins_key="mins"):
    """Best legal XI judged only by minutes, not final points: a bench player only
    displaces a starter here if they played strictly more minutes by `mins_key` — a
    call you could make without knowing the final scoreline. The real captain is
    pinned first so the multiplier isn't re-litigated by this heuristic.

    `mins_key` selects WHICH minutes decide who was "nailed on": the default,
    "mins", is that gameweek's own actual minutes (used by the Free Hit audit,
    which asks "how would this exact squad's real GW have gone"). bench_audit
    instead passes "trail_mins" — minutes from the GWs BEFORE the one being
    judged — since a genuine process call has to be based on what was knowable
    heading into the deadline, not on minutes that only exist after kickoff."""
    cap_name = next((p["name"] for p in squad if p.get("captain")), None)
    by = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in squad:
        by[p["pos"]].append(p)
    for pos in by:
        by[pos].sort(key=lambda x: (x["name"] != cap_name, -x[mins_key], not x["started"]))
    picked, counts = [], {k: 0 for k in MINN}
    if by["GKP"]:
        picked.append(by["GKP"][0]); counts["GKP"] = 1
    have = lambda: {p["name"] for p in picked}
    for pos, n in MINN.items():
        if pos == "GKP":
            continue
        for p in by[pos]:
            if counts[pos] >= n:
                break
            if p["name"] in have():
                continue
            picked.append(p); counts[pos] += 1
    pool = [p for pos in ("DEF", "MID", "FWD") for p in by[pos] if p["name"] not in have()]
    pool.sort(key=lambda x: (x["name"] != cap_name, -x[mins_key], not x["started"]))
    for p in pool:
        if len(picked) >= 11:
            break
        if counts[p["pos"]] >= MAXX[p["pos"]]:
            continue
        picked.append(p); counts[p["pos"]] += 1
    return picked

def build_captain_board(boot, team_id, lookback=3):
    """Per-GW captain audit shaped like the bench audit: You / Process / Hindsight.
    You = what the armband actually returned (the effective captain's points x multiplier,
    so a vice who took over, or a Triple Captain, is graded as played). Process = the
    starter who had the best points-per-appearance over the `lookback` finished GWs BEFORE
    this one - a call you could make at the deadline without the result. Hindsight = the
    top scorer among the XI that started (the armband can't go on a benched player)."""
    names = {e["id"]: e["web_name"] for e in boot["elements"]}
    finished = sorted(e["id"] for e in boot["events"] if e.get("finished"))
    live_cache = {}
    def live_for(g):
        if g not in live_cache:
            try:
                live_cache[g] = {el["id"]: (el["stats"].get("total_points", 0), el["stats"].get("minutes", 0))
                                 for el in get(f"https://fantasy.premierleague.com/api/event/{g}/live/").get("elements", [])}
            except Exception as e:
                _warn(f"build_captain_board: could not load GW{g} live data: {e}")
                live_cache[g] = None
        return live_cache[g]
    out = {}
    for gw in finished:
        live = live_for(gw)
        if live is None:
            continue
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
        except Exception as e:
            _warn(f"build_captain_board: could not load GW{gw} picks: {e}")
            continue
        picks = pk.get("picks") or []
        cap = next((x for x in picks if x.get("is_captain")), None)
        vc = next((x for x in picks if x.get("is_vice_captain")), None)
        if not cap:
            continue
        pts = lambda eid: live.get(eid, (0, 0))[0]
        eff = next((x for x in (cap, vc) if x and (x.get("multiplier") or 0) >= 2), cap)
        mult = max(2, eff.get("multiplier") or 2)
        you = pts(eff["element"]) * mult
        starters = [x for x in picks if x["position"] <= 11]
        prior = [g for g in finished if g < gw][-lookback:]
        def form(eid):
            seen = [live_for(g) for g in prior]
            played = [d[eid][0] for d in seen if d and eid in d and d[eid][1] > 0]
            return sum(played) / len(played) if played else -1
        proc = max(starters, key=lambda x: (form(x["element"]), x["element"] == cap["element"])) if starters else cap
        if form(proc["element"]) < 0:
            proc = cap  # no track record to judge on: the only defensible call is the one made
        best = max(starters or [cap], key=lambda x: pts(x["element"]))
        top = sorted(starters, key=lambda x: -pts(x["element"]))[:5]
        out[f"gw{gw}"] = {
            "you": you, "process": pts(proc["element"]) * mult, "hindsight": pts(best["element"]) * mult,
            "mult": mult, "chip": pk.get("active_chip"),
            "captain": [names.get(cap["element"], "?"), pts(cap["element"])],
            "vice": [names.get(vc["element"], "?"), pts(vc["element"])] if vc else None,
            "effective": names.get(eff["element"], "?"),
            "process_pick": [names.get(proc["element"], "?"), pts(proc["element"]), round(form(proc["element"]), 1)],
            "best": [names.get(best["element"], "?"), pts(best["element"])],
            "options": [[names.get(x["element"], "?"), pts(x["element"])] for x in top],
        }
    return out

def build_bench_audit(boot, team_id, lookback=3):
    """`process` grades your bench call against what was knowable BEFORE the
    deadline, not against what happened in the gameweek itself: a player's
    "process" minutes are their trailing minutes from the `lookback` finished
    GWs before the one being judged (a true pre-deadline signal — reusing the
    gameweek's OWN actual minutes would grade the decision on its outcome,
    which is exactly the outcome-bias process-vs-outcome is meant to avoid).
    Early gameweeks with no/short history fall back to fewer prior GWs, and
    with zero history _process_xi's minutes-tie falls through to whichever
    player you actually started — the only defensible "process" call when
    there's no track record yet."""
    names = {e["id"]: e["web_name"] for e in boot["elements"]}
    pmap = {e["id"]: POS[e["element_type"]] for e in boot["elements"]}
    finished_gws = sorted(e["id"] for e in boot["events"] if e.get("finished"))
    live_cache = {}
    def live_for(g):
        if g not in live_cache:
            try:
                live_cache[g] = get(f"https://fantasy.premierleague.com/api/event/{g}/live/").get("elements", [])
            except Exception as e:
                _warn(f"build_bench_audit: could not load GW{g} live data: {e}")
                live_cache[g] = None  # unavailable: callers skip it rather than treat as 0 pts/0 mins
        return live_cache[g]

    out = {}
    for gw in finished_gws:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
        except Exception as e:
            _warn(f"build_bench_audit: could not load GW{gw} picks: {e}")
            continue
        if pk.get("active_chip") == "bboost":
            # Bench Boost makes the whole audit meaningless: every one of the
            # 15 counts toward "you" regardless of bench position, so there
            # was no actual start/sit decision to grade that week — comparing
            # that bench-boosted real score against an 11-man-only process/
            # hindsight XI is an apples-to-oranges number, not a real miss.
            continue
        live_elems = live_for(gw)
        if live_elems is None:
            continue
        pts = {el["id"]: el["stats"]["total_points"] for el in live_elems}
        mins = {el["id"]: el["stats"].get("minutes", 0) for el in live_elems}
        prior_gws = [g for g in finished_gws if g < gw][-lookback:]
        trail_mins = {}
        for g in prior_gws:
            for el in live_for(g) or []:
                trail_mins[el["id"]] = trail_mins.get(el["id"], 0) + int(el["stats"].get("minutes") or 0)
        cap = next((p for p in pk.get("picks", []) if p.get("is_captain")), None)
        mult = (cap or {}).get("multiplier") or 2
        squad, bench = [], []
        for p in pk.get("picks", []):
            item = {
                "name": names.get(p["element"], "?"),
                "pos": pmap.get(p["element"], "MID"),
                "pts": pts.get(p["element"], 0),
                "mins": mins.get(p["element"], 0),
                "trail_mins": trail_mins.get(p["element"], 0),
                "started": p["position"] <= 11,
                "captain": bool(p.get("is_captain")),
            }
            squad.append(item)
            if p["position"] > 11:
                bench.append([item["name"], item["pts"]])
        best = _best_xi(squad)
        started = {p["name"] for p in best}
        you = (pk.get("entry_history") or {}).get("points")
        raw = sum(p["pts"] for p in best)
        # Actual captain's own points, not a virtual re-captain to whoever
        # scored highest — hindsight is meant to grade the lineup only, and
        # _best_xi already guarantees the real captain is in `best`.
        best_cap_pts = next((p["pts"] for p in best if p["captain"]), 0)
        hindsight = raw + best_cap_pts * (mult - 1)
        proc_xi = _process_xi(squad, mins_key="trail_mins")
        proc_started = {p["name"] for p in proc_xi}
        proc_cap_pts = next((p["pts"] for p in proc_xi if p["captain"]), 0)
        process = sum(p["pts"] for p in proc_xi) + proc_cap_pts * (mult - 1)
        # "Should have benched" is judged by PROCESS (who was nailed on
        # trailing minutes heading into this GW), not pure outcome — a
        # starter who was clearly a fixture but had a quiet points day (e.g.
        # a nailed captain blanking) isn't a bench mistake, so flagging them
        # via hindsight's points-only best XI was misleading. `better` now
        # lists actual starters process XI wouldn't have started, i.e. it
        # wanted a currently-benched player (by trailing minutes) instead.
        better = [[p["name"], p["pts"]] for p in squad if p["started"] and p["name"] not in proc_started]
        # Per-bench-player verdict, auto-derived instead of hand-typed per GW:
        # "process" = minutes said they should've started (a real misread),
        # "variance" = not a nailed-minutes starter, but scored well enough
        # that hindsight's best XI (`started`) still wanted them anyway (bad
        # luck, not a mistake), "ok" = correctly left out either way — i.e. in
        # `better`/`better_names`, hindsight's own worst scorers, which is
        # what "correctly benched" actually looks like.
        bench_tags = {}
        for name, _pts in bench:
            if name in proc_started:
                bench_tags[name] = "process"
            elif name in started:
                bench_tags[name] = "variance"
            else:
                bench_tags[name] = "ok"
        out[f"gw{gw}"] = {"you": you, "process": process, "hindsight": hindsight, "your_bench": bench, "better_bench": better[:4], "bench_tags": bench_tags}
    return out













def build_transfers(boot, team_id):
    """Every transfer made this season, with the points swing (existing) and
    the actual price paid/received (element_in_cost/element_out_cost — the
    FPL transfers endpoint's own record of the deal, not today's price) so
    the season's real buy/sell history is visible, not just this GW's points
    verdict. This is the authoritative source for "what did I actually pay
    and get" from GW1 to now — see build_live_value below, which reuses this
    same raw transfers data to compute an actually-current squad value
    (last_deadline_value is frozen at the last deadline, not live)."""
    names = {e["id"]: e["web_name"] for e in boot["elements"]}
    try:
        rows = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/transfers/")
    except Exception as e:
        _warn(f"build_transfers: could not load transfers list: {e}")
        return []
    live_cache, out = {}, []
    for t in rows:
        gw = t.get("event")
        if gw not in live_cache:
            try:
                live_cache[gw] = {el["id"]: el["stats"]["total_points"] for el in get(f"https://fantasy.premierleague.com/api/event/{gw}/live/").get("elements", [])}
            except Exception as e:
                _warn(f"build_transfers: could not load GW{gw} live data: {e}")
                live_cache[gw] = {}
        inn, outp = names.get(t["element_in"], "?"), names.get(t["element_out"], "?")
        pin, pout = live_cache[gw].get(t["element_in"], 0), live_cache[gw].get(t["element_out"], 0)
        net = pin - pout
        verdict = "Good that GW" if net > 1 else ("Lost that GW" if net < -1 else "Even that GW")
        out.append({
            "gw": gw, "out": outp, "inn": inn, "net": ("+" if net > 0 else "") + str(net), "verdict": verdict,
            "out_price": (t.get("element_out_cost") or 0) / 10, "in_price": (t.get("element_in_cost") or 0) / 10,
        })
    out.sort(key=lambda x: x["gw"] or 0)
    return out

def build_live_value(boot, team_id, picks_gw, hist, entry, locked_gw):
    """Live squad value + bank via FPL's real profit-share sell-price rule
    (half the profit since purchase, rounded down to the nearest £0.1m; a
    loss is passed through in full) — entry['last_deadline_value']/
    ['last_deadline_bank'] are frozen as of the LAST DEADLINE and don't move
    with price changes since.

    This reflects the last LOCKED, currently-scored squad — the team you'd
    actually have if you never confirmed a wildcard/transfers before the next
    deadline. It does NOT and structurally CANNOT reflect an in-progress,
    not-yet-confirmed wildcard draft: FPL's public API never exposes a
    provisional squad before its own deadline, not even your own team's
    (same limitation wildcard_recommend.py's own docstring documents — that's
    exactly why the wildcard-watch files are hand-curated from screenshots
    instead of scraped). While Wildcard is active, FPL's own app shows the
    DRAFT's value on its Transfers/Finance screen, which this field will not
    match — that's `worth_tracker.current.total_cost` in the wildcard-watch
    files instead, computed from the hand-entered draft squad."""
    elements = {e["id"]: e for e in boot["elements"]}
    picks = []
    if picks_gw:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
            picks = pk.get("picks") or []
        except Exception as e:
            _warn(f"build_live_value: could not load GW{picks_gw} squad: {e}")
    if not picks:
        return None
    try:
        raw_transfers = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/transfers/")
    except Exception as e:
        _warn(f"build_live_value: could not load transfers list: {e}")
        raw_transfers = []

    # Free Hit gws excluded: a buy made only during a Free Hit reverts and
    # isn't part of the permanently-held squad's cost basis; a genuine
    # Wildcard buy is real and permanent, so it's NOT excluded.
    fh_gws = {c["event"] for c in hist.get("chips", []) if c.get("name") == "freehit"}
    ordered = sorted(
        (t for t in raw_transfers if t.get("event") not in fh_gws),
        key=lambda t: (t.get("event") or 0, t.get("time") or ""),
    )
    last_in_cost = {}
    for t in ordered:
        if t.get("element_in") is not None:
            last_in_cost[t["element_in"]] = t.get("element_in_cost")

    total_sell_tenths = 0
    for p in picks:
        el = elements.get(p.get("element"))
        if not el:
            continue
        now_cost = el["now_cost"]
        purchase_cost = last_in_cost.get(el["id"])
        if purchase_cost is None:
            purchase_cost = now_cost - (el.get("cost_change_start") or 0)  # held since GW1
        sell = purchase_cost + (now_cost - purchase_cost) // 2 if now_cost > purchase_cost else now_cost
        total_sell_tenths += sell

    bank_tenths = entry.get("last_deadline_bank", 0)
    # Only when picks_gw is AHEAD of locked_gw: in a Free Hit week picks_gw is
    # the earlier GW, and last_deadline_bank already includes its transfers.
    # Defensive only: in practice `picks_gw` (from build_plan) never actually
    # gets ahead of `locked_gw`, because FPL's public picks endpoint 404s for
    # any not-yet-deadlined gameweek (confirmed live) — so this can't correct
    # for an in-progress wildcard draft, which is invisible to this scraper
    # regardless. Kept in case FPL's visibility rules differ in some case not
    # yet observed; last_deadline_bank is used as-is the rest of the time.
    if locked_gw is not None and picks_gw is not None and picks_gw > locked_gw:
        for t in ordered:
            if t.get("event") == picks_gw:
                bank_tenths += (t.get("element_out_cost") or 0) - (t.get("element_in_cost") or 0)

    return {"squad_value": round(total_sell_tenths / 10, 1), "bank": round(bank_tenths / 10, 1)}




































def build_transfer_targets(boot, team_id, picks_gw, top_n=8, min_minutes=180):
    """Scouting lists for the Plan tab: players you DON'T currently own with
    strong underlying attacking numbers (xG+xA per 90) or a reliable
    Defensive Contribution rate — the same underlying-stats signals already
    used to audit your own squad (build_xg_signal / build_defcon), applied
    league-wide and filtered to non-owned players, as concrete transfer
    targets rather than just a read on your existing 15."""
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}

    def to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    squad_ids = set()
    if picks_gw:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
            squad_ids = {p["element"] for p in pk.get("picks") or [] if p.get("element") in elements}
        except Exception as e:
            _warn(f"build_transfer_targets: could not load GW{picks_gw} squad: {e}")

    finished_gws = sum(1 for e in boot["events"] if e.get("finished"))
    xg_rows, defcon_rows = [], []
    for el in elements.values():
        if el["id"] in squad_ids:
            continue
        mins = int(el.get("minutes") or 0)
        if mins < min_minutes or not scouting_ok(el, finished_gws):
            continue
        pos = POS[el["element_type"]]
        club = teams[el["team"]]["short_name"]
        cost, owned = el["now_cost"] / 10, float(el.get("selected_by_percent") or 0)
        p90 = mins / 90

        if pos != "GKP":
            xgi = to_float(el.get("expected_goal_involvements"))
            if xgi is None:
                xgi = (to_float(el.get("expected_goals")) or 0.0) + (to_float(el.get("expected_assists")) or 0.0)
            xg_rows.append({
                "name": el["web_name"], "pos": pos, "club": club, "cost": cost, "owned_pct": owned,
                "goals": int(el.get("goals_scored") or 0), "assists": int(el.get("assists") or 0),
                "xgi": round(xgi, 2), "xgi_p90": round(xgi / p90, 2) if p90 else 0.0,
            })

        if pos in DEFCON_THRESHOLD:
            per90 = to_float(el.get("defensive_contribution_per_90"))
            threshold = DEFCON_THRESHOLD[pos]
            if per90 is not None and per90 >= threshold:
                defcon_rows.append({
                    "name": el["web_name"], "pos": pos, "club": club, "cost": cost, "owned_pct": owned,
                    "per90": round(per90, 2), "threshold": threshold, "margin": round(per90 - threshold, 2),
                })

    xg_rows.sort(key=lambda r: -r["xgi_p90"])
    defcon_rows.sort(key=lambda r: -r["margin"])
    return {"min_minutes": min_minutes, "xg": xg_rows[:top_n], "defcon": defcon_rows[:top_n]}


def _intel_tags_by_player(root):
    """Every player's News qualifier tags (fpl_common.QUALIFIER_PATTERNS),
    merged across both sources' agreed+split themes — reused by build_targets
    as a light "what's the internet already saying about this player" signal
    on top of the app's own underlying-stats signals. Same {agreed, split}
    shape and reuse pattern as _rotation_flagged_players above, just keyed on
    every tag instead of filtering to one."""
    tags = {}
    for filename in ("news.js",):
        data = _load_theme_file(root, filename)
        if data is None:
            continue
        for item in (data.get("agreed") or []) + (data.get("split") or []):
            if item.get("player"):
                tags.setdefault(item["player"], set()).update(item.get("tags") or [])
    return tags


TARGET_HORIZONS = (1, 3, 6)

def build_targets(boot, min_minutes=180, threshold=2.0, top_n=15, exclude=None):
    """League-wide "who to target" shortlists for the Target tab, at three
    look-ahead horizons (next 1/3/6 GWs) — combining the same underlying
    signals already shown on the Strategy tab (form, xGI/90, DEFCON
    reliability, points-per-£1m value, xG/xA over/underperformance) with
    the Intel tab's News "transfer target"/"fade" consensus, so the two
    tabs' signals feed one shortlist instead of the user mentally combining
    six tabs themselves.

    Only the fixture-ease component changes across horizons (a club's
    average FDR over its next N fixtures); every other signal reflects
    current underlying quality and is computed once, then reused for all
    three lists. Scoring is a plain, documented point count rather than a
    hidden weighted formula — each signal contributes at most 1-2 points
    when a player clears a fixed threshold, and every point is shown back
    to the user as a "Why" tag rather than only a bare score. A player FPL
    itself flags as out is excluded outright; a doubt is kept but never
    scored positively. `exclude` is a set of (name, club) pairs — the current
    squad — so the shortlist only ever shows players you don't already have.
    """
    teams = {t["id"]: t for t in boot["teams"]}
    exclude = exclude or set()

    def to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    intel = _intel_tags_by_player(ROOT)

    # Only gameweeks you can still act on: a live gameweek whose deadline has passed is not a target horizon.
    now_utc = datetime.now(timezone.utc)
    upcoming = sorted((e for e in boot["events"] if not e.get("finished")
                       and not (parse_deadline(e.get("deadline_time")) and now_utc >= parse_deadline(e.get("deadline_time")))),
                      key=lambda e: e["id"])[:max(TARGET_HORIZONS)]
    fdr_samples = {n: {} for n in TARGET_HORIZONS}  # horizon -> team_id -> [fdr,...]
    blank_gws = {n: {} for n in TARGET_HORIZONS}    # horizon -> team_id -> gameweeks with no fixture
    double_gws = {n: {} for n in TARGET_HORIZONS}   # horizon -> team_id -> gameweeks with two or more
    for i, ev in enumerate(upcoming, start=1):
        try:
            fx = fixture_scan(ev["id"], teams)
        except Exception as e:
            _warn(f"build_targets: could not load GW{ev['id']} fixtures: {e}")
            continue
        for tid in teams:
            fixtures = fx.get(tid, [])
            for n in TARGET_HORIZONS:
                if i <= n:
                    fdr_samples[n].setdefault(tid, []).extend(f["fdr"] for f in fixtures if f.get("fdr") is not None)
                    if not fixtures:
                        blank_gws[n][tid] = blank_gws[n].get(tid, 0) + 1
                    elif len(fixtures) > 1:
                        double_gws[n][tid] = double_gws[n].get(tid, 0) + 1
    avg_fdr = {n: {tid: round(sum(v) / len(v), 2) for tid, v in fdr_samples[n].items() if v} for n in TARGET_HORIZONS}

    # Points-per-£1m value is only meaningful relative to a position's own
    # pool (a £4.5m defender and a £15m forward aren't comparable in raw
    # value), so rank each position's qualifying players and flag the top
    # quartile — same idea as build_value_board, computed inline here since
    # that function only returns its own top_n cut, not the full pool.
    value_by_pos = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for el in boot["elements"]:
        if int(el.get("minutes") or 0) < min_minutes:
            continue
        cost = el["now_cost"] / 10
        if cost > 0:
            value_by_pos[POS[el["element_type"]]].append((el["id"], (el.get("total_points") or 0) / cost))
    good_value_ids = set()
    for pos_rows in value_by_pos.values():
        pos_rows.sort(key=lambda r: -r[1])
        good_value_ids.update(eid for eid, _ in pos_rows[:max(1, len(pos_rows) // 4)])

    rows = []
    for el in boot["elements"]:
        if int(el.get("minutes") or 0) < min_minutes:
            continue
        avail = player_availability(el)
        if avail["kind"] == "out":
            continue  # never recommend a player FPL itself says can't play
        if (el["web_name"], teams[el["team"]]["short_name"]) in exclude:
            continue  # already in the squad: a target is someone you don't have

        pos = POS[el["element_type"]]
        name = el["web_name"]
        try:
            form = float(el.get("form") or 0)
        except (TypeError, ValueError):
            form = 0.0
        xgi = to_float(el.get("expected_goal_involvements"))
        if xgi is None:
            xgi = (to_float(el.get("expected_goals")) or 0.0) + (to_float(el.get("expected_assists")) or 0.0)
        mins = int(el.get("minutes") or 0)
        p90 = mins / 90
        xgi_p90 = round(xgi / p90, 2) if p90 else 0.0
        gi = int(el.get("goals_scored") or 0) + int(el.get("assists") or 0)
        gi_diff = gi - xgi  # same over/underperformance signal as build_xg_signal's Diff column

        defcon_ok = False
        if pos in DEFCON_THRESHOLD:
            per90 = to_float(el.get("defensive_contribution_per_90"))
            defcon_ok = per90 is not None and per90 >= DEFCON_THRESHOLD[pos]

        tags_here = intel.get(name) or set()
        rows.append({
            "id": el["id"], "team_id": el["team"], "name": name, "pos": pos, "club": teams[el["team"]]["short_name"],
            "cost": el["now_cost"] / 10, "owned_pct": to_float(el.get("selected_by_percent")) or 0.0,
            "form": form, "xgi_p90": xgi_p90, "defcon_ok": defcon_ok,
            "due_return": pos != "GKP" and gi_diff <= -threshold,
            "overperforming": pos != "GKP" and gi_diff >= threshold,
            "good_value": el["id"] in good_value_ids,
            "intel_target": "transfer target" in tags_here,
            "intel_fade": bool(tags_here & {"fade/sell", "injury/doubt"}),
            "doubt": avail["kind"] == "doubt",
        })

    out = {}
    for n in TARGET_HORIZONS:
        scored = []
        for r in rows:
            fdr = avg_fdr[n].get(r["team_id"])
            kind_run = fdr is not None and fdr <= 2.6
            why = []
            score = 0
            if r["form"] >= 6.0:
                why.append("In form"); score += 2
            if r["pos"] != "GKP" and r["xgi_p90"] >= 0.5:
                why.append("Strong xGI"); score += 2
            if r["defcon_ok"]:
                why.append("Reliable DEFCON"); score += 1
            if r["good_value"]:
                why.append("Great value"); score += 1
            if r["due_return"]:
                why.append("Due a return"); score += 1
            if r["overperforming"]:
                why.append("Sell-high risk"); score -= 1
            if kind_run:
                why.append("Kind run"); score += 1
            blanks = blank_gws[n].get(r["team_id"], 0)
            doubles = double_gws[n].get(r["team_id"], 0)
            if blanks:
                why.append(f"{blanks} blank GW" + ("s" if blanks > 1 else "")); score -= 2 * blanks
            if doubles:
                why.append(f"{doubles} double GW" + ("s" if doubles > 1 else "")); score += 2 * doubles
            if r["intel_target"]:
                why.append("News backed"); score += 1
            if r["intel_fade"]:
                why.append("Fade signal"); score -= 1
            if r["doubt"]:
                why.append("Doubt")
            scored.append({
                "name": r["name"], "pos": r["pos"], "club": r["club"], "cost": r["cost"], "owned_pct": r["owned_pct"],
                "form": r["form"], "xgi_p90": r["xgi_p90"], "fdr": fdr, "score": score, "why": why,
            })
        scored.sort(key=lambda s: (-s["score"], -s["xgi_p90"], -s["form"]))
        out[str(n)] = {"horizon": n, "top": scored[:top_n]}

    return {"min_minutes": min_minutes, "top_n": top_n, "horizons": out}


def target_rival_entries(rows, team_id, limit_top=2, limit_bottom=0, spread=1):
    """Entry ids for the small, bounded set of rivals the Leagues tab actually
    compares against: the real competition (pick_contenders: nearest to you on
    points), the top of the table (limit_top), and whoever's within `spread`
    ranks of you either side — a superset of whatever build_tactics() ends up
    calling "first"/"second"/"contenders"/"neighbor_above"/"neighbor_below",
    so it doesn't need to duplicate that exact tie-break logic here. The
    bottom of the table (limit_bottom, off by default) used to be fetched too;
    a manager 100+ points back isn't competition."""
    sorted_rows = sorted(rows, key=lambda r: (r.get("rank") is None, r.get("rank") or 10**9))
    me_idx = next((i for i, r in enumerate(sorted_rows) if r.get("entry") == team_id), None)
    picked = list(sorted_rows[:limit_top]) + (list(sorted_rows[-limit_bottom:]) if limit_bottom else [])
    picked.extend(pick_contenders(rows, team_id))
    if me_idx is not None:
        lo, hi = max(0, me_idx - spread), min(len(sorted_rows), me_idx + spread + 1)
        picked.extend(sorted_rows[lo:hi])
    seen, out = set(), []
    for r in picked:
        eid = r.get("entry")
        if eid is None or eid == team_id or eid in seen:
            continue
        seen.add(eid)
        out.append(eid)
    return out




def rival_effective_ownership(picks_by_entry, my_entry):
    """True effective ownership among the RIVAL teams of a league (your own team left out): for each player the
    sum of FPL's pick multiplier over rival squads (0 benched, 1 starting, 2 captain, 3 triple captain), divided by
    the number of rival teams with picks. Returns ({id: eo %}, {id: rival teams owning him}, rival team count)."""
    mult, owners, n = {}, {}, 0
    for eid, pk in picks_by_entry.items():
        picks = (pk or {}).get("picks") or []
        if eid == my_entry or not picks:
            continue
        n += 1
        for p in picks:
            pid = p["element"]
            mult[pid] = mult.get(pid, 0) + int(p.get("multiplier") or 0)
            owners[pid] = owners.get(pid, 0) + 1
    eo = {pid: round(100 * m / n, 1) for pid, m in mult.items()} if n else {}
    return eo, owners, n


def rival_context(entries, last_fin_gw, my_last_gw_pts, member_squads_by_entry, elements, next_fixture_map, chip_windows=None):
    """Small, targeted extra fetches (season history only, no per-GW picks) for a
    bounded set of rivals: chips used this season, how much ground moved last GW,
    and — once picks are public — their squad's average fixture difficulty for
    the next GW. Only for the handful of rows the Leagues tab's comparisons
    actually use, not the whole league."""
    ctx = {}
    for eid in entries:
        try:
            h = get(f"https://fantasy.premierleague.com/api/entry/{eid}/history/")
        except Exception as e:
            _warn(f"rival_context: could not load history for entry {eid}: {e}")
            continue
        chips = {c["name"]: c["event"] for c in h.get("chips", [])}
        chips_left = None
        if chip_windows:
            events = {}
            for c in h.get("chips", []):
                events.setdefault(c["name"], []).append(c.get("event") or 0)
            chips_left = sorted(n for n, (a, b) in chip_windows.items() if not any(a <= ev <= b for ev in events.get(n, [])))
        gap_trend = None
        if my_last_gw_pts is not None and last_fin_gw is not None:
            row = next((r for r in h.get("current", []) if r.get("event") == last_fin_gw), None)
            if row and row.get("points") is not None:
                gap_trend = my_last_gw_pts - row["points"]
        fixture = None
        squad = member_squads_by_entry.get(eid)
        if squad and next_fixture_map:
            fdrs = []
            for p in squad.get("xi", []):
                el = elements.get(p.get("id"))
                info = next_fixture_map.get(el["team"]) if el else None
                if info and info.get("fdr") is not None:
                    fdrs.append(info["fdr"])
            if fdrs:
                avg = sum(fdrs) / len(fdrs)
                fixture = {"avg_fdr": round(avg, 1), "label": "Tough" if avg >= 3.6 else ("Easy" if avg <= 2.4 else "Mixed")}
        ctx[eid] = {"chips": chips, "chips_left": chips_left, "gap_trend": gap_trend, "fixture": fixture}
    return ctx


def _prefetch_picks(entries, gw, workers=6):
    """{entry id: picks payload} for many managers, fetched concurrently (they were one at a time,
    ~0.4 s each). Failures are warned about and left out, as the sequential loop did."""
    from concurrent.futures import ThreadPoolExecutor
    def one(entry):
        try:
            return entry, get(f"https://fantasy.premierleague.com/api/entry/{entry}/event/{gw}/picks/")
        except Exception as e:
            _warn(f"analyze_leagues: could not load picks for entry {entry}: {e}")
            return entry, None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(ex.map(one, list(entries)))

def analyze_leagues(boot, entry, team_id, picks_gw, deadline_passed=False, my_last_gw_pts=None, last_fin_gw=None, next_fixture_map=None):
    teams = {t["id"]: t for t in boot["teams"]}
    elements = {e["id"]: e for e in boot["elements"]}
    classic = entry.get("leagues", {}).get("classic") or []
    tracked_ids = TRACKED_BY_TEAM.get(team_id, TRACKED_LEAGUES)
    my_picks = set()
    my_squad = None
    try:
        my_pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
        my_picks = {p["element"] for p in my_pk.get("picks") or []}
        if deadline_passed and my_pk.get("picks"):
            my_squad = format_pick_squad(my_pk.get("picks"), elements, teams)
            my_squad["chip"] = my_pk.get("active_chip")
    except Exception as e:
        _warn(f"analyze_leagues: could not load own GW{picks_gw} picks: {e}")
    leagues = []
    # Full per-league ownership counts, keyed by league id — a transient,
    # not-serialized companion to `leagues` (below). build_tactics only ever
    # emits truncated top-8/10 lists (template/you_unique/they_share/
    # cap_last), so an arbitrary player not already in one of those has no
    # way to look up their real mini-league ownership; this lets a caller in
    # main() do that lookup for ANY player (e.g. the Injury tab's mini-league
    # section) without re-fetching every member's picks.
    counts_by_league = {}
    tracked = [x for x in classic if x.get("id") in tracked_ids]
    tracked.sort(key=lambda x: 0 if x.get("id") == 125784 else 1)
    for L in tracked:
        try:
            rows = (get(f"https://fantasy.premierleague.com/api/leagues-classic/{L['id']}/standings/?page_standings=1").get("standings") or {}).get("results") or []
        except Exception as e:
            _warn(f"analyze_leagues: could not load standings for league {L['id']}: {e}")
            continue
        table = [{"rank": r.get("rank"), "team": r.get("entry_name"), "pts": r.get("total"), "me": r.get("entry") == team_id, "entry": r.get("entry")} for r in rows[:15]]
        counts, n, owned_by, cap_by = {}, 0, {}, {}
        member_squads = []
        picks_available = 0
        if len(rows) >= 2:
            picks_by_entry = _prefetch_picks([r["entry"] for r in rows], picks_gw)
            for r in rows:
                pk = picks_by_entry.get(r["entry"])
                if pk is None:
                    continue
                picks = pk.get("picks") or []
                if not picks:
                    continue
                picks_available += 1
                n += 1
                eid = r.get("entry")
                owned = set()
                for p in picks:
                    pid = p["element"]
                    counts[pid] = counts.get(pid, 0) + 1
                    owned.add(pid)
                    if p.get("is_captain"):
                        cap_by[pid] = cap_by.get(pid, 0) + 1
                if eid is not None:
                    owned_by[eid] = owned
                if deadline_passed:
                    squad = format_pick_squad(picks, elements, teams)
                    squad.update({
                        "entry": eid,
                        "team": r.get("entry_name"),
                        "manager": r.get("player_name"),
                        "rank": r.get("rank"),
                        "pts": r.get("total"),
                        "me": eid == team_id,
                        "chip": pk.get("active_chip"),
                    })
                    member_squads.append(squad)
        # Adaptive, not a flat 40%/25%: in a 6-team league 40% is ~2 people, barely
        # a signal. Same scaling build_tactics() already uses for its own template.
        tmpl_thresh = max(3, (n + 1) // 2) if n else None
        diff_thresh = max(1, n // 4) if n else None
        template, diffs = [], []
        if n:
            for pid, c in sorted(counts.items(), key=lambda x: -x[1]):
                el = elements.get(pid)
                if not el: continue
                pct = round(100 * c / n)
                item = {"name": el["web_name"], "club": teams[el["team"]]["short_name"], "own": pct, "count": c, "n": n}
                if c >= tmpl_thresh and pid not in my_picks: template.append(item)
                if pid in my_picks and c <= diff_thresh: diffs.append(item)
        member_squads_by_entry = {s["entry"]: s for s in member_squads}
        target_entries = target_rival_entries(rows, team_id)
        rival_ctx = rival_context(target_entries, last_fin_gw, my_last_gw_pts, member_squads_by_entry, elements, next_fixture_map, current_half_chip_windows(boot)) if target_entries else {}
        tactics = build_tactics(rows, team_id, L, n, counts, owned_by, cap_by, my_picks, elements, teams, rival_ctx=rival_ctx)
        rival_eo, rival_owners, rival_n = rival_effective_ownership(
            {r["entry"]: picks_by_entry.get(r["entry"]) for r in rows} if len(rows) >= 2 else {}, team_id)
        counts_by_league[L["id"]] = {"counts": dict(counts), "cap_by": dict(cap_by), "n": n,
                                     "rival_eo": rival_eo, "rival_owners": rival_owners, "rival_n": rival_n}
        league_obj = {
            "id": L["id"],
            "name": L.get("name"),
            "rank": L.get("entry_rank"),
            "last_rank": L.get("entry_last_rank"),
            "size": len(rows),
            "table": table,
            "template": template[:8],
            "diffs": diffs[:8],
            "tactics": tactics,
            "picks_gw": picks_gw,
            "deadline_passed": bool(deadline_passed),
            "picks_unlocked": bool(deadline_passed and picks_available > 0),
        }
        if deadline_passed:
            # Prefer rank order for display
            member_squads.sort(key=lambda s: (s.get("rank") is None, s.get("rank") or 999))
            league_obj["member_squads"] = member_squads
            if picks_available == 0:
                league_obj["picks_note"] = "Picks unlock after deadline (API empty)."
        else:
            league_obj["picks_note"] = "Picks unlock after deadline."
        leagues.append(league_obj)
    overall_template, overall_diffs = [], []
    for el in boot["elements"]:
        sel = float(el.get("selected_by_percent") or 0)
        item = {"name": el["web_name"], "club": teams[el["team"]]["short_name"], "own": sel}
        if my_picks:
            if sel >= 25 and el["id"] not in my_picks: overall_template.append(item)
            if el["id"] in my_picks and sel <= 12: overall_diffs.append(item)
    overall_template.sort(key=lambda x: -x["own"])
    overall_diffs.sort(key=lambda x: x["own"])
    overall = next((L for L in classic if L.get("id") == 314), None)
    public = [{"id": 314, "name": "Overall", "rank": overall.get("entry_rank"), "last_rank": overall.get("entry_last_rank")}] if overall else []
    out = {
        "mini": leagues,
        "public": public,
        "overall_template": overall_template[:8],
        "overall_diffs": overall_diffs[:8],
        "picks_gw": picks_gw,
        "deadline_passed": bool(deadline_passed),
        "picks_unlocked": bool(deadline_passed),
        "_counts_by_league": counts_by_league,
    }
    if my_squad and deadline_passed:
        out["my_squad"] = {**my_squad, "entry": team_id, "me": True, "picks_gw": picks_gw}
    return out


def main(team_id=TEAM_ID, out_path=None):
    data_file = Path(out_path) if out_path else ROOT / "data.js"
    existing = {}
    if data_file.exists() and data_file.read_text().strip():
        raw = data_file.read_text(); s, e = raw.find("{"), raw.rfind("}")
        try:
            existing = json.loads(raw[s:e+1])
        except Exception as ex:
            # Starting from {} would silently wipe the carried state (AI team, track record, price trend):
            # stop instead and let the previous good file stay in place.
            raise RuntimeError(f"{data_file.name} exists but cannot be parsed ({ex}); refusing to rebuild it from scratch")
    health = {}

    def section(name, fn, *args, key=None, fallback=None, **kw):
        """Run one builder. If it raises, keep the previous value for that section (so one broken source cannot
        take the whole refresh down) and record it in data["_health"] so the failure is visible and check_data
        can fail the run."""
        key = key or name
        try:
            val = fn(*args, **kw)
            health[name] = {"ok": True}
            return val
        except Exception as ex:
            _warn(f"section '{name}' failed, keeping its previous value: {type(ex).__name__}: {ex}")
            prev = (existing.get("_health") or {}).get(name) or {}
            health[name] = {"ok": False, "error": f"{type(ex).__name__}: {str(ex)[:160]}", "since": prev.get("since") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
            return existing.get(key) if existing.get(key) is not None else fallback
    boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
    entry = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/")
    hist = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/history/")
    avg = {e["id"]: e.get("average_entry_score") for e in boot["events"]}
    # FPL's average for a gameweek keeps moving until the gameweek is finished AND its data checked. Only a
    # settled average may be cached: GW6's was cached at 37 mid-gameweek and never corrected (final: 58),
    # which made every "vs the field" figure for that week wrong.
    settled = {e["id"] for e in boot["events"] if e.get("finished") and e.get("data_checked")}
    field_avg = {}
    for k, v in (existing.get("field_avg_known") or {}).items():
        try:
            if int(k) in settled:
                field_avg[int(k)] = v  # JSON round-trip turns int GW keys into strings
        except (TypeError, ValueError):
            pass
    prev_price_trend = dict(existing.get("price_trend") or {})
    today_et = datetime.now(ET).strftime("%Y-%m-%d")
    # Club rest-days are the same for both Shaaland and Bacalhau — refresh.py
    # runs once per team per workflow invocation, so this lives in its own
    # cache file (not data.js/bacalhau-data.js's `existing`) shared across
    # both runs. Whichever team's run goes first pays the fetch cost; the second
    # reads what the first just wrote.
    recovery_cache_path = ROOT / "team_recovery_cache.json"
    try:
        recovery_cache = json.loads(recovery_cache_path.read_text())
    except Exception:
        recovery_cache = {}
    try:
        team_recovery = fixtures_external.get_team_recovery(boot, recovery_cache)
        if not isinstance(team_recovery, dict) or not isinstance(team_recovery.get("teams"), dict):
            raise ValueError(f"malformed recovery result: {type(team_recovery).__name__}")
    except Exception as e:
        _warn(f"main: team recovery unavailable, continuing without it: {e}")
        team_recovery = {"fetched_at": None, "teams": {}}
    recovery_cache["team_recovery"] = team_recovery
    recovery_cache_path.write_text(json.dumps(recovery_cache, indent=2))
    chips_used = chips_by_half(hist)
    gws = []
    for row in hist.get("current", []):
        gw = row["event"]
        # a settled gameweek always uses FPL's final average; one still being played shows the live figure uncached
        fa = (avg.get(gw) or field_avg.get(gw)) if gw in settled else (avg.get(gw) or None)
        if fa and gw in settled:
            field_avg[gw] = fa
        gws.append({"gw": gw, "points": row["points"], "bench": row["points_on_bench"], "transfers": row["event_transfers"], "hits": row["event_transfers_cost"], "rank": row["overall_rank"], "field_avg": fa, "delta": (row["points"] - fa) if fa else None, "chip": next((chip_base(n) for n, ev in chips_used.items() if ev == gw), None)})
    _teams_by_id0 = {t["id"]: t for t in boot["teams"]}
    data_odds = section("odds", setup_odds, boot, deadline_state(boot), _teams_by_id0, fallback={"matches": 0})
    inputs = model_inputs(boot, (team_recovery or {}).get("teams"))
    plan = build_plan(boot, team_id, hist, chips_used, inputs)
    ds = deadline_state(boot)
    live = build_live_value(boot, team_id, plan.get("squad_from_gw"), hist, entry, ds.get("locked_gw"))
    last_fin = max((e["id"] for e in boot["events"] if e.get("finished")), default=None)
    # After deadline: league picks for the locked GW. Before: ownership from provisional/latest squad GW.
    league_picks_gw = ds["locked_gw"] if ds["deadline_passed"] and ds["locked_gw"] else (plan.get("squad_from_gw") or last_fin)
    my_last_gw_pts = next((r["points"] for r in hist.get("current", []) if r.get("event") == last_fin), None)
    teams_by_id = {t["id"]: t for t in boot["teams"]}
    next_fixture_map = fixture_map(ds["next_gw"], teams_by_id) if ds["next_gw"] else None
    leagues = analyze_leagues(boot, entry, team_id, league_picks_gw, deadline_passed=bool(ds["deadline_passed"]),
                               my_last_gw_pts=my_last_gw_pts, last_fin_gw=last_fin, next_fixture_map=next_fixture_map)
    counts_by_league = leagues.pop("_counts_by_league", {})  # transient, not serialized into data.js
    caps = captain_audit(boot, team_id)
    data = existing or {}
    data["odds"] = data_odds
    if not (data_odds or {}).get("matches") and health.get("odds", {}).get("ok"):
        health["odds"] = {"ok": True, "empty": True, "note": (data_odds or {}).get("error") or "no priced matches"}
    def _model_accuracy():
        cal = json.loads((ROOT / "calibration.json").read_text())
        return {"fitted_on": cal["fitted_on"], "holdout": cal["holdout"], "generated": cal.get("generated"),
                "metrics": {k: cal["metrics"]["holdout"][k] for k in ("uncalibrated", "calibrated", "form_baseline")}}
    data["model_accuracy"] = section("model_accuracy", _model_accuracy, fallback={})
    # Recomputed every run rather than cached off `existing`: both only cover finished
    # GWs (whose points never change), so recomputing is cheap and safe, whereas a
    # "skip if already present" cache would silently freeze once a new GW finishes.
    data["transfers"] = section("transfers", lambda: add_roll_rows(build_transfers(boot, team_id), hist, chips_used, squad_changes_for_chips(team_id, hist)), fallback=[])
    data["bench_audit"] = section("bench_audit", build_bench_audit, boot, team_id, fallback={})
    data["captain_board"] = section("captain_board", build_captain_board, boot, team_id, fallback={})
    ft_rows, ft_next = free_transfer_ledger(hist or {})
    data["ft_ledger"] = {"rows": ft_rows, "next": ft_next, "next_gw": next((e["id"] for e in boot["events"] if not e.get("finished") and e["id"] > (ft_rows[-1]["gw"] if ft_rows else 0)), None)}
    data["chip_net"] = section("chip_net", build_chip_net, chips_used, caps, data["bench_audit"], boot, team_id, data["transfers"], gws, hist=hist, fallback={})
    data["fh_audit"] = section("fh_audit", build_fh_audit, boot, team_id, chips_used)
    data["strategy"] = section("strategy", build_strategy, boot, team_id, hist, gws, data["transfers"], plan.get("squad_from_gw"), fallback={})
    owned = {(r[1], r[2]) for r in (plan.get("rows") or [])}  # your squad as (name, club): scouting lists leave these out
    data["xg_signal"] = section("xg_signal", build_xg_signal, boot, team_id, plan.get("squad_from_gw"), exclude=owned, next_fixture_map=next_fixture_map, fallback={})
    data["volume_log"] = section("volume_log", lambda: update_volume_log(backfill_volume_log(data.get("volume_log"), boot, team_id), (data.get("xg_signal") or {}).get("imminent"), ds, boot), fallback={})
    data["defcon"] = section("defcon", build_defcon, boot, team_id, plan.get("squad_from_gw"), exclude=owned, fallback={})
    data["rotation_risk"] = section("rotation_risk", build_rotation_risk, boot, team_id, plan.get("squad_from_gw"), team_recovery=team_recovery.get("teams"), target_gw=team_recovery.get("target_gw"), fallback={})
    data["team_recovery"] = team_recovery
    # name -> position for every player (None where two players share a name in different positions): lets the
    # Plan tab's transfer advice only ever swap like for like
    _pos = {}
    for _e in boot["elements"]:
        _p = POS[_e["element_type"]]
        _pos[_e["web_name"]] = _p if _pos.get(_e["web_name"], _p) == _p else None
    data["pos_by_name"] = _pos
    # club short name -> FPL team code, for the Plan pitch view's shirt images
    data["team_codes"] = {t["short_name"]: t["code"] for t in boot["teams"] if t.get("code") is not None}
    data.pop("af_team_ids", None)  # left over from the removed API-Football code
    data["form_fdr"] = section("form_fdr", build_form_fdr, boot, next_fixture_map, exclude=owned, fallback={})
    data["value_board"] = section("value_board", build_value_board, boot, exclude=owned, fallback={})
    squad_names = {r[1] for r in (plan.get("rows") or [])}
    data["injury_watch"] = section("injury_watch", build_injury_watch, boot, squad_names=squad_names, squad_ids=set(plan.get("squad_ids") or []) or None, fallback={"rows": []})

    # Injury tab's mini-league section: a niche differential 6 of your 13
    # ESL teams all specifically picked being suddenly doubtful is a much
    # bigger deal to your actual competition than its low global ownership
    # would suggest — the global top-N list above would likely miss it
    # entirely. Same hardcoded-ESL-id convention as wc_top3 below.
    esl_counts_info = counts_by_league.get(125784) or {}
    # True EO among your RIVALS (your own team left out): pick multipliers from their latest locked squads, so a
    # benched pick counts 0, a starter 1, a captain 2 and a triple captain 3 (rival_effective_ownership).
    esl_n = esl_counts_info.get("rival_n")
    esl_eo = esl_counts_info.get("rival_eo") or {}
    esl_owners = esl_counts_info.get("rival_owners") or {}
    league_rows = []
    for r in data["injury_watch"].get("rows", []):
        c = esl_owners.get(r["id"])   # keyed on the player's id: two players can share a web_name
        if c:  # only players at least 1 rival owns — 0-owned is noise here
            league_rows.append({**r, "league_own": c, "league_eo": esl_eo.get(r["id"], 0.0)})
    league_rows.sort(key=lambda r: (-(r["league_eo"] or 0), -r["league_own"]))
    esl_league_obj = next((lg for lg in (leagues.get("mini") or []) if lg.get("id") == 125784), None)
    data["injury_watch"]["league"] = {
        "id": 125784, "name": (esl_league_obj or {}).get("name"), "n": esl_n,
        "top_n": 10, "rows": league_rows[:10],
    }

    data["transfer_targets"] = section("transfer_targets", build_transfer_targets, boot, team_id, plan.get("squad_from_gw"), fallback={})
    data["targets"] = section("targets", build_targets, boot, exclude=owned, fallback={"horizons": {}})

    # Wildcard tab's "who the room barely owns" shortlist: top Target-6 names,
    # excluding your current squad, preferring names this ESL league's table
    # barely owns (<=3, same threshold plan-intel.js already uses) — computed
    # once here so the Wildcard card and Price radar's decision-set filter
    # both reference the identical 3 names, not two independently-drifting lists.
    esl = next((lg for lg in (leagues.get("mini") or []) if lg.get("id") == 125784), None)
    tac = (esl or {}).get("tactics") or {}
    own_by_name = {}
    for u in (tac.get("template") or []) + (tac.get("you_unique") or []) + (tac.get("they_share") or []):
        own_by_name[u["name"]] = u["count"]
    h6_top = ((data["targets"].get("horizons") or {}).get("6") or {}).get("top") or []
    wc_candidates = [r for r in h6_top if r["name"] not in squad_names]
    wc_candidates.sort(key=lambda r: (0 if (own_by_name.get(r["name"]) is None or own_by_name.get(r["name"]) <= 3) else 1, -r["score"]))
    wc_top3 = [{**r, "esl_own": own_by_name.get(r["name"]), "esl_n": tac.get("n")} for r in wc_candidates[:3]]
    data["targets"]["wc_top3"] = wc_top3
    _by_key = {(e["web_name"], teams_by_id[e["team"]]["short_name"]): e["id"] for e in boot["elements"]}
    my_ids = {_by_key[(row[1], row[2])] for row in (plan.get("rows") or []) if (row[1], row[2]) in _by_key}
    data["set_pieces"] = section("set_pieces", build_set_pieces, boot, my_ids, fallback={"rows": []})
    data["news_players"] = section("news_players", build_news_players, boot, ds, teams_by_id, inputs, fpl_common.load_js_object(ROOT / "news.js"),
                                   [x["name"] for x in (tac.get("they_share") or [])], my_ids, fallback={})
    data["elite"] = section("elite", build_elite_ownership, boot, ds.get("locked_gw"), fallback={})
    _elite = data["elite"] or {}
    for _h in ((data["targets"].get("horizons") or {}).values()):
        for _r in _h.get("top") or []:
            _eid = _r.get("id") if _r.get("id") is not None else _by_key.get((_r.get("name"), _r.get("club")))
            if _elite.get("n") and _eid is not None:
                _r["elite_pct"] = round(100 * (_elite["own"].get(str(_eid)) or _elite["own"].get(_eid) or 0) / _elite["n"])

    watch_filename = "bacalhau-wildcard.js" if "bacalhau" in data_file.name else "shaaland-wildcard.js"
    watch = fpl_common.load_js_object(ROOT / watch_filename)
    watch_names = {p.get("name") for p in (watch.get("xi") or []) + (watch.get("bench") or []) if p.get("name")}
    watch_names |= {r["name"] for r in wc_top3}
    data["price_radar"] = section("price_radar", build_price_radar, boot, team_id, plan.get("squad_from_gw"), extra_names=watch_names, exclude=owned, fallback={"squad": [], "rising": [], "falling": [], "watch": []})
    trend_rows = (data["price_radar"].get("squad") or []) + (data["price_radar"].get("watch") or [])
    data["price_trend"] = build_price_trend(prev_price_trend, trend_rows, today_et)
    # --- everything below needs every signal above: news, elite ownership, price momentum, set pieces, rivals ---
    _mode = "chase"
    _rank = tac.get("you_rank")
    if _rank == 1 or (tac.get("gap_to_first") is not None and tac.get("gap_to_first") <= 0):
        _mode = "defend"
    elif _rank is not None and _rank > 3:
        _mode = "climb"
    _lc = counts_by_league.get(125784) or {}
    signals = section("transfer_signals", build_transfer_signals, boot, fpl_common.load_js_object(ROOT / "news.js"), data.get("elite"),
                      {"counts": _lc.get("counts") or {}, "n": _lc.get("n"), "mode": _mode}, data.get("set_pieces"), fallback={}) or {}
    data["elo_ratings"] = section("elo", lambda: __import__("elo").fetch_ratings(boot, cache_path=ROOT / "elo_cache.json").get("ratings") or {}, fallback={})
    if not data["elo_ratings"] and health.get("elo", {}).get("ok"):
        health["elo"] = {"ok": True, "empty": True, "note": "source returned no ratings"}      # optional source: honest, but not a failed run
    data["swing"] = section("swing", build_swing_data, boot, ds, teams_by_id, plan, data.get("elo_ratings"), fallback={})
    data["transfer_signals"] = {"mode": _mode, "players": len(signals)}
    try:
        enrich_with_model(data, boot, ds, teams_by_id, inputs, signals)
        health["enrich_model"] = {"ok": True}
    except Exception as e:
        _warn(f"enrich_with_model failed: {e}")
        health["enrich_model"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}", "since": ((existing.get("_health") or {}).get("enrich_model") or {}).get("since") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    def _predictions():
        import pred_track
        path = pred_track.log_path(data_file)
        plog = pred_track.grade(pred_track.load(path), boot, get, process=lambda a, b: __import__('understat').gw_process(boot, a, b))          # settle any finished gameweek first
        preds = build_predictions(boot, ds, teams_by_id, inputs, scale=pred_track.scales(plog))
        rows = preds.pop("_rows", [])
        if preds.get("gw"):
            picks = {c: [{k: p[k] for k in ("id", "team", "name", "club", "pos", "p", "raw", "fixture", "vol") if k in p} for p in preds.get(c, [])] for c in pred_track.CATS}
            # the Target tab's 1-GW top 10, saved beside the model's lists so the two can be graded the same way
            short = {t["id"]: t["short_name"] for t in boot["teams"]}
            ids = {(e["web_name"], short[e["team"]]): e["id"] for e in boot["elements"]}
            pool1 = [r for r in (((data.get("targets") or {}).get("pool") or {}).get("1") or []) if (r["name"], r["club"]) not in owned]
            tgt = (pool1 or ((((data.get("targets") or {}).get("horizons") or {}).get("1") or {}).get("top") or []))[:10]       # what the Target tab shows first
            picks["ap"] = [{k: x[k] for k in ("id", "name", "club", "pos", "ap", "fixture") if k in x} for x in preds.get("ap", [])]
            picks["rotation"] = [{k: x[k] for k in ("id", "team", "name", "club", "pos", "rotate", "fixture", "kind") if k in x} for x in preds.get("rotation", [])]
            picks[pred_track.TARGET] = [{"id": ids.get((t["name"], t["club"])), "name": t["name"], "club": t["club"], "pos": t.get("pos"), "score": t.get("score"), "xp": t.get("xp")} for t in tgt]
            pred_track.record(plog, preds["gw"], picks, datetime.now(timezone.utc))
            # per-player snapshot (inputs + chances + Target rank), the training data for tuning later
            trank = {(t["name"], t["club"]): (i + 1, t.get("score")) for i, t in enumerate(tgt)}
            pcols = []
            for r in rows:
                tr = trank.get((r["name"], r["club"]), (None, None))
                pcols.append([r["id"], r["team"], r["pos"], r["cost"], r["own"], r["form"], r["minutes"], round(r["xg90"], 2), round(r["xa90"], 2), r["fdr"], r["home"],
                              round(r["mp"], 2), round(r["avail"], 2), r.get("xp_raw", r["xp"]), round(r["goals"], 3), round(r["assists"], 3), round(r["goals"] + r["assists"], 3),
                              round(r["cs"], 3), round(r["defcon"], 3), tr[0], tr[1],
                              r["vol"]["shots"], r["vol"]["sot"], r["vol"]["big"], r["vol"]["cc"], r["vol"]["big_cc"], round(r.get("start_raw", r.get("start", 0)), 3)])
            pl = pred_track.load(pred_track.PLAYER_FILE)
            pred_track.player_record(pl, preds["gw"], pcols, datetime.now(timezone.utc))
            pred_track.player_grade(pl, boot, get)
            try:
                import learn
                preds["learning"] = learn.update(pl)           # compare the model's expected points with what happened; used from the next run
                _by = {e["id"]: e for e in boot["elements"]}
                _tm = {t["id"]: t["short_name"] for t in boot["teams"]}
                for _k in ("under", "over"):
                    for _m in ((preds["learning"].get("misses") or {}).get(_k) or []):
                        _e = _by.get(_m["id"]) or {}
                        _m["name"], _m["club"] = _e.get("web_name", "?"), _tm.get(_e.get("team"), "")
            except Exception as e:
                _warn(f"learn: {type(e).__name__}: {e}")
            pred_track.save(pred_track.PLAYER_FILE, pl)
            preds["snapshot"] = {"gw": preds["gw"], "players": len(pcols), "saved_gws": len(pl.get("gws") or {})}
        pred_track.save(path, plog)
        preds["record"] = pred_track.view(plog)
        leg = pred_track.grade_legacy(pred_track.load(pred_track.LEGACY_FILE), boot, get)     # earlier-method lists, graded once settled
        pred_track.save(pred_track.LEGACY_FILE, leg)
        preds["record"]["legacy"] = pred_track.legacy_view(leg, data.get("volume_log"))
        return preds
    data["predictions"] = section("predictions", _predictions, fallback={})
    data["ai_team"] = run_ai_team(data, boot, team_id, ds, chips_used, gws, teams_by_id, team_recovery.get("teams"), hist, inputs, signals)
    data["pred_log"] = section("pred_log", update_pred_log, data.get("pred_log"), ds, boot, plan, data.get("ai_team"), fallback={})
    data["planner"] = section("planner", run_planner, boot, team_id, ds, hist, chips_used, data.get("team") or {}, teams_by_id, inputs, signals, fallback={})
    _pl = data.get("planner") or {}
    if _pl.get("steps") and plan.get("transfer") is not None:
        # the Plan tab's transfer line is the model plan (all data the program has), not a separate rule
        _first = _pl["steps"][0]
        _mv = (_first.get("moves") or [])
        _follow = _pl.get("recommend") == "follow" and bool(_mv)
        _why = (f"Model plan for GW{_pl['gws'][0]}-{_pl['gws'][-1]}: " + ", ".join(f"{m['out']} -> {m['in']}" for m in _mv)
                + f" (+{_pl.get('gain')} expected points over rolling, of which {_pl.get('gain_extra')} from news, price, ownership and rivals)") if _follow else \
               f"Rolling is as good as any plan (best found {_pl.get('gain'):+} over rolling). Keep the free transfer."
        plan["transfer"].update({"action": "TRANSFER" if _follow else "ROLL", "reason": _why, "source": "planner",
                                 "move": ({"out": _mv[0]["out"], "inn": _mv[0]["in"]} if _follow else None)})
    try:
        _pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{plan.get('squad_from_gw')}/picks/") if plan.get("squad_from_gw") else {}
        data["daily_check"] = build_daily_check(data.get("daily_check"), boot, [p["element"] for p in _pk.get("picks", [])],
                                                (data.get("ai_team") or {}).get("plan"), data.get("rotation_risk"), datetime.now(timezone.utc))
        health["daily_check"] = {"ok": True}
    except Exception as e:
        _warn(f"daily_check failed: {e}")
        health["daily_check"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}", "since": ((existing.get("_health") or {}).get("daily_check") or {}).get("since") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    now = datetime.now(timezone.utc)
    data.update({
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "generated_at_et": fmt_generated_et(now),
        "timezone": "America/Toronto",
        "deadline": {
            "passed": ds["deadline_passed"],
            "locked_gw": ds["locked_gw"],
            "next_gw": ds["next_gw"],
            "intel_gw": ds["intel_gw"],
            "current_gw": ds["current_gw"],
            "picks_unlocked": ds["picks_unlocked"],
        },
        "team": {**(existing.get("team") or {}), "id": entry["id"], "name": entry["name"], "manager": f"{entry.get('player_first_name','')} {entry.get('player_last_name','')}".strip(), "overall_points": entry.get("summary_overall_points"), "overall_rank": entry.get("summary_overall_rank"), "bank": (live["bank"] if live else entry.get("last_deadline_bank", 0) / 10), "value": entry.get("last_deadline_value", 0) / 10, "live_value": (live["squad_value"] if live else entry.get("last_deadline_value", 0) / 10)},
        "history": hist.get("past", []),
        "chips_official": {k: chips_used.get(k) for k in CHIP_KEYS} | {k + "_h2": chips_used[k + "_h2"] for k in CHIP_KEYS if chips_used.get(k + "_h2")},
        "gameweeks": gws,
        "field_avg_known": field_avg,
        "plan": plan,
        "leagues": leagues,
        "captain_audit": caps,
    })
    # Decision log: freeze this gameweek's recommendation before the deadline, score finished ones (rec_log.py).
    # The committed rec_log*.json is the record; data.js only carries the page's view of it.
    try:
        import rec_log
        _rl_path = rec_log.log_path(data_file)
        _rl = rec_log.update(rec_log.load(_rl_path), data, boot, team_id, get)
        rec_log.save(_rl_path, _rl)
        data["decision_log"] = rec_log.view(_rl)
        health["decision_log"] = {"ok": True}
    except Exception as e:
        _warn(f"decision_log failed: {type(e).__name__}: {e}")
        health["decision_log"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}", "since": ((existing.get("_health") or {}).get("decision_log") or {}).get("since") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    data["_health"] = health
    tmp = data_file.with_name(data_file.name + ".tmp")
    tmp.write_text("window.FPL_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n")
    os.replace(tmp, data_file)          # never leave a half-written data file behind
    print("Updated", data_file.name, entry.get("name"), [u["gw"] for u in plan.get("upcoming", [])])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", type=int, default=TEAM_ID)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    main(args.team, args.out)

#!/usr/bin/env python3
"""Matchday snapshot, refreshed far more often than the full refresh: while a gameweek's matches are in play,
write live-data.js with your squad's live points (FPL's own live feed, provisional bonus included), who has
played and what is still to come. Does nothing (and writes nothing) when no match is in play, so the repo only
changes on match days. The browser cannot read FPL's API itself (no CORS), hence this server-side snapshot.

    python live_update.py          # writes live-data.js only if a gameweek is live"""
from __future__ import annotations
import json
import re, os, sys
from datetime import datetime, timezone
from pathlib import Path
from fplbase import ROOT, get, parse_deadline, POS, _warn
import ai_team

TEAMS = {"Shaaland": 1360999, "Bacalhau": 1360920}
OUT = ROOT / "live-data.js"
DATA_FILES = {"Shaaland": "data.js", "Bacalhau": "bacalhau-data.js"}


def live_gameweek(boot, fixtures, now):
    """The gameweek that is live: one with a match in play wins (so a new gameweek takes over from one that FPL has not settled
    yet); otherwise the first unsettled gameweek whose matches have started (every match over but FPL's checks not done: totals
    still move until then); else None."""
    cands = []
    for e in sorted(boot["events"], key=lambda e: e["id"]):
        if e.get("finished") and e.get("data_checked"):
            continue
        dl = parse_deadline(e.get("deadline_time"))
        if not dl or now < dl:
            break
        fx = [f for f in fixtures if f.get("event") == e["id"]]
        if any(f.get("started") for f in fx):
            cands.append((e["id"], any(f.get("started") and not (f.get("finished") or f.get("finished_provisional")) for f in fx)))
    playing = [g for g, on in cands if on]
    if playing:
        return max(playing)
    return cands[0][0] if cands else None


def team_snapshot(boot, team_id, gw, live, els):
    pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
    picks = sorted(pk.get("picks") or [], key=lambda p: p.get("position") or 99)
    if len(picks) != 15:
        return None
    plan = {"squad": [{"id": p["element"], "name": els[p["element"]]["web_name"], "pos": POS[els[p["element"]]["element_type"]]} for p in picks],
            "xi": [p["element"] for p in picks if p["position"] <= 11], "bench": [p["element"] for p in picks if p["position"] > 11],
            "captain": next(p["element"] for p in picks if p.get("is_captain")), "vice": next(p["element"] for p in picks if p.get("is_vice_captain")),
            "chip": "3xc" if pk.get("active_chip") == "3xc" else None, "hit_cost": (pk.get("entry_history") or {}).get("event_transfers_cost") or 0}
    return snapshot_plan(boot, plan, pk.get("active_chip"), live, els)


def snapshot_plan(boot, plan, chip, live, els):
    """Provisional points of a 15-man plan from FPL's live stats (the AI team's locked plan goes through here too)."""
    stats = {i: {"minutes": s.get("minutes", 0), "points": s.get("total_points", 0), "bonus": s.get("bonus", 0)} for i, s in live.items()}
    res = ai_team.score_plan(plan, stats, False)      # not final: no auto-subs or vice promotion until it is certain
    bench_boost = chip == "bboost"
    total = res["gross"] + (res["bench_pts"] if bench_boost else 0) - res["hits"]
    short = {t["id"]: t["short_name"] for t in boot["teams"]}
    lines = [{"id": l["id"], "name": l["name"], "pos": l["pos"], "club": short.get(els[l["id"]]["team"], ""), "pts": l["pts"], "mult": l["mult"], "played": l["played"],
              "bonus": stats.get(l["id"], {}).get("bonus", 0), "vice": l["id"] == plan["vice"]} for l in res["lines"]]
    bench = [{"id": i, "name": els[i]["web_name"], "pos": POS[els[i]["element_type"]], "club": short.get(els[i]["team"], ""), "pts": stats.get(i, {}).get("points", 0),
              "played": stats.get(i, {}).get("minutes", 0) > 0, "bonus": stats.get(i, {}).get("bonus", 0)} for i in plan["bench"]]
    return {"points": total, "gross": res["gross"], "hits": res["hits"], "captain": res["captain"], "chip": chip,
            "xi": lines, "bench": bench, "yet_to_play": sum(1 for l in lines if not l["played"])}


def entry_base(entry_id, gw):
    """Season points before this gameweek (FPL's own history, net of hits)."""
    if gw <= 1:
        return 0
    cur = get(f"https://fantasy.premierleague.com/api/entry/{entry_id}/history/").get("current") or []
    return next((c["total_points"] for c in cur if c["event"] == gw - 1), 0)


def h2h_live(boot, data, snap_me, gw, live, els, my_entry):
    """You against the AI team for the live gameweek: provisional points, season totals, and who only one side owns."""
    ai = data.get("ai_team") or {}
    plan = (ai.get("history") or {}).get(f"gw{gw}") or (ai.get("plan") if (ai.get("plan") or {}).get("gw") == gw else None)
    if not plan or not snap_me or not plan.get("xi"):
        return None
    sc = snapshot_plan(boot, {**plan, "hit_cost": plan.get("hit_cost") or 0}, plan.get("chip"), live, els)
    res_pts = ((plan.get("result") or {}).get("points")) or 0
    ai_base = (ai.get("season_points") or 0) - res_pts         # the stored season total already holds the provisional result
    me_base = entry_base(my_entry, gw)
    mine = {l["id"] for l in snap_me["xi"]}
    theirs = {l["id"] for l in sc["xi"]}
    only = lambda lines, other: [{"name": l["name"], "club": l["club"], "pts": l["pts"] * (l["mult"] or 1), "played": l["played"], "cap": (l["mult"] or 1) > 1}
                                 for l in lines if l["id"] not in other]
    return {"you": {"pts": snap_me["points"], "base": me_base, "total": me_base + snap_me["points"], "captain": snap_me["captain"], "yet": snap_me["yet_to_play"]},
            "ai": {"pts": sc["points"], "base": ai_base, "total": ai_base + sc["points"], "captain": sc["captain"], "yet": sc["yet_to_play"], "chip": plan.get("chip")},
            "only_you": only(snap_me["xi"], theirs), "only_ai": only(sc["xi"], mine), "same": len(mine & theirs)}


def leagues_live(boot, data, my_name, snap_me, my_entry, gw, live, els):
    """Each mini-league live: season points before the gameweek + every member's provisional points for it."""
    from concurrent.futures import ThreadPoolExecutor
    out = []
    for lg in (data.get("leagues") or {}).get("mini") or []:
        table = lg.get("table") or []
        def one(row):
            try:
                if row.get("entry") == my_entry:
                    snap, base = snap_me, entry_base(my_entry, gw)
                else:
                    snap, base = team_snapshot(boot, row["entry"], gw, live, els), entry_base(row["entry"], gw)
                if not snap:
                    return None
                return {"team": row["team"], "me": bool(row.get("me") or row.get("entry") == my_entry), "base": base, "pts": snap["points"], "total": base + snap["points"],
                        "yet": snap["yet_to_play"], "cap": snap["captain"]}
            except Exception as e:
                _warn(f"live: league member {row.get('entry')}: {e}")
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = [r for r in pool.map(one, table) if r]
        if len(rows) < 2:
            continue
        before = sorted(rows, key=lambda r: -r["base"])
        for i, r in enumerate(before):
            r["rank_before"] = 1 + sum(1 for x in rows if x["base"] > r["base"])
        for r in rows:
            r["rank"] = 1 + sum(1 for x in rows if x["total"] > r["total"])
        out.append({"id": lg.get("id"), "name": lg.get("name"), "size": lg.get("size"), "rows": sorted(rows, key=lambda r: (r["rank"], r["team"]))})
    return out


DEFCON_THR = {2: 10, 3: 12, 4: 12}


def _load(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def _data_js(name):
    try:
        raw = (ROOT / name).read_text()
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception:
        return {}


def pred_picks(gw, boot):
    """The predictions to follow live for this gameweek: the saved top-10s (prediction_log.json) when there are some, else the older
    saved lists (chance-volume goal / assist flags in data.js and the stored DEFCON top-10). Returns (source, {cat: [{id|team, name, club}]})."""
    log = (_load(ROOT / "prediction_log.json").get("gws") or {}).get(str(gw))
    if log and log.get("picks"):
        return "Top 10 predictions", {c: log["picks"].get(c, []) for c in ("goals", "assists", "gi", "ap", "defcon", "clean_sheets", "target", "rotation")}
    short = {t["id"]: t["short_name"] for t in boot["teams"]}
    by_key = {(e["web_name"], short[e["team"]]): e["id"] for e in boot["elements"]}
    picks = {"goals": [], "assists": [], "gi": [], "ap": [], "defcon": [], "clean_sheets": [], "target": []}
    for f in ((_data_js("data.js").get("volume_log") or {}).get(f"gw{gw}") or {}).get("flags", []):
        cat = "goals" if f.get("kind") == "goal" else "assists"
        picks[cat].append({"id": f.get("eid"), "name": f["name"], "club": f["club"]})
    for p in ((_load(ROOT / "legacy_predictions.json").get("gws") or {}).get(str(gw)) or {}).get("picks", []):
        eid = by_key.get((p["name"], p["club"]))
        if eid:
            picks["defcon"].append({"id": eid, "name": p["name"], "club": p["club"]})
    if not any(picks.values()):
        return None, {}
    return "Earlier method (saved before the deadline)", picks


def pred_live(gw, boot, live, fixtures, els):
    """Where each followed prediction stands right now: not started / in play / done, and what he has so far."""
    source, picks = pred_picks(gw, boot)
    if not source:
        return None
    def state(team):
        mine = [f for f in fixtures if team in (f["team_h"], f["team_a"])]
        if not mine:
            return "none", None
        if all(f.get("finished_provisional") or f.get("finished") for f in mine):
            return "done", mine
        if any(f.get("started") for f in mine):
            return "live", mine
        return "yet", mine
    out = {}
    for cat, lst in picks.items():
        rows = []
        for p in lst:
            if cat == "clean_sheets":
                team = p.get("team")
                st, mine = state(team)
                conceded = sum((f["team_a_score"] if f["team_h"] == team else f["team_h_score"]) or 0 for f in (mine or []))
                rows.append({"name": p.get("club"), "club": "", "state": st, "val": conceded, "need": 0, "hit": any(f.get("finished_provisional") or f.get("finished") for f in (mine or [])) and any(((f["team_a_score"] if f["team_h"] == team else f["team_h_score"]) or 0) == 0 and (f.get("finished_provisional") or f.get("finished")) for f in (mine or [])) or (st == "live" and len(mine or []) == 1 and conceded == 0),
                             "mins": max([f.get("minutes") or 0 for f in (mine or [])] or [0])})
                continue
            el = els.get(p.get("id")) or {}
            st, mine = state(el.get("team"))
            s = live.get(p.get("id")) or {}
            extra = {}
            if cat == "rotation":
                starts, m = int(s.get("starts") or 0), int(s.get("minutes") or 0)
                benched = st != "none" and starts == 0 and (st == "done" or (st == "live" and len(mine or []) == 1))                     # the match has begun and he is not in the starting XI
                short = st == "done" and starts == 1 and m < 60            # started but was off early
                rows.append({"name": p.get("name") or el.get("web_name"), "club": p.get("club", ""), "state": st, "val": 1 if (benched or short) else 0, "need": 1,
                             "hit": bool(benched or short), "mins": m, "starts": starts, "rot": p.get("rotate")})
                continue
            if cat in ("gi", "target", "ap"):
                g, a = int(s.get("goals_scored") or 0), int(s.get("assists") or 0)
                pts = g * {1: 6, 2: 6, 3: 5, 4: 4}.get(el.get("element_type"), 4) + a * 3
                val, need, extra = g + a, 1, {"g": g, "a": a, "pts": pts, "exp": p.get("ap")}
            elif cat == "goals":
                val, need = int(s.get("goals_scored") or 0), 1
            elif cat == "assists":
                val, need = int(s.get("assists") or 0), 1
            else:
                val, need = int(s.get("defensive_contribution") or 0), DEFCON_THR.get(el.get("element_type"), 12)
            rows.append({"name": p.get("name") or el.get("web_name"), "club": p.get("club", ""), "state": st, "val": val, "need": need,
                         "hit": val >= need, "mins": int(s.get("minutes") or 0), **extra})
        out[cat] = rows
    return {"source": source, "cats": out}


def main(argv):
    now = datetime.now(timezone.utc)
    boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
    fixtures = get("https://fantasy.premierleague.com/api/fixtures/")
    gw = int(argv[0]) if argv else live_gameweek(boot, fixtures, now)      # a gameweek number forces a snapshot (testing)
    out = Path(argv[1]) if len(argv) > 1 else OUT
    if gw is None:
        print("no gameweek in play; nothing written")
        return 0
    els = {e["id"]: e for e in boot["elements"]}
    live = {el["id"]: el["stats"] for el in get(f"https://fantasy.premierleague.com/api/event/{gw}/live/").get("elements", [])}
    fx = [f for f in fixtures if f.get("event") == gw]
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    games = [{"home": teams[f["team_h"]], "away": teams[f["team_a"]], "hs": f.get("team_h_score"), "as": f.get("team_a_score"),
              "minutes": f.get("minutes"), "started": bool(f.get("started")), "finished": bool(f.get("finished_provisional") or f.get("finished"))} for f in fx]
    snap = {"gw": gw, "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"), "games": games,
            "in_play": sum(1 for g in games if g["started"] and not g["finished"]), "teams": {}}
    try:
        snap["pred"] = pred_live(gw, boot, live, fx, els)
    except Exception as e:
        _warn(f"live: predictions: {e}")
    snap["h2h"], snap["leagues"] = {}, {}
    for name, tid in TEAMS.items():
        try:
            snap["teams"][name] = team_snapshot(boot, tid, gw, live, els)
        except Exception as e:
            _warn(f"live: {name}: {e}")
        data = _data_js(DATA_FILES[name])
        try:
            snap["h2h"][name] = h2h_live(boot, data, snap["teams"].get(name), gw, live, els, tid)
        except Exception as e:
            _warn(f"live: {name} head to head: {e}")
        try:
            snap["leagues"][name] = leagues_live(boot, data, name, snap["teams"].get(name), tid, gw, live, els)
        except Exception as e:
            _warn(f"live: {name} leagues: {e}")
    text = "window.FPL_LIVE = " + json.dumps(snap, separators=(",", ":")) + ";\n"
    try:    # nothing but the timestamp moved: do not write (the workflow would commit an identical snapshot every 10 minutes)
        strip = lambda t: re.sub(r'"generated_at":"[^"]*"', "", t)
        if out.exists() and strip(out.read_text()) == strip(text):
            print(f"live-data.js unchanged for GW{gw}")
            return 0
    except OSError:
        pass
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, out)
    print(f"live-data.js written for GW{gw}: {snap['in_play']} match(es) in play")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as ex:      # an FPL outage must not email a red run every 10 minutes: the next tick retries
        _warn(f"live_update: {ex}")
        sys.exit(0)

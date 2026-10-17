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


def live_gameweek(boot, fixtures, now):
    """The gameweek with a match in play or just finished but not yet settled, else None."""
    for e in sorted(boot["events"], key=lambda e: e["id"]):
        if e.get("finished") and e.get("data_checked"):
            continue
        dl = parse_deadline(e.get("deadline_time"))
        if not dl or now < dl:
            return None
        # the first unsettled gameweek is the live one if any of its matches has kicked off (including when every
        # match is over but FPL has not finished its checks: totals still move until then)
        return e["id"] if any(f.get("started") for f in fixtures if f.get("event") == e["id"]) else None
    return None


def team_snapshot(boot, team_id, gw, live, els):
    pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
    picks = sorted(pk.get("picks") or [], key=lambda p: p.get("position") or 99)
    if len(picks) != 15:
        return None
    plan = {"squad": [{"id": p["element"], "name": els[p["element"]]["web_name"], "pos": POS[els[p["element"]]["element_type"]]} for p in picks],
            "xi": [p["element"] for p in picks if p["position"] <= 11], "bench": [p["element"] for p in picks if p["position"] > 11],
            "captain": next(p["element"] for p in picks if p.get("is_captain")), "vice": next(p["element"] for p in picks if p.get("is_vice_captain")),
            "chip": "3xc" if pk.get("active_chip") == "3xc" else None, "hit_cost": (pk.get("entry_history") or {}).get("event_transfers_cost") or 0}
    stats = {i: {"minutes": s.get("minutes", 0), "points": s.get("total_points", 0), "bonus": s.get("bonus", 0)} for i, s in live.items()}
    res = ai_team.score_plan(plan, stats, False)      # not final: no auto-subs or vice promotion until it is certain
    chip = pk.get("active_chip")
    bench_boost = chip == "bboost"
    total = res["gross"] + (res["bench_pts"] if bench_boost else 0) - res["hits"]
    short = {t["id"]: t["short_name"] for t in boot["teams"]}
    lines = [{"id": l["id"], "name": l["name"], "pos": l["pos"], "club": short.get(els[l["id"]]["team"], ""), "pts": l["pts"], "mult": l["mult"], "played": l["played"],
              "bonus": stats[l["id"]]["bonus"], "vice": l["id"] == plan["vice"]} for l in res["lines"]]
    bench = [{"id": i, "name": els[i]["web_name"], "pos": POS[els[i]["element_type"]], "club": short.get(els[i]["team"], ""), "pts": stats[i]["points"],
              "played": stats[i]["minutes"] > 0, "bonus": stats[i]["bonus"]} for i in plan["bench"]]
    return {"points": total, "gross": res["gross"], "hits": res["hits"], "captain": res["captain"], "chip": chip,
            "xi": lines, "bench": bench, "yet_to_play": sum(1 for l in lines if not l["played"])}


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
                rows.append({"name": p.get("club"), "club": "", "state": st, "val": conceded, "need": 0, "hit": st != "yet" and conceded == 0,
                             "mins": max([f.get("minutes") or 0 for f in (mine or [])] or [0])})
                continue
            el = els.get(p.get("id")) or {}
            st, mine = state(el.get("team"))
            s = live.get(p.get("id")) or {}
            extra = {}
            if cat == "rotation":
                starts, m = int(s.get("starts") or 0), int(s.get("minutes") or 0)
                benched = st != "yet" and starts == 0                      # the match has begun and he is not in the starting XI
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
    for name, tid in TEAMS.items():
        try:
            snap["teams"][name] = team_snapshot(boot, tid, gw, live, els)
        except Exception as e:
            _warn(f"live: {name}: {e}")
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

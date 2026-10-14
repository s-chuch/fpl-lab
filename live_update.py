#!/usr/bin/env python3
"""Matchday snapshot, refreshed far more often than the full refresh: while a gameweek's matches are in play,
write live-data.js with your squad's live points (FPL's own live feed, provisional bonus included), who has
played and what is still to come. Does nothing (and writes nothing) when no match is in play, so the repo only
changes on match days. The browser cannot read FPL's API itself (no CORS), hence this server-side snapshot.

    python live_update.py          # writes live-data.js only if a gameweek is live"""
from __future__ import annotations
import json, os, sys
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
    lines = [{"name": l["name"], "pos": l["pos"], "pts": l["pts"], "mult": l["mult"], "played": l["played"], "bonus": stats[l["id"]]["bonus"]} for l in res["lines"]]
    bench = [{"name": els[i]["web_name"], "pts": stats[i]["points"], "played": stats[i]["minutes"] > 0} for i in plan["bench"]]
    return {"points": total, "gross": res["gross"], "hits": res["hits"], "captain": res["captain"], "chip": chip,
            "xi": lines, "bench": bench, "yet_to_play": sum(1 for l in lines if not l["played"])}


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
    for name, tid in TEAMS.items():
        try:
            snap["teams"][name] = team_snapshot(boot, tid, gw, live, els)
        except Exception as e:
            _warn(f"live: {name}: {e}")
    text = "window.FPL_LIVE = " + json.dumps(snap, separators=(",", ":")) + ";\n"
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, out)
    print(f"live-data.js written for GW{gw}: {snap['in_play']} match(es) in play")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

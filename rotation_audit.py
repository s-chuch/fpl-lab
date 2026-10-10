import json
import fpl_common
from fpl_common import get
boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
teams = {t["id"]: t["short_name"] for t in boot["teams"]}
els = {e["id"]: e for e in boot["elements"]}
fin = sorted(e["id"] for e in boot["events"] if e.get("finished"))
print("RESULT finished GWs:", fin, "| current/next:", [(e["id"], e.get("is_current"), e.get("is_next")) for e in boot["events"] if e.get("is_current") or e.get("is_next")])
gws = fin[-4:]
fx = {gw: get(f"https://fantasy.premierleague.com/api/fixtures/?event={gw}") for gw in gws}
live = {gw: {e["id"]: e["stats"] for e in get(f"https://fantasy.premierleague.com/api/event/{gw}/live/")["elements"]} for gw in gws}
for gw in gws:
    n = {}
    for f in fx[gw]:
        for t in (f["team_h"], f["team_a"]):
            n.setdefault(t, []).append(f)
    print("RESULT GW", gw, "fixtures", len(fx[gw]), "clubs with 0 fixtures:", sorted(teams[t] for t in teams if t not in n), "| clubs with 2:", sorted(teams[t] for t, v in n.items() if len(v) > 1), "| unfinished fixtures:", sum(1 for f in fx[gw] if not f.get("finished")))
# my squads
import re
for label, entry in (("Shaaland", 1360999), ("Bacalhau", 1360920)):
    pk = get(f"https://fantasy.premierleague.com/api/entry/{entry}/event/6/picks/")
    print("RESULT", label, "GW6 picks:")
    for p in pk["picks"]:
        e = els[p["element"]]
        row = []
        for gw in gws:
            nfx = sum(1 for f in fx[gw] if e["team"] in (f["team_h"], f["team_a"]))
            m = live[gw].get(e["id"], {}).get("minutes")
            row.append(f"GW{gw}:{m}min/{nfx}fx")
        print("RESULT   ", f'{e["web_name"]:12}', teams[e["team"]], p["position"], " ".join(row), "| status", e["status"], e.get("chance_of_playing_next_round"), (e.get("news") or "")[:40])

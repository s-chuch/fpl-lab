import json, os, collections
import fpl_common, fixtures_external as fx
key = os.environ["API_FOOTBALL_KEY"]
boot = fpl_common.get("https://fantasy.premierleague.com/api/bootstrap-static/")
print("RESULT fpl teams:", [(t["name"], t["short_name"]) for t in boot["teams"]])
for day in ("2026-09-28", "2026-09-29", "2026-09-30"):
    d = fx._af_get("/fixtures", {"date": day}, key)
    items = d.get("response") or []
    leagues = collections.Counter((i["league"]["country"], i["league"]["name"]) for i in items)
    print("RESULT", day, "leagues:", [k for k in leagues if k[0] in ("England", "World") or "Champions" in k[1] or "Europa" in k[1] or "Conference" in k[1]])
    for i in items:
        l = i["league"]
        if l["country"] == "England" or "Champions League" in l["name"] or "Europa" in l["name"]:
            print("RESULT  ", day, l["name"], "|", i["teams"]["home"]["name"], "v", i["teams"]["away"]["name"], i["fixture"]["status"]["short"])

import json, os
import fpl_common, fixtures_external as fx
boot = fpl_common.get("https://fantasy.premierleague.com/api/bootstrap-static/")
res = fx.get_team_recovery(os.environ["API_FOOTBALL_KEY"], boot, {})
print("RESULT clubs with any match in window:", len(res["log"]), "clubs with record:", len(res["teams"]))
for k, ms in res["log"].items():
    print("RESULT", k, [(m["date"][:16], m["competition"], m["opponent"], "FT" if m["finished"] else "sched") for m in ms])
for k, v in res["teams"].items():
    print("RESULT rec", k, json.dumps(v))

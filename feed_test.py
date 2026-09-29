import json
import fpl_common, fixtures_external as fx
boot = fpl_common.get("https://fantasy.premierleague.com/api/bootstrap-static/")
res = fx.get_team_recovery(boot, {})
print("RESULT clubs with record:", len(res["teams"]), "of", len(boot["teams"]))
for k, v in res["teams"].items():
    print("RESULT", k, json.dumps(v))

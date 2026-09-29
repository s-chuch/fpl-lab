"""One-off: run the worldfootball scrape for real and print per-club results (no commit)."""
import json, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import fpl_common, fixtures_external as fx
boot = fpl_common.get("https://fantasy.premierleague.com/api/bootstrap-static/")
today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
if len(sys.argv) > 1:  # quick mode: first N clubs
    boot = {"teams": boot["teams"][:int(sys.argv[1])]}
res = fx.get_team_recovery(boot, {}, today)
print("RESULT fetched_date", res["fetched_date"], "clubs with data", len(res["teams"]), "of", len(boot["teams"]))
for k, v in res["teams"].items():
    print("RESULT", k, json.dumps(v))

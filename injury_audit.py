import collections, re
import fpl_common
from refresh import player_availability
boot = fpl_common.get("https://fantasy.premierleague.com/api/bootstrap-static/")
teams = {t["id"]: t["short_name"] for t in boot["teams"]}
els = boot["elements"]
print("RESULT total players", len(els))
print("RESULT raw status letters:", dict(collections.Counter(e.get("status") for e in els)))
print("RESULT our kinds:", dict(collections.Counter(player_availability(e)["kind"] for e in els)))
# 1) status letters we do not handle explicitly (anything besides a/d/i/s/u)
odd = [e for e in els if e.get("status") not in ("a", "d", "i", "s", "u")]
print("RESULT unhandled status players:", len(odd), [(e["web_name"], teams[e["team"]], e.get("status"), e.get("chance_of_playing_next_round"), (e.get("news") or "")[:50]) for e in odd[:12]])
# 2) classified OK but the news text says otherwise
words = re.compile(r"injur|knock|hamstring|ankle|knee|calf|groin|illness|suspen|doubt|unavailable|fitness|surgery|ban|loan|left the club|transfer", re.I)
miss = [e for e in els if player_availability(e)["kind"] == "ok" and words.search(e.get("news") or "")]
print("RESULT classified OK but news mentions a problem:", len(miss))
for e in miss[:20]:
    print("RESULT   ", e["web_name"], teams[e["team"]], e.get("status"), e.get("chance_of_playing_next_round"), e.get("chance_of_playing_this_round"), "|", (e.get("news") or "")[:90], "|", e.get("news_added"))
# 3) flagged but news empty (possible stale flag)
noNews = [e for e in els if player_availability(e)["kind"] != "ok" and not (e.get("news") or "").strip()]
print("RESULT flagged with empty news:", len(noNews), [(e["web_name"], teams[e["team"]], e.get("status"), e.get("chance_of_playing_next_round")) for e in noNews[:10]])
# 4) 'out' because chance==0 but status a (our rule) and 'u' (unavailable)
print("RESULT out via status u:", sum(1 for e in els if e.get("status") == "u"), "| out via chance==0 only:", sum(1 for e in els if e.get("status") not in ("i", "s", "u") and e.get("chance_of_playing_next_round") == 0))
# 5) next-round vs this-round disagreement
dis = [e for e in els if e.get("chance_of_playing_next_round") is not None and e.get("chance_of_playing_this_round") is not None and e["chance_of_playing_next_round"] != e["chance_of_playing_this_round"]]
print("RESULT next vs this-round chance differ:", len(dis), [(e["web_name"], e["chance_of_playing_this_round"], e["chance_of_playing_next_round"]) for e in dis[:8]])
# 6) owned players that are out/doubt, top 12 with news
top = sorted([e for e in els if player_availability(e)["kind"] != "ok"], key=lambda e: -float(e.get("selected_by_percent") or 0))[:12]
for e in top:
    a = player_availability(e)
    print("RESULT TOP", e["web_name"], teams[e["team"]], a["label"], f'{e.get("selected_by_percent")}%', "|", (e.get("news") or "")[:80])
# 7) same web_name collisions among squads' players
c = collections.Counter(e["web_name"] for e in els); print("RESULT duplicate web_names:", sum(1 for v in c.values() if v > 1), [n for n, v in c.items() if v > 1][:12])

import json, os, urllib.request, urllib.error
def get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ShaalandFPLLab/1.0)", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return 0, str(e)[:200]
RANGE = "20260926-20261110"
for code in ("eng.1", "uefa.champions", "uefa.europa", "uefa.europa.conf", "eng.fa", "eng.league_cup"):
    st, d = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard?dates={RANGE}&limit=300")
    if st != 200 or not isinstance(d, dict):
        print("RESULT espn", code, "HTTP", st, str(d)[:120]); continue
    ev = d.get("events") or []
    print("RESULT espn", code, "HTTP", st, "events", len(ev))
    for e in ev[:4]:
        print("RESULT   ", e.get("date"), e.get("name"), (e.get("status") or {}).get("type", {}).get("name"))
st, d = get("https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/teams")
if st == 200:
    ts = [t["team"] for t in d["sports"][0]["leagues"][0]["teams"]]
    print("RESULT espn teams", len(ts), [(t["id"], t["displayName"]) for t in ts][:20])
    st2, s = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/teams/{ts[0]['id']}/schedule")
    print("RESULT espn team schedule", ts[0]["displayName"], "HTTP", st2, "events", len(s.get("events") or []) if isinstance(s, dict) else s)
    if isinstance(s, dict):
        for e in (s.get("events") or [])[:12]:
            print("RESULT   ", e.get("date"), e.get("name"), (e.get("league") or {}).get("name") or (e.get("seasonType") or {}).get("name"))
else:
    print("RESULT espn teams HTTP", st, d)
# football-data.org without a key (shows what is open at all)
st, d = get("https://api.football-data.org/v4/competitions/PL/matches?dateFrom=2026-09-26&dateTo=2026-10-10")
print("RESULT football-data PL nokey HTTP", st, (len(d.get("matches", [])) if isinstance(d, dict) else d))
st, d = get("https://api.football-data.org/v4/competitions/CL/matches?dateFrom=2026-09-26&dateTo=2026-10-10")
print("RESULT football-data CL nokey HTTP", st, (len(d.get("matches", [])) if isinstance(d, dict) else d))

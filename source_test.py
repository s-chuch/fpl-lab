import json, urllib.request, urllib.error
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
def get(url, extra=None):
    req = urllib.request.Request(url, headers={**UA, **(extra or {})})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)
def out(*a): print("RESULT", *a)
# fixturedownload slugs
for slug in ["epl-2026", "champions-league-2026", "europa-league-2026", "conference-league-2026", "fa-cup-2026", "efl-cup-2026", "league-cup-2026", "carabao-cup-2026", "uefa-europa-league-2026", "uefa-conference-league-2026", "europa-conference-league-2026"]:
    st, b = get(f"https://fixturedownload.com/feed/json/{slug}")
    if st == 200:
        try:
            d = json.loads(b); teams = sorted({m["HomeTeam"] for m in d})
            out("fixturedownload", slug, st, "matches", len(d), "teams", len(teams), teams[:40], "sample", json.dumps(d[0])[:230])
        except Exception as e:
            out("fixturedownload", slug, st, "nonjson", b[:80])
    else:
        out("fixturedownload", slug, st)
# UEFA official API
for name, cid in [("CL", 1), ("EL", 14), ("ECL", 2019)]:
    st, b = get(f"https://match.uefa.com/v5/matches?competitionId={cid}&fromDate=2026-09-20&toDate=2026-10-20&limit=100&offset=0&order=ASC", {"Origin": "https://www.uefa.com"})
    try:
        d = json.loads(b)
        out("uefa", name, st, "matches", len(d))
        for m in d[:3]:
            out("   ", m.get("kickOffTime", {}).get("dateTime"), m.get("homeTeam", {}).get("internationalName"), "v", m.get("awayTeam", {}).get("internationalName"), m.get("status"), m.get("round", {}).get("metaData", {}).get("name"))
    except Exception:
        out("uefa", name, st, b[:150])
# TheSportsDB
T = "https://www.thesportsdb.com/api/v1/json/3"
for label, url in [("team next Arsenal", f"{T}/eventsnext.php?id=133604"), ("team last Arsenal", f"{T}/eventslast.php?id=133604"), ("FA Cup next", f"{T}/eventsnextleague.php?id=4482"), ("EFL Cup next", f"{T}/eventsnextleague.php?id=4570"), ("season EPL", f"{T}/eventsseason.php?id=4328&s=2026-2027")]:
    st, b = get(url)
    try:
        d = json.loads(b); ev = d.get("events") or d.get("results") or []
        out("sportsdb", label, st, "events", len(ev), [(e.get("strTimestamp"), e.get("strLeague"), e.get("strEvent")) for e in ev[:6]])
    except Exception:
        out("sportsdb", label, st, b[:100])

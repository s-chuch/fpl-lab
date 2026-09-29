import json, urllib.request, urllib.error
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "application/json,text/plain,*/*"}
def probe(label, url, extra=None, show=170):
    req = urllib.request.Request(url, headers={**UA, **(extra or {})})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read().decode("utf-8", "replace"); st = r.status
    except urllib.error.HTTPError as e:
        st, body = e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        st, body = 0, str(e)
    print(f"RESULT [{st}] {label} len={len(body)} :: {' '.join(body[:show].split())}")
    return st, body
T = "https://www.thesportsdb.com/api/v1/json/3"
probe("sportsdb EPL next", f"{T}/eventsnextleague.php?id=4328")
probe("sportsdb CL next", f"{T}/eventsnextleague.php?id=4480")
probe("sportsdb Europa next", f"{T}/eventsnextleague.php?id=4481")
probe("sportsdb team next (Arsenal 133604)", f"{T}/eventsnext.php?id=133604")
probe("sportsdb team last (Arsenal)", f"{T}/eventslast.php?id=133604")
probe("sportsdb search leagues", f"{T}/search_all_leagues.php?c=England")
probe("fixturedownload epl", "https://fixturedownload.com/feed/json/epl-2026")
probe("fixturedownload cl", "https://fixturedownload.com/feed/json/champions-league-2026")
probe("openfootball england", "https://raw.githubusercontent.com/openfootball/england/master/2026-27/1-premierleague.txt")
probe("openfootball cl", "https://raw.githubusercontent.com/openfootball/champions-league/master/2026-27/cl.txt")
probe("uefa match api CL", "https://match.uefa.com/v5/matches?competitionId=1&seasonYear=2027&limit=5&offset=0&order=ASC", {"Origin": "https://www.uefa.com"})
probe("fotmob team Arsenal", "https://www.fotmob.com/api/teams?id=9825")
probe("espn core api", "https://sports.core.api.espn.com/v2/sports/soccer/leagues/eng.1/seasons/2026/types/1/events?limit=3")
probe("espn cdn schedule", "https://cdn.espn.com/core/soccer/schedule/_/date/20261003/league/eng.1?xhr=1")
probe("bbc", "https://web-cdn.api.bbci.co.uk/wc-poll-data/container/sport-data-scores-fixtures?selectedStartDate=2026-10-03&selectedEndDate=2026-10-10&todayDate=2026-09-29&urn=urn%3Abbc%3Asportsdata%3Afootball%3Atournament-collection%3Acollection&useSdApi=false")
probe("football-data.co.uk csv", "https://www.football-data.co.uk/fixtures.csv")
probe("wikipedia CL 2026-27", "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=2026%E2%80%9327+UEFA+Champions+League&format=json")
probe("fpl fixtures", "https://fantasy.premierleague.com/api/fixtures/?future=1", show=100)

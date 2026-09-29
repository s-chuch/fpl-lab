"""One-off: report what API-Football's free plan returns per endpoint (summary only)."""
import json, os, time, urllib.parse, urllib.request
KEY = os.environ["API_FOOTBALL_KEY"]
TESTS = [
    ("status", "/status", {}),
    ("league info", "/leagues", {"id": 39}),
    ("teams 2026", "/teams", {"league": 39, "season": 2026}),
    ("teams 2024", "/teams", {"league": 39, "season": 2024}),
    ("standings 2026", "/standings", {"league": 39, "season": 2026}),
    ("standings 2024", "/standings", {"league": 39, "season": 2024}),
    ("fixtures league 2026", "/fixtures", {"league": 39, "season": 2026}),
    ("fixtures league 2024", "/fixtures", {"league": 39, "season": 2024}),
    ("fixtures by date today", "/fixtures", {"date": "2026-09-29"}),
    ("fixtures by date 2026-10-03", "/fixtures", {"date": "2026-10-03"}),
    ("fixtures date range 2026", "/fixtures", {"team": 42, "from": "2026-09-20", "to": "2026-10-20"}),
    ("fixtures live", "/fixtures", {"live": "all"}),
    ("injuries 2026", "/injuries", {"league": 39, "season": 2026}),
    ("injuries 2024", "/injuries", {"league": 39, "season": 2024}),
    ("players 2026", "/players", {"team": 42, "season": 2026}),
    ("players 2024", "/players", {"team": 42, "season": 2024}),
    ("topscorers 2024", "/players/topscorers", {"league": 39, "season": 2024}),
    ("predictions", "/predictions", {"fixture": 1035037}),
    ("odds 2024", "/odds", {"league": 39, "season": 2024, "date": "2024-08-17"}),
    ("transfers", "/transfers", {"team": 42}),
    ("team statistics 2024", "/teams/statistics", {"league": 39, "season": 2024, "team": 42}),
]
for label, path, params in TESTS:
    time.sleep(7)  # stay under 10 req/min
    url = f"https://v3.football.api-sports.io{path}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"x-apisports-key": KEY})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        print(f"PROBE {label}: EXC {e}"); continue
    resp = d.get("response")
    n = len(resp) if isinstance(resp, (list, dict)) else resp
    sample = ""
    if isinstance(resp, list) and resp:
        sample = json.dumps(resp[0])[:180]
    elif isinstance(resp, dict):
        sample = json.dumps(resp)[:180]
    print(f"PROBE {label}: results={n} errors={json.dumps(d.get('errors'))[:160]} rateLimit={d.get('rateLimit')} sample={sample}")

import json, re, urllib.request, urllib.error
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)
def out(*a): print("RESULT", *a)
st, b = get("https://fixturedownload.com/")
out("fixturedownload home", st, len(b), sorted(set(re.findall(r'/(?:feed/json|download/csv|results)/([a-z0-9-]+)', b)))[:80])
st, b = get("https://fixturedownload.com/sport/football")
out("fixturedownload football", st, len(b), sorted(set(re.findall(r'/results/([a-z0-9-]+)', b)))[:120])
for slug in ["fa-cup-2026","fa-cup-2026-27","facup-2026","efl-cup-2026","efl-cup-2026-27","carabao-cup-2026","league-cup-2026","england-fa-cup-2026","england-league-cup-2026","efl-trophy-2026","championship-2026"]:
    st, b = get(f"https://fixturedownload.com/feed/json/{slug}"); out("fd", slug, st, len(b))
st, b = get("https://api.github.com/repos/openfootball/england/contents/2026-27")
try: out("openfootball england files", st, [f["name"] for f in json.loads(b)])
except Exception: out("openfootball england", st, b[:120])
st, b = get("https://api.github.com/repos/openfootball/england/contents/")
try: out("openfootball england root", st, [f["name"] for f in json.loads(b)][:40])
except Exception: out("of root", st, b[:120])
T = "https://www.thesportsdb.com/api/v1/json/3"
for lid, name in [(4482, "FA Cup"), (4570, "EFL Cup")]:
    for r in (1, 2, 3, 4):
        st, b = get(f"{T}/eventsround.php?id={lid}&r={r}&s=2026-2027")
        try:
            ev = json.loads(b).get("events") or []
            out("sportsdb", name, "round", r, st, "events", len(ev), [(e["strTimestamp"], e["strEvent"]) for e in ev[:4]])
        except Exception: out("sportsdb", name, "round", r, st, b[:80])
    st, b = get(f"{T}/eventsseason.php?id={lid}&s=2026-2027")
    try:
        ev = json.loads(b).get("events") or []; out("sportsdb", name, "season", st, "events", len(ev), [(e["strTimestamp"], e["strEvent"]) for e in ev[:4]])
    except Exception: out("sportsdb", name, "season", st, b[:80])
for title in ["2026–27_EFL_Cup", "2026–27_FA_Cup"]:
    st, b = get(f"https://en.wikipedia.org/w/api.php?action=parse&page={title}&prop=wikitext&format=json&redirects=1")
    try:
        w = json.loads(b)["parse"]["wikitext"]["*"]; out("wikipedia", title, st, len(w), "footballbox count", w.count("{{Football box"), "sample", ' '.join(w[w.find("{{Football box"):][:300].split()))
    except Exception: out("wikipedia", title, st, b[:100])

"""Club Elo ratings for the 20 Premier League clubs (free CSV API, no key).

Source: http://api.clubelo.com/<YYYY-MM-DD> returns every club's rating on that
date as CSV with header `Rank,Club,Country,Level,Elo,From,To`. Ratings are
mapped to FPL short names ("MCI", "TOT", ...) through a normalised-name map
(Club Elo writes "Man City", "Man United", "Forest", "Tottenham", ...).

Optional enrichment: every public function degrades to an empty result with an
"error" key rather than raising, so a Club Elo outage never breaks a refresh.

match_probs() is an APPROXIMATION: the win expectancy comes from the standard
Elo formula plus a home-advantage bonus; the draw share is a simple bell curve
in the rating gap (not fitted to this league), so treat it as a rough prior.
"""
from __future__ import annotations
import csv, io, json, os, re, sys, urllib.request
from datetime import date as _date, datetime, timedelta, timezone

BASE = "http://api.clubelo.com"
UA = "fpl-lab/1.0 (+https://github.com; elo.py)"
HFA = 65.0            # home advantage in Elo points
CACHE_HOURS = 12
DRAW_MAX = 0.28       # draw share between evenly matched sides (approximation)
DRAW_WIDTH = 450.0    # gap (Elo) at which the draw share falls to ~60% of max

# FPL short_name -> extra normalised Club Elo spellings (the normalised FPL
# name itself is always tried too).
ALIASES = {
    "MCI": ["mancity", "manchestercity"],
    "MUN": ["manunited", "manutd", "manchesterunited"],
    "TOT": ["tottenham", "spurs", "tottenhamhotspur"],
    "WOL": ["wolves", "wolverhampton", "wolverhamptonwanderers"],
    "NFO": ["forest", "nottmforest", "nottinghamforest"],
    "NEW": ["newcastle", "newcastleunited"],
    "LEE": ["leeds", "leedsunited"],
    "BHA": ["brighton", "brightonhovealbion"],
    "BOU": ["bournemouth", "afcbournemouth"],
    "WHU": ["westham", "westhamunited"],
    "CRY": ["crystalpalace", "palace"],
    "AVL": ["astonvilla", "villa"],
    "BUR": ["burnley"],
    "SUN": ["sunderland"],
    "COV": ["coventry", "coventrycity"],
    "HUL": ["hull", "hullcity"],
    "IPS": ["ipswich", "ipswichtown"],
    "LEI": ["leicester", "leicestercity"],
    "SOU": ["southampton"],
    "NOR": ["norwich", "norwichcity"],
    "SHU": ["sheffieldunited", "sheffutd"],
    "LUT": ["luton", "lutontown"],
}


def _log(msg):
    print(f"[elo.py] {msg}", file=sys.stdout, flush=True)


def norm(name):
    """Lower-case, strip accents' punctuation/spaces: "Nott'm Forest" -> "nottmforest"."""
    return re.sub(r"[^a-z]", "", str(name).lower())


def _keys_for(team):
    keys = {norm(team.get("name", "")), norm(team.get("short_name", ""))}
    keys.update(ALIASES.get(team.get("short_name"), []))
    keys.discard("")
    return keys


def parse_csv(text, on_date=None):
    """Parse Club Elo CSV -> list of dicts (club, country, elo). When `on_date`
    ('YYYY-MM-DD') is given, only rows whose From..To span contains it are kept
    (a date query already returns just those; this guards against history files).
    A club with several rows keeps the one with the latest From."""
    rows = {}
    for r in csv.DictReader(io.StringIO(text.strip())):
        try:
            club, elo = (r.get("Club") or "").strip(), float(r["Elo"])
        except (KeyError, TypeError, ValueError):
            continue
        frm, to = (r.get("From") or "").strip(), (r.get("To") or "").strip()
        if on_date and frm and to and not (frm <= on_date <= to):
            continue
        key = (club, (r.get("Country") or "").strip())
        cur = rows.get(key)
        if cur is None or frm >= cur["from"]:
            rows[key] = {"club": club, "country": (r.get("Country") or "").strip(),
                          "elo": elo, "from": frm}
    if not rows:
        raise ValueError("no rating rows in CSV")
    return list(rows.values())


def map_ratings(boot, rows):
    """Map parsed rows onto FPL short names -> (ratings, unmatched FPL names).
    English clubs win a name clash when the Country column is present."""
    by_key = {}
    for r in rows:
        k = norm(r["club"])
        if k not in by_key or (r["country"] == "ENG" and by_key[k]["country"] != "ENG"):
            by_key[k] = r
    ratings, unmatched = {}, []
    for t in boot.get("teams", []):
        hit = next((by_key[k] for k in sorted(_keys_for(t)) if k in by_key), None)
        if hit:
            ratings[t["short_name"]] = round(hit["elo"], 1)
        else:
            unmatched.append(t.get("name", t.get("short_name")))
    return ratings, unmatched


def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


def _now():
    return datetime.now(timezone.utc)


def cache_fresh(cache, day, now=None, hours=CACHE_HOURS):
    """True if `cache` holds ratings for `day` fetched within `hours`."""
    try:
        if not cache or not cache.get("ratings") or cache.get("date") != day:
            return False
        at = datetime.fromisoformat(cache["fetched_at"])
        return (now or _now()) - at < timedelta(hours=hours)
    except (KeyError, TypeError, ValueError):
        return False


def fetch_ratings(boot, date=None, getter=None, cache_path=None):
    """-> {"ratings": {short_name: elo}, "fetched_at", "date", "unmatched"}
    or {"ratings": {}, "error": "..."}; never raises. `getter(url)->text` is
    injectable for tests; `cache_path` is an optional JSON cache (12h)."""
    try:
        day = str(date or _date.today().isoformat())
        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    cache = json.load(f)
            except (OSError, ValueError):
                cache = None
            if cache_fresh(cache, day):
                _log(f"using cache from {cache['fetched_at']} ({len(cache['ratings'])} clubs)")
                return cache
        text = (getter or _http_get)(f"{BASE}/{day}")
        ratings, unmatched = map_ratings(boot, parse_csv(text, day))
        if not ratings:
            raise ValueError("no Premier League club matched")
        out = {"ratings": ratings, "fetched_at": _now().isoformat(timespec="seconds"),
               "date": day, "unmatched": unmatched}
        if unmatched:
            _log(f"no Club Elo match for: {', '.join(unmatched)} (add to ALIASES)")
        _log(f"{len(ratings)} clubs rated for {day}")
        if cache_path:
            try:
                tmp = cache_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(out, f, separators=(",", ":"))
                os.replace(tmp, cache_path)
            except OSError as e:
                _log(f"could not write cache: {e}")
        return out
    except Exception as e:  # noqa: BLE001 - optional enrichment must not raise
        _log(f"unavailable: {e}")
        return {"ratings": {}, "error": f"{type(e).__name__}: {e}"}


def match_probs(elo_home, elo_away, hfa=HFA):
    """Approximate win/draw/loss probabilities (sum to 1).

    Expected score E = 1/(1+10^(-(dr+hfa)/400)) is the standard Elo formula
    (win = 1, draw = 0.5). The draw share is a bell curve in the gap,
    d = DRAW_MAX * exp(-(gap/DRAW_WIDTH)^2), an approximation, not a fit. Then
    P(home) = E - d/2 and P(away) = 1 - E - d/2 so that P(home)+d/2 = E holds,
    clamped at zero and renormalised."""
    gap = float(elo_home) - float(elo_away) + hfa
    e = 1.0 / (1.0 + 10 ** (-gap / 400.0))
    d = DRAW_MAX * pow(2.718281828459045, -((gap / DRAW_WIDTH) ** 2))
    d = min(d, 2 * min(e, 1 - e))
    h, a = e - d / 2, 1 - e - d / 2
    tot = h + d + a
    return {"home": h / tot, "draw": d / tot, "away": a / tot}


def elo_gap(ratings, club, opp):
    """club's Elo minus opponent's (positive = club is stronger); None if either is unrated."""
    try:
        return float(ratings[club]) - float(ratings[opp])
    except (KeyError, TypeError, ValueError):
        return None

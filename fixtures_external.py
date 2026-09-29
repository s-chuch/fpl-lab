"""All-competition rest-days for each PL club, via API-Football (api-sports.io).

FPL's own API is Premier-League-only — no Champions League, Europa/Conference
League, or domestic cup fixtures exist in it anywhere — so "how many days'
rest did this club have before its next match" can't be answered from data
this app already fetches. This module fills that one gap from an external,
free-tier source, and nothing else: everything else about rotation risk
(minutes trend, FPL's own injury status, scraped news/X mentions) stays in
refresh.py's build_rotation_risk exactly as before.

Every function degrades to an empty/None result rather than raising when the
API key is missing, a request fails, or a club can't be matched — this is an
optional enrichment layered on top of a pipeline that must keep working
without it (same posture as this codebase's existing news-scrape fallbacks).

NOTE: the first live GitHub Actions run (2026-09-29) found that API-Football's
free tier rejects season-scoped current-season lookups (a /teams?league=&
season=2026 call came back "Free plans do not have access to this season, try
from 2022 to 2024."). Team identity is resolved via /teams?search=<name>
instead, which isn't season-scoped and isn't affected by that restriction.
If /fixtures calls ever hit the same wall, check the _warn lines in the
run's log — the fallback in that case is scraping worldfootball.net, which
was researched as a free, unlimited backstop when API-Football was chosen.
"""
from __future__ import annotations
import json, re, time, urllib.error, urllib.parse, urllib.request
import sys
from datetime import datetime, timezone

AF_BASE = "https://v3.football.api-sports.io"
USER_AGENT = "ShaalandFPLLab/1.0"

# Hand-maintained hints for clubs whose FPL `name` is unlikely to match
# API-Football's team name via plain normalization (abbreviated/traditional
# names on the FPL side). Keyed by FPL short_name; values are extra
# normalized-name candidates to try. Not exhaustive by design — an unmatched
# club is logged and simply excluded from recovery data for that run rather
# than guessed at.
NAME_HINTS = {
    "MUN": ["manchester united", "man united", "man utd"],
    "MCI": ["manchester city", "man city"],
    "TOT": ["tottenham", "tottenham hotspur", "spurs"],
    "WOL": ["wolverhampton", "wolverhampton wanderers", "wolves"],
    "NFO": ["nottingham forest", "nottm forest", "forest"],
    "NEW": ["newcastle", "newcastle united"],
    "WHU": ["west ham", "west ham united"],
    "BHA": ["brighton", "brighton hove albion", "brighton and hove albion"],
}


def _warn(msg):
    print(f"[fixtures_external.py] WARNING: {msg}", file=sys.stderr)


def _norm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(fc|afc)\b", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


RATE_LIMIT_PER_MIN = 10  # API-Football free tier's documented cap; confirmed live
_call_times = []


def _throttle():
    """Proactively pace calls to stay under the free tier's 10-req/min cap,
    rather than firing a burst and reacting to 429s after the fact — the
    first live run showed that reactive retries (short backoff) never
    actually clear a per-minute window, so every call after the 11th just
    kept failing for the rest of that run."""
    now = time.time()
    while _call_times and now - _call_times[0] > 60:
        _call_times.pop(0)
    if len(_call_times) >= RATE_LIMIT_PER_MIN:
        time.sleep(max(0, 60 - (now - _call_times[0]) + 0.5))
        now = time.time()
        while _call_times and now - _call_times[0] > 60:
            _call_times.pop(0)
    _call_times.append(time.time())


class _RateLimited(Exception):
    pass


def _af_get(path, params, api_key, timeout=20, retries=4):
    """A 429 shows up two ways from this API: an actual HTTP 429 status, or
    (confirmed live) an HTTP 200 whose JSON body is just
    {"rateLimit": "..."} — the latter looks like a valid empty response
    unless checked for explicitly, so it's treated as a retryable failure
    here rather than silently read as "no results"."""
    url = f"{AF_BASE}{path}?{urllib.parse.urlencode(params)}"
    last_err = None
    for attempt in range(retries):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"x-apisports-key": api_key, "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            if isinstance(data, dict) and data.get("rateLimit"):
                raise _RateLimited(data["rateLimit"])
            return data
        except urllib.error.HTTPError as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(61 if e.code == 429 else 2)
        except _RateLimited as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(61)
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2)
    raise last_err


def match_af_team(fpl_team, af_teams):
    """fpl_team: one of boot["teams"]. af_teams: [{"id":.., "name":..}, ...]
    from API-Football's /teams response. Tries an exact normalized-name
    match first, then this module's hand-maintained hints, then a loose
    substring match either direction — returns the API-Football team id, or
    None if nothing matches closely enough to trust."""
    candidates = [_norm(fpl_team.get("name"))]
    candidates += [_norm(h) for h in NAME_HINTS.get(fpl_team.get("short_name"), [])]
    candidates = [c for c in candidates if c]
    for af in af_teams:
        if _norm(af["name"]) in candidates:
            return af["id"]
    for af in af_teams:
        af_norm = _norm(af["name"])
        if af_norm and any(af_norm in c or c in af_norm for c in candidates):
            return af["id"]
    return None


def _search_af_team(api_key, query):
    """One /teams?search= lookup -> [{"id":.., "name":..}, ...]. This
    endpoint isn't season-scoped, unlike /teams?league=&season=, which
    API-Football's free tier rejects for the current season (confirmed
    live: 'Free plans do not have access to this season, try from 2022 to
    2024.') — team identity lookup doesn't need a season at all, so this
    sidesteps that restriction entirely."""
    try:
        resp = _af_get("/teams", {"search": query}, api_key)
    except Exception as e:
        _warn(f"_search_af_team({query!r}): request failed: {e}")
        return []
    out = []
    for item in (resp or {}).get("response") or []:
        t = (item or {}).get("team") or {}
        if t.get("id") and t.get("name"):
            out.append({"id": t["id"], "name": t["name"]})
    if not out and (resp or {}).get("errors"):
        _warn(f"_search_af_team({query!r}): {json.dumps(resp.get('errors'))[:200]}")
    return out


def fetch_af_team_ids(api_key, fpl_teams):
    """{fpl_short_name: api_football_team_id} for the given FPL team dicts
    (each one of boot["teams"]), resolved one /teams?search= call per club
    (plus a retry per NAME_HINTS candidate if the first search doesn't
    resolve). A club that still doesn't match is logged and simply left
    out — the caller decides whether to retry it later."""
    out = {}
    for t in fpl_teams:
        queries = [q for q in [t.get("name")] + NAME_HINTS.get(t.get("short_name"), []) if q]
        af_id = None
        for q in queries:
            candidates = _search_af_team(api_key, q)
            af_id = match_af_team(t, candidates) if candidates else None
            if af_id:
                break
        if af_id:
            out[t["short_name"]] = af_id
        else:
            _warn(f"fetch_af_team_ids: no API-Football match for {t.get('name')} ({t.get('short_name')})")
    return out


def get_af_team_ids(api_key, boot, existing):
    """Permanent (season-independent) id cache — a club's API-Football id
    never changes season to season, so this is resolved once per club and
    kept forever, unlike team_recovery's rest-days which are refetched
    daily. Only clubs missing from the cache (a new promotion, or a name
    that failed to match before) cost a request; a fully-populated cache
    costs zero."""
    cached = dict((existing or {}).get("af_team_ids") or {})
    if not api_key:
        return cached
    missing = [t for t in boot["teams"] if t["short_name"] not in cached]
    if not missing:
        return cached
    cached.update(fetch_af_team_ids(api_key, missing))
    return cached


def _first_fixture(resp):
    items = (resp or {}).get("response") or []
    return items[0] if items else None


def _fixture_info(fx, own_af_id=None):
    if not fx:
        return None
    raw_date = ((fx.get("fixture") or {}).get("date"))
    if not raw_date:
        return None
    try:
        date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
    except Exception:
        return None
    competition = ((fx.get("league") or {}).get("name")) or "?"
    opponent = None
    if own_af_id is not None:
        teams = fx.get("teams") or {}
        home, away = teams.get("home") or {}, teams.get("away") or {}
        opponent = away.get("name") if home.get("id") == own_af_id else home.get("name")
    return {"date": date, "date_str": date.strftime("%Y-%m-%d"), "competition": competition, "opponent": opponent}


def fetch_recovery_for_team(api_key, af_team_id):
    """Rest days between this club's most recent finished match (any
    competition) and its next scheduled one (any competition). Two API
    calls. Returns None on any failure so a single bad club can't take
    down the whole recovery build."""
    try:
        last_resp = _af_get("/fixtures", {"team": af_team_id, "last": 1, "status": "FT"}, api_key)
        next_resp = _af_get("/fixtures", {"team": af_team_id, "next": 1}, api_key)
    except Exception as e:
        _warn(f"fetch_recovery_for_team({af_team_id}): request failed: {e}")
        return None
    last_info = _fixture_info(_first_fixture(last_resp))
    next_info = _fixture_info(_first_fixture(next_resp), own_af_id=af_team_id)
    rest_days = None
    if last_info and next_info:
        rest_days = (next_info["date"].date() - last_info["date"].date()).days
    return {
        "rest_days": rest_days,
        "last_match": {"date": last_info["date_str"], "competition": last_info["competition"]} if last_info else None,
        "next_match": ({"date": next_info["date_str"], "competition": next_info["competition"], "opponent": next_info.get("opponent")} if next_info else None),
    }


def build_team_recovery(api_key, af_team_ids):
    """{fpl_short_name: recovery-record} for every club id given that
    returns usable fixture data. Empty dict (not an exception) if the key
    is missing or nothing resolves."""
    if not api_key:
        return {}
    out = {}
    for short_name, af_id in (af_team_ids or {}).items():
        info = fetch_recovery_for_team(api_key, af_id)
        if info:
            out[short_name] = info
    return out


def get_team_recovery(api_key, af_team_ids, existing, today_et):
    """Top-level entry point for refresh.py's main(). Caches by ET calendar
    date so the ~40-request fetch (20 clubs x 2 calls) happens once a day
    no matter how many times the refresh workflow fires — the free tier is
    ~100 requests/day and rest-days barely changes within a day anyway.
    Takes an already-resolved af_team_ids map (see get_af_team_ids) rather
    than resolving ids itself, since those are cached separately and
    permanently."""
    prev = (existing or {}).get("team_recovery") or {}
    if prev.get("fetched_date") == today_et:
        return prev
    if not api_key:
        return prev if prev else {"fetched_date": None, "teams": {}}
    return {"fetched_date": today_et, "teams": build_team_recovery(api_key, af_team_ids)}

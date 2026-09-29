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

NOTE: this module's request/response handling was written from provider-doc
research, not a live test call — this sandbox has no network path to
api-sports.io to hand-verify it, and the API key lives only in the project's
GitHub secret. The first real GitHub Actions run after this ships is the
actual verification point (see the "recovery period" plan). If team_recovery
comes back all-null, check the _warn lines in that run's log for the raw
response shape and adjust the field lookups below.
"""
from __future__ import annotations
import json, re, time, urllib.error, urllib.parse, urllib.request
import sys
from datetime import datetime, timezone

AF_BASE = "https://v3.football.api-sports.io"
PL_LEAGUE_ID = 39
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


def _af_get(path, params, api_key, timeout=20, retries=3, backoff=1.5):
    url = f"{AF_BASE}{path}?{urllib.parse.urlencode(params)}"
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"x-apisports-key": api_key, "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff ** attempt)
    raise last_err


def current_af_season(today=None):
    """PL season label API-Football expects: the year the season started
    (e.g. 2026 for the 2026-27 season). No network call needed — derived
    from today's date, since the PL season always runs roughly Aug-May."""
    d = today or datetime.now(timezone.utc)
    return d.year if d.month >= 7 else d.year - 1


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


def fetch_af_team_ids(api_key, boot, season=None):
    """{fpl_short_name: api_football_team_id} for every PL club that
    matches. One API call total."""
    season = season or current_af_season()
    try:
        resp = _af_get("/teams", {"league": PL_LEAGUE_ID, "season": season}, api_key)
    except Exception as e:
        _warn(f"fetch_af_team_ids: request failed: {e}")
        return {}
    af_teams = []
    for item in (resp or {}).get("response") or []:
        t = (item or {}).get("team") or {}
        if t.get("id") and t.get("name"):
            af_teams.append({"id": t["id"], "name": t["name"]})
    if not af_teams:
        _warn(f"fetch_af_team_ids: no teams in response — check API key/season/shape: {json.dumps(resp)[:300]}")
        return {}
    out = {}
    for t in boot["teams"]:
        af_id = match_af_team(t, af_teams)
        if af_id:
            out[t["short_name"]] = af_id
        else:
            _warn(f"fetch_af_team_ids: no API-Football match for {t.get('name')} ({t.get('short_name')})")
    return out


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


def build_team_recovery(api_key, boot):
    """{fpl_short_name: recovery-record} for every club that resolves and
    returns usable fixture data. Empty dict (not an exception) if the key
    is missing or nothing resolves."""
    if not api_key:
        return {}
    team_ids = fetch_af_team_ids(api_key, boot)
    out = {}
    for short_name, af_id in team_ids.items():
        info = fetch_recovery_for_team(api_key, af_id)
        if info:
            out[short_name] = info
    return out


def get_team_recovery(api_key, boot, existing, today_et):
    """Top-level entry point for refresh.py's main(). Caches by ET calendar
    date so the ~40-request fetch (20 clubs x 2 calls) happens once a day
    no matter how many times the refresh workflow fires — the free tier is
    ~100 requests/day and rest-days barely changes within a day anyway."""
    prev = (existing or {}).get("team_recovery") or {}
    if prev.get("fetched_date") == today_et:
        return prev
    if not api_key:
        return prev if prev else {"fetched_date": None, "teams": {}}
    return {"fetched_date": today_et, "teams": build_team_recovery(api_key, boot)}

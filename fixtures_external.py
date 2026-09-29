"""All-competition club activity for the Rotations tab's Rest column, via API-Football's free plan.

FPL's own API is Premier-League-only — no Champions League, Europa/Conference
League, or domestic cup fixtures exist in it — so "how many days' rest does
this club have before its next match" can't be answered from data this app
already fetches.

What the free plan actually allows (probed live 2026-09-29): no `last`/`next`
params, no current-season queries, but `/fixtures?date=D` works for yesterday,
today and tomorrow only, across every competition. So each run fetches those 3
dates, keeps every Premier League club's matches in a rolling log in
team_recovery_cache.json, and derives rest-days from that log: the next
unfinished match (visible up to a day ahead) minus the latest finished match
seen. Rest-days is None until the log holds both, i.e. for a club's first few
days of history or when its next match is more than a day away.

Every function degrades to an empty/None result rather than raising when the
key is missing or a request fails — this is optional enrichment on a pipeline
that must keep working without it.
"""
from __future__ import annotations
import json, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

AF_BASE = "https://v3.football.api-sports.io"
USER_AGENT = "ShaalandFPLLab/1.0"
REFETCH_MINUTES = 90   # statuses change during the day; refetch at most this often
KEEP_DAYS = 14         # rolling match-log retention
FINISHED = {"FT", "AET", "PEN"}
DEAD = {"PST", "CANC", "ABD", "AWD", "WO", "SUSP"}  # never going to be played as scheduled

# FPL short_name -> extra API-Football name candidates where FPL's own `name`
# won't equal API-Football's after normalization. Matching is exact-only:
# a loose match would pair "Newcastle" with Newcastle Jets etc. in a
# worldwide fixtures list.
NAME_HINTS = {
    "MUN": ["Manchester United"], "MCI": ["Manchester City"],
    "TOT": ["Tottenham", "Tottenham Hotspur"], "WOL": ["Wolves", "Wolverhampton Wanderers"],
    "NFO": ["Nottingham Forest"], "NEW": ["Newcastle", "Newcastle United"],
    "WHU": ["West Ham", "West Ham United"], "BHA": ["Brighton", "Brighton & Hove Albion"],
    "LEE": ["Leeds", "Leeds United"], "AVL": ["Aston Villa"], "CRY": ["Crystal Palace"],
    "BOU": ["Bournemouth"], "SUN": ["Sunderland"], "BRE": ["Brentford"],
}


def _warn(msg):
    print(f"[fixtures_external.py] WARNING: {msg}", file=sys.stderr)


def _norm(s):
    s = re.sub(r"\b(fc|afc)\b", "", (s or "").lower())
    return re.sub(r"[^a-z0-9]", "", s)


def build_name_index(fpl_teams):
    """{normalized API-Football name: fpl short_name}."""
    idx = {}
    for t in fpl_teams:
        for n in [t.get("name")] + NAME_HINTS.get(t.get("short_name"), []):
            if _norm(n):
                idx.setdefault(_norm(n), t["short_name"])
    return idx


def _af_get(path, params, api_key, timeout=20, retries=2):
    url = f"{AF_BASE}{path}?{urllib.parse.urlencode(params)}"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"x-apisports-key": api_key, "User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            if isinstance(data, dict) and data.get("rateLimit"):
                raise OSError(f"rate limited: {data['rateLimit']}")
            return data
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(20)
    raise last


def matches_from_response(resp, name_index):
    """[(short_name, match-dict), ...] for every PL club appearing in an
    API-Football /fixtures response (one entry per club per fixture)."""
    out = []
    for item in (resp or {}).get("response") or []:
        fx, lg, tm = item.get("fixture") or {}, item.get("league") or {}, item.get("teams") or {}
        raw = fx.get("date")
        status = (fx.get("status") or {}).get("short")
        if not raw or status in DEAD:
            continue
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        home, away = tm.get("home") or {}, tm.get("away") or {}
        for me, opp in ((home, away), (away, home)):
            sn = name_index.get(_norm(me.get("name")))
            if sn:
                out.append((sn, {"fixture_id": fx.get("id"), "date": when.isoformat(), "finished": status in FINISHED,
                                 "competition": lg.get("name") or "?", "opponent": opp.get("name")}))
    return out


def merge_log(log, new_matches, now):
    """Fold (short_name, match) pairs into the per-club rolling log, keyed by
    fixture id so a later fetch updates a match's finished flag; drops
    entries older than KEEP_DAYS."""
    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
    out = {k: {m["fixture_id"]: m for m in v if m.get("date", "") >= cutoff} for k, v in (log or {}).items()}
    for sn, m in new_matches:
        out.setdefault(sn, {})[m["fixture_id"]] = m
    return {k: sorted(v.values(), key=lambda m: m["date"]) for k, v in out.items()}


def recovery_from_log(matches, now):
    """Rest-days record for one club from its match log: next = earliest
    unfinished match from now on, last = latest finished match before it."""
    nxt = next((m for m in matches if not m["finished"] and m["date"][:10] >= now.date().isoformat()), None)
    before = [m for m in matches if m["finished"] and (not nxt or m["date"] < nxt["date"])]
    last = before[-1] if before else None
    if not nxt and not last:
        return None
    rest = None
    if nxt and last:
        rest = (datetime.fromisoformat(nxt["date"]).date() - datetime.fromisoformat(last["date"]).date()).days
    return {
        "rest_days": rest,
        "last_match": {"date": last["date"][:10], "competition": last["competition"]} if last else None,
        "next_match": ({"date": nxt["date"][:10], "competition": nxt["competition"], "opponent": nxt["opponent"]} if nxt else None),
    }


def get_team_recovery(api_key, boot, existing, now=None):
    """Entry point for refresh.py's main(). Returns the cache's
    {"fetched_at", "log", "teams"}; refetches yesterday/today/tomorrow only
    if the last fetch is older than REFETCH_MINUTES, so the two refresh.py
    runs per workflow (and repeat workflow runs) cost nothing extra."""
    now = now or datetime.now(timezone.utc)
    prev = (existing or {}).get("team_recovery") or {}
    if not api_key:
        return prev or {"fetched_at": None, "log": {}, "teams": {}}
    try:
        if prev.get("fetched_at") and now - datetime.fromisoformat(prev["fetched_at"]) < timedelta(minutes=REFETCH_MINUTES):
            return prev
    except ValueError:
        pass
    idx = build_name_index(boot["teams"])
    new, ok = [], 0
    for delta in (-1, 0, 1):
        day = (now + timedelta(days=delta)).date().isoformat()
        try:
            resp = _af_get("/fixtures", {"date": day}, api_key)
        except Exception as e:
            _warn(f"/fixtures?date={day} failed: {e}")
            continue
        if (resp or {}).get("errors"):
            _warn(f"/fixtures?date={day}: {json.dumps(resp['errors'])[:200]}")
            continue
        ok += 1
        got = matches_from_response(resp, idx)
        print(f"[fixtures_external.py] {day}: {len((resp or {}).get('response') or [])} fixtures, {len(got)} PL-club matches", file=sys.stderr)
        new += got
    if not ok:
        return prev or {"fetched_at": None, "log": {}, "teams": {}}
    log = merge_log(prev.get("log"), new, now)
    teams = {sn: r for sn, r in ((sn, recovery_from_log(ms, now)) for sn, ms in log.items()) if r}
    return {"fetched_at": now.isoformat(), "log": log, "teams": teams}

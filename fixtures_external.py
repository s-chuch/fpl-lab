"""All-competition rest-days for each PL club, from fixturedownload.com's free JSON feeds.

FPL's own API is Premier-League-only — no Champions League, Europa/Conference
League fixtures exist in it — so "how many days' rest does this club have
before its next match" can't be answered from data this app already fetches.
This module fills that gap and nothing else: everything else about rotation
risk stays in refresh.py's build_rotation_risk.

Source (found by testing several free options from GitHub Actions on
2026-09-29): fixturedownload.com/feed/json/<competition>-<year> serves the whole
season as static JSON — no key, not blocked from GitHub's servers, scores
included once played. Used: epl, champions-league, europa-league,
conference-league. NOT covered: the FA Cup and EFL Cup (no feed found), so a
cup midweek game is invisible here. API-Football's free plan, worldfootball.net,
ESPN and football-data.org were all ruled out (plan-blocked / 403 from Actions).

Feed club names mostly match FPL's own team names ("Man City", "Spurs",
"Nott'm Forest"); matching is exact-normalized only, plus NAME_HINTS. Any FPL
club with no match in the Premier League feed is logged, so a rename shows up
in the Actions log instead of silently dropping that club.

Every function degrades to an empty/None result rather than raising when a feed
can't be fetched — this is optional enrichment on a pipeline that must keep
working without it.
"""
from __future__ import annotations
import json, re, sys, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

FEED_BASE = "https://fixturedownload.com/feed/json"
FEEDS = [("Premier League", "epl"), ("Champions League", "champions-league"),
         ("Europa League", "europa-league"), ("Conference League", "conference-league")]
USER_AGENT = "Mozilla/5.0 (compatible; ShaalandFPLLab/1.0)"
REFETCH_MINUTES = 60  # feeds update as results land; also dedupes the two refresh.py runs per workflow

# FPL short_name -> extra names the feed might use, beyond FPL's own `name`.
NAME_HINTS = {
    "MUN": ["Manchester United", "Man United"], "MCI": ["Manchester City"],
    "TOT": ["Tottenham", "Tottenham Hotspur"], "WOL": ["Wolves", "Wolverhampton Wanderers"],
    "NFO": ["Nottingham Forest", "Nott'm Forest"], "NEW": ["Newcastle United"],
    "WHU": ["West Ham", "West Ham United"], "BHA": ["Brighton & Hove Albion"],
    "LEE": ["Leeds United"], "COV": ["Coventry City"], "HUL": ["Hull City"], "IPS": ["Ipswich Town"],
}


def _warn(msg):
    print(f"[fixtures_external.py] WARNING: {msg}", file=sys.stderr)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(fc|afc)\b", "", (s or "").lower()))


def build_name_index(fpl_teams):
    idx = {}
    for t in fpl_teams:
        for n in [t.get("name")] + NAME_HINTS.get(t.get("short_name"), []):
            if _norm(n):
                idx.setdefault(_norm(n), t["short_name"])
    return idx


def season_year(now):
    """Feeds are named by the year the season starts (2026 for 2026/27)."""
    return now.year if now.month >= 7 else now.year - 1


def _fetch_feed(slug, year, timeout=25):
    req = urllib.request.Request(f"{FEED_BASE}/{slug}-{year}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def matches_from_feed(rows, competition, name_index):
    """[(short_name, match-dict), ...] — one entry per PL club per row."""
    out = []
    for r in rows or []:
        try:
            when = datetime.strptime(r["DateUtc"].replace("Z", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError, AttributeError):
            continue
        played = r.get("HomeTeamScore") is not None and r.get("AwayTeamScore") is not None
        for me, opp in ((r.get("HomeTeam"), r.get("AwayTeam")), (r.get("AwayTeam"), r.get("HomeTeam"))):
            sn = name_index.get(_norm(me))
            if sn:
                out.append((sn, {"date": when, "competition": competition, "opponent": opp, "played": played}))
    return out


def recovery_from_matches(matches, now):
    """Rest-days record for one club: last = latest played match, next =
    earliest unplayed match still to come (a kickoff already past with no
    score is treated as in-progress and ignored)."""
    played = [m for m in matches if m["played"]]
    upcoming = [m for m in matches if not m["played"] and m["date"] >= now]
    last = max(played, key=lambda m: m["date"]) if played else None
    nxt = min(upcoming, key=lambda m: m["date"]) if upcoming else None
    if not last and not nxt:
        return None
    return {
        "rest_days": (nxt["date"].date() - last["date"].date()).days if last and nxt else None,
        "last_match": {"date": last["date"].strftime("%Y-%m-%d"), "competition": last["competition"]} if last else None,
        "next_match": ({"date": nxt["date"].strftime("%Y-%m-%d"), "competition": nxt["competition"], "opponent": nxt["opponent"]} if nxt else None),
    }


def get_team_recovery(boot, existing, now=None):
    """Entry point for refresh.py's main(). Returns
    {"fetched_at", "teams": {short_name: record}}; refetches the four feeds
    only if the last fetch is older than REFETCH_MINUTES. If every feed
    fails the previous result is kept."""
    now = now or datetime.now(timezone.utc)
    prev = (existing or {}).get("team_recovery") or {}
    try:
        if prev.get("fetched_at") and now - datetime.fromisoformat(prev["fetched_at"]) < timedelta(minutes=REFETCH_MINUTES):
            return prev
    except ValueError:
        pass
    idx = build_name_index(boot["teams"])
    per_club, ok, pl_seen = {}, 0, set()
    for competition, slug in FEEDS:
        try:
            rows = _fetch_feed(slug, season_year(now))
        except (urllib.error.URLError, OSError, ValueError) as e:
            _warn(f"{slug} feed failed: {e}")
            continue
        ok += 1
        got = matches_from_feed(rows, competition, idx)
        print(f"[fixtures_external.py] {slug}: {len(rows)} rows, {len(got)} PL-club matches", file=sys.stderr)
        for sn, m in got:
            per_club.setdefault(sn, []).append(m)
            if slug == "epl":
                pl_seen.add(sn)
    if not ok:
        return prev or {"fetched_at": None, "teams": {}}
    missing = [t["short_name"] for t in boot["teams"] if t["short_name"] not in pl_seen]
    if missing:
        _warn(f"no Premier League feed match for: {', '.join(missing)} (rename? add to NAME_HINTS)")
    teams = {sn: r for sn, r in ((sn, recovery_from_matches(ms, now)) for sn, ms in per_club.items()) if r}
    return {"fetched_at": now.isoformat(), "teams": teams}

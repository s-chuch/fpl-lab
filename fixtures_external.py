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
conference-league. The EFL Cup and FA Cup have no feed, so they are read from English
Wikipedia's cup pages ({{Football box}} templates via the parse API; kickoff times
there are UK local and converted to UTC); the FA Cup
page has no fixtures until later rounds are drawn, so that part is unverified
until PL clubs enter (January). API-Football's free plan, worldfootball.net,
ESPN and football-data.org were all ruled out (plan-blocked / 403 from Actions).

Feed club names mostly match FPL's own team names ("Man City", "Spurs",
"Nott'm Forest"); matching is exact-normalized only, plus NAME_HINTS. Any FPL
club with no match in the Premier League feed is logged, so a rename shows up
in the Actions log instead of silently dropping that club.

A kickoff in the last IN_PROGRESS_HOURS with no score yet counts as the club's
NEXT (in-progress) match. The previous result is only replaced when the
Premier League feed itself was fetched.

Every function degrades to an empty/None result rather than raising when a feed
can't be fetched — this is optional enrichment on a pipeline that must keep
working without it.
"""
from __future__ import annotations
import json, re, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

FEED_BASE = "https://fixturedownload.com/feed/json"
FEEDS = [("Premier League", "epl"), ("Champions League", "champions-league"),
         ("Europa League", "europa-league"), ("Conference League", "conference-league")]
USER_AGENT = "Mozilla/5.0 (compatible; ShaalandFPLLab/1.0)"
WIKI_UA = "ShaalandFPLLab/1.0 (https://github.com/s-chuch/fpl-lab)"  # Wikipedia asks for an identifying UA
WIKI_CUPS = [("EFL Cup", "{y}–{yy} EFL Cup"), ("FA Cup", "{y}–{yy} FA Cup")]
PENDING_RESULT_HOURS = 48  # how long a finished-but-unscored match is treated as played
SCHEMA = 4  # bump when the record shape changes so an old cached result is refetched, not reused for 30 minutes
REFETCH_MINUTES = 30  # feeds update as results land; also dedupes the two refresh.py runs per workflow
IN_PROGRESS_HOURS = 3  # an unscored match kicked off this recently is still being played
UK = ZoneInfo("Europe/London")

# FPL short_name -> extra names the feed might use, beyond FPL's own `name`.
NAME_HINTS = {
    "MUN": ["Manchester United", "Man United"], "MCI": ["Manchester City"],
    "TOT": ["Tottenham", "Tottenham Hotspur"], "WOL": ["Wolves", "Wolverhampton Wanderers"],
    "NFO": ["Nottingham Forest", "Nott'm Forest"], "NEW": ["Newcastle United"],
    "WHU": ["West Ham", "West Ham United"], "BHA": ["Brighton & Hove Albion"],
    "LEE": ["Leeds United"], "COV": ["Coventry", "Coventry City"], "HUL": ["Hull", "Hull City"], "IPS": ["Ipswich", "Ipswich Town"],
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


def _match_ref(m):
    return {"date": m["date"].strftime("%Y-%m-%d"), "competition": m["competition"], "opponent": m.get("opponent")}


def recovery_ahead(matches, now, anchor):
    """Forward-looking rest record, anchored on the NEXT gameweek deadline you can
    still act on (anchor). Once a gameweek's deadline has passed its squad is locked,
    so rotation risk only matters for what comes after: target = the club's first
    match on/after the anchor, last = the latest match BEFORE it in ANY competition
    (scheduled ones count - a midweek European tie still to be played is exactly
    what tires the squad for the target match), and `between` lists those scheduled
    matches. Unscored matches older than PENDING_RESULT_HOURS are treated as
    postponed and ignored."""
    usable = [m for m in matches if m["played"] or m["date"] >= now - timedelta(hours=PENDING_RESULT_HOURS)]
    ahead = sorted((m for m in usable if m["date"] >= anchor), key=lambda m: m["date"])
    before = sorted((m for m in usable if m["date"] < anchor), key=lambda m: m["date"])
    if not ahead:
        return None
    target, fol = ahead[0], (ahead[1] if len(ahead) > 1 else None)
    last = before[-1] if before else None
    between = [m for m in before if not m["played"] and m["date"] >= now - timedelta(hours=IN_PROGRESS_HOURS)]
    return {
        "rest_days": (target["date"].date() - last["date"].date()).days if last else None,
        "last_match": ({**_match_ref(last), "scheduled": not last["played"]} if last else None),
        "next_match": _match_ref(target),
        "following_match": ({**_match_ref(fol), "days_after": (fol["date"].date() - target["date"].date()).days} if fol else None),
        "between": [_match_ref(m) for m in between],
    }


def recovery_from_matches(matches, now, anchor=None):
    """Rest-days record for one club. With `anchor` (the next gameweek deadline you
    can still act on) it looks AHEAD of it - see recovery_ahead. Without one (season
    over / no deadline known) it falls back to 'since the last played match, before
    the next one': last = latest played match, next = earliest unplayed match still
    to come, including one that kicked off within IN_PROGRESS_HOURS."""
    if anchor is not None:
        rec = recovery_ahead(matches, now, anchor)
        if rec:
            return rec
    # A match that kicked off more than IN_PROGRESS_HOURS ago but has no score in the
    # feed yet has been played - the feed just lags - so it counts as the last match
    # (otherwise a club that played at noon shows its rest as measured from weeks ago).
    awaiting_score = [m for m in matches if not m["played"] and now - timedelta(hours=PENDING_RESULT_HOURS) <= m["date"] < now - timedelta(hours=IN_PROGRESS_HOURS)]
    played = [m for m in matches if m["played"]] + awaiting_score
    upcoming = sorted((m for m in matches if not m["played"] and m["date"] >= now - timedelta(hours=IN_PROGRESS_HOURS)), key=lambda m: m["date"])
    last = max(played, key=lambda m: m["date"]) if played else None
    nxt = upcoming[0] if upcoming else None
    fol = upcoming[1] if len(upcoming) > 1 else None  # the match after next: a short turnaround after `nxt` is the classic rotation trigger
    if not last and not nxt:
        return None
    return {
        "following_match": ({"date": fol["date"].strftime("%Y-%m-%d"), "competition": fol["competition"], "opponent": fol["opponent"],
                             "days_after": (fol["date"].date() - nxt["date"].date()).days} if fol and nxt else None),
        "rest_days": (nxt["date"].date() - last["date"].date()).days if last and nxt else None,
        "last_match": {"date": last["date"].strftime("%Y-%m-%d"), "competition": last["competition"]} if last else None,
        "next_match": ({"date": nxt["date"].strftime("%Y-%m-%d"), "competition": nxt["competition"], "opponent": nxt["opponent"]} if nxt else None),
    }


def _fetch_wiki_wikitext(title, timeout=25):
    q = urllib.parse.urlencode({"action": "parse", "page": title, "prop": "wikitext", "format": "json", "redirects": 1})
    req = urllib.request.Request(f"https://en.wikipedia.org/w/api.php?{q}", headers={"User-Agent": WIKI_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    if "error" in d:
        raise ValueError(d["error"].get("info", "wikipedia error"))
    return d["parse"]["wikitext"]["*"]


_BOX_RE = re.compile(r"\{\{[Ff]ootball box.*?\n\}\}", re.S)
_DATE_RE = re.compile(r"\|\s*date\s*=\s*(\d{1,2} [A-Za-z]+ \d{4})")
_TIME_RE = re.compile(r"\|\s*time\s*=\s*(\d{1,2}):(\d{2})")
_SCORE_RE = re.compile(r"\|\s*score\s*=\s*((?:[^\n|{\[]|\[\[[^\]]*\]\]|\{\{[^}]*\}\})*)")
_REAL_SCORE_RE = re.compile(r"\d+\s*[–—-]\s*\d+")


def _wiki_team(box, field):
    m = re.search(rf"\|\s*{field}\s*=\s*(.*?)(?=\s*\|\s*[A-Za-z0-9_]+\s*=|\n|\}}\}})", box)
    if not m:
        return None
    raw = m.group(1)
    link = re.search(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", raw)
    name = link.group(1) if link else raw
    return re.sub(r"\(\d+\)|\{\{.*?\}\}", "", name).strip() or None


def _clean_score(raw):
    """Drop link targets ([[Match 12|v]] -> v) and unwrap {{score link|X|2–1}} to its last arg."""
    raw = re.sub(r"\{\{[^|}]*\|(?:[^}]*\|)?([^|}]*)\}\}", r"\1", raw)
    return re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", raw)


def matches_from_wikitext(wikitext, competition, name_index):
    """Same shape as matches_from_feed, from a Wikipedia cup page's
    {{Football box}} templates. Kickoff times are UK local, converted to UTC;
    with no time the match is dated 23:59 UTC so an unplayed tie today still
    counts as upcoming. A match counts as played once a real score (2–1) is filled."""
    out = []
    for box in _BOX_RE.findall(wikitext or ""):
        dm = _DATE_RE.search(box)
        if not dm:
            continue
        try:
            when = datetime.strptime(dm.group(1), "%d %B %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        tm = _TIME_RE.search(box)
        if tm:
            local = datetime(when.year, when.month, when.day, int(tm.group(1)), int(tm.group(2)), tzinfo=UK)
            when = local.astimezone(timezone.utc)
        else:
            when = when.replace(hour=23, minute=59)
        sm = _SCORE_RE.search(box)
        played = bool(sm and _REAL_SCORE_RE.search(_clean_score(sm.group(1))))
        t1, t2 = _wiki_team(box, "team1"), _wiki_team(box, "team2")
        for me, opp in ((t1, t2), (t2, t1)):
            sn = name_index.get(_norm(me))
            if sn:
                out.append((sn, {"date": when, "competition": competition, "opponent": opp, "played": played}))
    return out


def next_deadline(boot, now):
    """(gameweek id, deadline datetime) of the first gameweek whose deadline is still
    in the future - the next one you can still make changes for. (None, None) if the
    season is over or no deadline parses."""
    for e in sorted(boot.get("events") or [], key=lambda e: e.get("id") or 0):
        raw = e.get("deadline_time")
        try:
            dl = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if dl > now:
            return e["id"], dl
    return None, None


def get_team_recovery(boot, existing, now=None):
    """Entry point for refresh.py's main(). Returns
    {"fetched_at", "teams": {short_name: record}}; refetches the four feeds
    only if the last fetch is older than REFETCH_MINUTES. If the Premier League
    feed fails the previous result is kept (never replaced by partial data)."""
    now = now or datetime.now(timezone.utc)
    prev = (existing or {}).get("team_recovery") or {}
    target_gw, anchor = next_deadline(boot, now)
    try:
        if prev.get("schema") == SCHEMA and prev.get("target_gw") == target_gw and prev.get("fetched_at") and now - datetime.fromisoformat(prev["fetched_at"]) < timedelta(minutes=REFETCH_MINUTES):
            return prev
    except ValueError:
        pass
    idx = build_name_index(boot["teams"])
    per_club, pl_ok, pl_seen = {}, False, set()
    for competition, slug in FEEDS:
        try:
            rows = _fetch_feed(slug, season_year(now))
        except (urllib.error.URLError, OSError, ValueError) as e:
            _warn(f"{slug} feed failed: {e}")
            continue
        pl_ok = pl_ok or slug == "epl"
        got = matches_from_feed(rows, competition, idx)
        print(f"[fixtures_external.py] {slug}: {len(rows)} rows, {len(got)} PL-club matches", file=sys.stderr)
        for sn, m in got:
            per_club.setdefault(sn, []).append(m)
            if slug == "epl":
                pl_seen.add(sn)
    yy = lambda y: f"{y + 1}"[2:]
    for competition, tmpl in WIKI_CUPS:
        y = season_year(now)
        try:
            text = _fetch_wiki_wikitext(tmpl.format(y=y, yy=yy(y)))
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            _warn(f"{competition} wikipedia page failed: {e}")
            continue
        got = matches_from_wikitext(text, competition, idx)
        print(f"[fixtures_external.py] {competition} (wikipedia): {len(got)} PL-club matches", file=sys.stderr)
        for sn, m in got:
            per_club.setdefault(sn, []).append(m)
    if not pl_ok:
        return prev or {"fetched_at": None, "teams": {}}
    missing = [t["short_name"] for t in boot["teams"] if t["short_name"] not in pl_seen]
    if missing:
        _warn(f"no Premier League feed match for: {', '.join(missing)} (rename? add to NAME_HINTS)")
    teams = {sn: r for sn, r in ((sn, recovery_from_matches(ms, now, anchor)) for sn, ms in per_club.items()) if r}
    return {"schema": SCHEMA, "fetched_at": now.isoformat(), "target_gw": target_gw, "anchor": anchor.isoformat() if anchor else None, "teams": teams}

"""All-competition rest-days for each PL club, scraped from worldfootball.net.

FPL's own API is Premier-League-only — no Champions League, Europa/Conference
League, or domestic cup fixtures exist in it — so "how many days' rest did
this club have before its next match" can't be answered from data this app
already fetches. This module fills that one gap and nothing else: everything
else about rotation risk stays in refresh.py's build_rotation_risk.

(API-Football was tried first, but its free plan refuses the `last`/`next`
fixture parameters and current-season data, so it was removed.)

Every function degrades to an empty/None result rather than raising when a
page can't be fetched or parsed — this is an optional enrichment layered on a
pipeline that must keep working without it. Each club's outcome is logged to
stderr so a layout change on the site is visible in the Actions log.

The row parser is deliberately generic (any <tr> holding a dd/mm/yyyy or
yyyy-mm-dd date) because it was written without being able to load the live
pages; check the first Actions run's log lines and adjust here if a club
reports no matches.
"""
from __future__ import annotations
import re, sys, time, urllib.error, urllib.request
from datetime import date, datetime
from html.parser import HTMLParser

BASE = "https://www.worldfootball.net"
USER_AGENT = "Mozilla/5.0 (compatible; ShaalandFPLLab/1.0)"
FETCH_DELAY = 1.5  # seconds between requests; be polite to a free site

# FPL short_name -> extra slug candidates where the plain slugified FPL name
# won't match the site's team slug.
SLUG_HINTS = {
    "MUN": ["manchester-united"], "MCI": ["manchester-city"],
    "TOT": ["tottenham-hotspur"], "WOL": ["wolverhampton-wanderers"],
    "NFO": ["nottingham-forest"], "NEW": ["newcastle-united"],
    "WHU": ["west-ham-united"], "BHA": ["brighton-hove-albion"],
    "LEE": ["leeds-united"], "AVL": ["aston-villa"], "CRY": ["crystal-palace"],
    "BOU": ["afc-bournemouth"], "SUN": ["sunderland-afc"],
}

DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")


def _warn(msg):
    print(f"[fixtures_external.py] WARNING: {msg}", file=sys.stderr)


def _slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s


def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


class _RowParser(HTMLParser):
    """Collects every <tr> as {"cells": [text, ...], "links": [(href, text), ...]}."""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell, self._href, self._link_txt = [], None, None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = {"cells": [], "links": []}
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "a" and self._row is not None:
            self._href, self._link_txt = dict(attrs).get("href", ""), []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        if self._link_txt is not None:
            self._link_txt.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._row is not None and self._href is not None:
            self._row["links"].append((self._href, " ".join("".join(self._link_txt).split())))
            self._href = self._link_txt = None
        elif tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row["cells"].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _row_date(cells):
    for c in cells:
        m = DATE_RE.search(c)
        if m:
            try:
                if m.group(1):
                    return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                return date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
            except ValueError:
                return None
    return None


def parse_matches(html, own_slug=None):
    """[{"date": date, "competition": str, "opponent": str|None}, ...] for
    every table row carrying a date, in page order."""
    p = _RowParser()
    try:
        p.feed(html)
    except Exception as e:
        _warn(f"parse_matches: HTML parse failed: {e}")
        return []
    out = []
    for row in p.rows:
        d = _row_date(row["cells"])
        if not d:
            continue
        comp = next((t for h, t in row["links"] if "/competition/" in h and t), None)
        opp = next((t for h, t in row["links"]
                    if "/teams/" in h and t and (not own_slug or f"/teams/{own_slug}/" not in h)), None)
        out.append({"date": d, "competition": comp or "?", "opponent": opp})
    return out


def recovery_from_matches(matches, today):
    """Rest-days record from a club's parsed matches: last match dated
    before `today`, next dated `today` or later. None if either is missing
    from the page (rest_days stays None but the other side is still kept)."""
    past = [m for m in matches if m["date"] < today]
    future = [m for m in matches if m["date"] >= today]
    last = max(past, key=lambda m: m["date"]) if past else None
    nxt = min(future, key=lambda m: m["date"]) if future else None
    if not last and not nxt:
        return None
    return {
        "rest_days": (nxt["date"] - last["date"]).days if last and nxt else None,
        "last_match": {"date": last["date"].isoformat(), "competition": last["competition"]} if last else None,
        "next_match": ({"date": nxt["date"].isoformat(), "competition": nxt["competition"], "opponent": nxt["opponent"]} if nxt else None),
    }


def _slug_candidates(team, cached):
    out = [cached] if cached else []
    base = _slugify(team.get("name"))
    for s in SLUG_HINTS.get(team.get("short_name"), []) + [base, base + "-fc"]:
        if s and s not in out:
            out.append(s)
    return out


def fetch_recovery_for_team(team, today, cached_slug=None):
    """(recovery-record | None, slug | None) for one FPL team dict. Tries
    each slug candidate's team page until one yields dated rows."""
    for slug in _slug_candidates(team, cached_slug):
        url = f"{BASE}/teams/{slug}/"
        try:
            time.sleep(FETCH_DELAY)
            html = _fetch(url)
        except (urllib.error.URLError, OSError, ValueError) as e:
            _warn(f"{team.get('short_name')}: {url} failed: {e}")
            continue
        matches = parse_matches(html, own_slug=slug)
        rec = recovery_from_matches(matches, today)
        if rec:
            print(f"[fixtures_external.py] {team.get('short_name')}: {len(matches)} dated rows from {url}", file=sys.stderr)
            return rec, slug
        _warn(f"{team.get('short_name')}: {url} loaded but {len(matches)} dated rows gave no last/next match")
    return None, None


def get_team_recovery(boot, existing, today_et):
    """Top-level entry point for refresh.py's main(). Returns
    {"fetched_date", "slugs", "teams"}. Cached by ET calendar date, and
    clubs that already have data today are not re-fetched, so repeated
    workflow runs cost nothing and a partial run only retries the gaps.
    fetched_date is stamped only when every club has data."""
    prev = (existing or {}).get("team_recovery") or {}
    slugs = dict(prev.get("slugs") or {})
    if prev.get("fetched_date") == today_et:
        return prev
    today = datetime.strptime(today_et, "%Y-%m-%d").date()
    teams = dict(prev.get("teams") or {}) if prev.get("partial_date") == today_et else {}
    empty_streak = 0
    for t in boot["teams"]:
        sn = t["short_name"]
        if sn in teams:
            continue
        rec, slug = fetch_recovery_for_team(t, today, slugs.get(sn))
        if rec:
            teams[sn], slugs[sn], empty_streak = rec, slug, 0
        else:
            empty_streak += 1
            if empty_streak >= 4:
                _warn("get_team_recovery: 4 consecutive clubs failed; stopping early (site blocked or layout changed?)")
                break
    complete = all(t["short_name"] in teams for t in boot["teams"])
    return {"fetched_date": today_et if complete else None,
            "partial_date": None if complete else today_et,
            "slugs": slugs, "teams": teams}

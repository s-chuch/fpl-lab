# fpl-lab project notes

## Recovery-period feature (rest days)

- `fixtures_external.py` reads **fixturedownload.com**'s free JSON feeds
  (`/feed/json/{epl,champions-league,europa-league,conference-league}-<year>`;
  no key, works from GitHub Actions) and computes each PL club's rest-days
  between its last played and next scheduled match. `refresh.py`'s `main()`
  calls `fixtures_external.get_team_recovery(boot, cache)`; the result feeds the
  "Rest" column and "Congestion" badge on the Rotations tab. Cached in
  `team_recovery_cache.json` (refetched at most hourly).
- **Gap:** FA Cup and EFL Cup are not covered (no free feed found), so a cup
  midweek game is invisible to rest-days.
- Check the Actions log for `[fixtures_external.py]` lines: a warning "no
  Premier League feed match for: ..." means a club name changed — add it to
  `NAME_HINTS`.
- Ruled out (tested 2026-09-29 from Actions): API-Football free plan (refuses
  `last`/`next` params and current-season data; only a rolling 3-day fixtures
  window), worldfootball.net and ESPN (403 to GitHub's IPs), football-data.org
  (needs key/plan). The `API_FOOTBALL_KEY` repo secret is no longer used and
  can be deleted.

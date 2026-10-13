# fpl-lab project notes

## Recovery-period feature (rest days)

- `fixtures_external.py` reads **fixturedownload.com**'s free JSON feeds
  (`/feed/json/{epl,champions-league,europa-league,conference-league}-<year>`;
  no key, works from GitHub Actions) and computes each PL club's rest-days
  between its last played and next scheduled match. `refresh.py`'s `main()`
  calls `fixtures_external.get_team_recovery(boot, cache)`; the result feeds the
  "Rest" column and "Congestion" badge on the Rotations tab. Cached in
  `team_recovery_cache.json` (refetched at most every 30 minutes).
- **Cups:** no feed exists for the EFL Cup / FA Cup, so `fixtures_external.py`
  parses English Wikipedia's `2026–27 EFL Cup` / `FA Cup` pages (`{{Football box}}`
  templates via the parse API). EFL Cup verified live; the FA Cup page has no
  fixtures until PL clubs enter in January, so that path is unverified — check
  the `FA Cup (wikipedia)` log line then.
- Check the Actions log for `[fixtures_external.py]` lines: a warning "no
  Premier League feed match for: ..." means a club name changed — add it to
  `NAME_HINTS`.
- Ruled out (tested 2026-09-29 from Actions): API-Football free plan (refuses
  `last`/`next` params and current-season data; only a rolling 3-day fixtures
  window), worldfootball.net and ESPN (403 to GitHub's IPs), football-data.org
  (needs key/plan). The `API_FOOTBALL_KEY` repo secret is no longer used and
  can be deleted.

## AI team (Plan / Results tabs under "AI team")

- `ai_team.py` plays a squad on its own from GW7 with the user's money (sell value + bank at
  start) and chip availability. State lives in `data["ai_team"]` (data.js / bacalhau-data.js),
  advanced by `refresh.py`'s `run_ai_team()` every run. Failures there never break the refresh.
- Each GW: the plan is recomputed every run until 12h before the deadline (`LOCK_HOURS`), then
  the first run after that locks it (transfers, XI, bench order, captain, vice). `refresh.yml`
  has a `*/30` cron whose first step skips the run unless it lands in the hour after the lock
  time; the normal crons are unaffected.
- Points come from FPL's live data (auto-subs, captain/vice, hits). Chip *decisions* are not
  built: it only lists the chips still available (same as the user). Revisit when chips reset (GW20).
- `ep_next` in FPL's bootstrap currently equals `form`, so it only gets a 20% weight.

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

- `ai_team.py` is a copy of the user's team that then plays on its own. On its first run (state
  version 2) `refresh.py`'s `_clone_user_team()` snapshots the locked GW's 15 players at the prices
  paid, the bank, the free transfers banked, the chips used and the points so far; after that the AI
  ignores what the user does. State lives in `data["ai_team"]` (data.js / bacalhau-data.js),
  advanced by `run_ai_team()` every run. Failures there never break the refresh.
- Season points = the user's points up to the copy (`baseline_points`) + what the AI scores itself.
- Each GW: the plan is recomputed every run until 12h before the deadline (`LOCK_HOURS`), then
  the first run after that locks it (transfers, XI, bench order, captain, vice). `refresh.yml`
  has a `*/30` cron whose first step skips the run unless it lands in the hour after the lock
  time; the normal crons are unaffected. Every run re-checks injuries, rotation, congestion and
  minutes, and logs changes (`changes`, `watch_locked`).
- Points come from FPL's live data (auto-subs, captain/vice, hits). Chip *decisions* are not
  built: it only lists the chips still available. Revisit when chips reset (GW20).
- `ep_next` in FPL's bootstrap currently equals `form`, so it only gets a 20% weight.

## Asset versions and caching

- `stamp_versions.py` rewrites every local `<script src>` / `<link href>` in `index.html` and
  `bacalhau.html` to `?v=<content hash>` (and replaced the old per-minute `document.write` loaders
  with static tags). `refresh.yml` runs it before committing and again after the rebase, and its
  `paths:` list includes the page/JS/CSS files so a push that edits them also gets stamped. Run it
  yourself before committing a UI change if you want the new URL immediately.
- `x-posts.js` is no longer loaded by the pages (the X feed is discontinued and stale), and
  `refresh.py` only uses a theme file (`_load_theme_file`) if it is at most 3 days old.
- `fpl_common.get` reuses one keep-alive HTTPS connection per host per thread and does not retry
  4xx (e.g. the expected 404 for a GW that has not locked); fixtures come from one whole-season
  request (`_fixtures_for`); league members' picks are prefetched in parallel (`_prefetch_picks`).

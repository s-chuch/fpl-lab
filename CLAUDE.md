# fpl-lab project notes

## Recovery-period feature (rest days)

- `fixtures_external.py` scrapes each Premier League club's team page on
  **worldfootball.net** (no API key, no account) for its last and next match in
  any competition, and computes rest-days. `refresh.py`'s `main()` calls
  `fixtures_external.get_team_recovery(boot, cache, today_et)`; the result feeds
  the "Rest" column and "Congestion" badge on the Rotations tab.
- Results are cached in `team_recovery_cache.json` (per ET day; only clubs
  still missing data are retried on later runs).
- **Unverified against the live site**: the parser was written without being
  able to load worldfootball.net (blocked in the authoring sandbox). Check the
  first Actions run's `[fixtures_external.py]` log lines; if clubs report no
  matches, adjust `parse_matches` / the team-page URL / `SLUG_HINTS`.
- History: API-Football was tried first and removed — its free plan refuses the
  `last`/`next` fixture params and current-season data ("Free plans do not have
  access to the Last parameter"). The `API_FOOTBALL_KEY` repo secret is no
  longer used and can be deleted.

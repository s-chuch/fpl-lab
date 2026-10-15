# Decisions

Short records of choices that are easy to undo by accident. Newest detail lives in `CLAUDE.md`.

## AI team locks 12 hours before the deadline
The plan is recomputed every refresh until `LOCK_HOURS` (12h) before the deadline, then the first run after that locks it. A stateless `*/30` cron only runs the refresh inside that window. Locking early gives the plan a fixed, checkable commitment; recomputing until then lets news and injuries change it. A plan only changes if the new one beats it by `HYSTERESIS` (0.6 expected points).

## Generated data is committed
`data.js`, `bacalhau-data.js` and the news/cache files are committed by the workflow because GitHub Pages serves static files and the browser cannot call FPL's API (no CORS). Trade-off: frequent data commits and rebase conflicts in the stamped `index.html` / `bacalhau.html`. The commit step therefore rebases with `-X theirs` (this run's regenerated files win), restores the two hand-edited wildcard files from `main` and recomputes their generated blocks, then re-stamps asset versions.

## Chips are tracked per half
FPL resets chips at GW20. `chips_by_half` returns `chip` (GW1-19) and `chip_h2` (GW20+); nothing may collapse them to one entry per name.

## Model blending
Expected points blend the xG/xA model, minutes security, fixtures and (when priced) bookmaker odds; FPL's `ep_next` gets a 20% weight because it mostly repeats form. `calibrate.py` backtests the model against plain form; the linear correction is not applied because the measured slopes are 0.75-0.95, not compressed.

## Wildcard watch files are partly hand-edited
The squad in `*-wildcard.js` is captured by hand while a wildcard is a draft; once the deadline passes `sync_confirmed_squad` replaces it with the locked picks. Generated blocks (`recommend`, `worth_tracker`) are recomputed by the workflow.

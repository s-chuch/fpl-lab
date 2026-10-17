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
- The X feed and `x-posts.js` / `x_scrape.py` are gone. `signals._load_theme_file` only uses `news.js` if it is at most 3 days old.
- `fpl_common.get` reuses one keep-alive HTTPS connection per host per thread and does not retry
  4xx (e.g. the expected 404 for a GW that has not locked); fixtures come from one whole-season
  request (`_fixtures_for`); league members' picks are prefetched in parallel (`_prefetch_picks`).

## Guarding against silent staleness

- Every chip you have played must show a result on Review > Chips (`build_chip_net` in `refresh.py`),
  using only things that can be measured: Bench Boost = the bench's points, Triple Captain = the
  captain's third multiple, Free Hit / Wildcard = the new squad's 15 players' GW points minus the previous squad's, player for
  player with the bench counted and no captain multiplier (`build_fh_audit` -> `compare`, shown as a
  collapsible list). Never the gameweek score vs the field average: that reads as a gain even when the
  chip made the squad worse. The card shows when the data
  was generated.
- Field averages: FPL's `average_entry_score` moves until a gameweek is finished AND `data_checked`;
  `refresh.py` only caches settled values (GW6 was cached at 37 mid-week, final 58, and every
  "vs the field" figure for that week was wrong).
- `check_data.py` runs as the **last** step of `refresh.yml` (after the data is committed, so the
  refresh itself is never blocked): it fails the run — red + email — if a required section is missing,
  a played chip has no result line, or the AI team's plan is not for the next open gameweek. Add a
  check there whenever a new section could go quietly stale.

## Wildcard watch files (`shaaland-wildcard.js`, `bacalhau-wildcard.js`)

- The squad in them is hand-captured while a wildcard is still a draft. Once that gameweek's deadline
  passes, `wildcard_recommend.py` (`sync_confirmed_squad`) replaces it with the locked picks every
  refresh and marks it `confirmed`, so a stale "provisional" draft can no longer linger (Bacalhau's sat
  at the 20 Sep draft after GW6). `check_data.py` fails the run if that ever happens again.
- Captain / bench advice uses the program's own expected points (`ai_team.player_values`, next open
  gameweek), not FPL's `ep_next` — which currently just repeats last week's form.

## Reliability and correctness rules (added after the R&D review)

- **One captain.** Plan tab (`_armband_by_xp`), AI plan and Wildcard watch all rank on `ai_team.player_values`
  with the same inputs (`refresh.model_inputs`: Understat windows + risk). Lineup/captain/bench use this
  gameweek's `xp`; `value` (this + next GW) is only for transfer decisions.
- **Points.** FPL's `points` is gross of hits. Anything compared with the AI team (net of hits) uses
  `points - event_transfers_cost`.
- **Chips are per half.** `chips_by_half(hist)` returns `chip` (GW1-19) and `chip_h2` (GW20+); never collapse to
  one entry per name. `chips_official`, `chip_net`, the Chips tab and `check_data` all use these keys; the AI
  team's `chips_available` ignores first-half plays from GW20.
- **Sections cannot kill a refresh.** `main()` wraps builders in `section(name, fn, ...)`: on failure the previous
  value is kept and `data["_health"][name]` records it; `check_data.py` fails the run on any failed section, an
  empty key section, data older than 30h, an illegal AI squad, or points that do not add up. A corrupt
  `data.js` stops the run instead of starting from scratch; files are written atomically and compact.
- **Workflow.** Checkout is `ref: main` then `git pull --ff-only`; the `*/30` gate is stateless (next deadline
  within 12h and that GW's AI plan not locked yet, retrying the FPL fetch). `tests/` (offline unit tests for
  sell price, chips, squad pairing, score_plan, model) run in the Syntax check step.
- **Plan/Targets.** `fixture_map` combines double gameweeks; Targets only use gameweeks whose deadline has not
  passed and score blank (-2) / double (+2) gameweeks. Price radar projects a move only for a strong swing.
- `data["pred_log"]` records each GW's Plan/AI captain and grades it against actual points after `data_checked`.
- xG/xA track record baseline = attacking starters (MID/FWD, 60+ mins), `baseline_att`.
- Plan tab opens with `thisGwCard` (captain/vice, like-for-like transfer, XI fitness flags, chip advice, AI lock time);
  Captain tab opens with `predLogCard` (the `pred_log` scorecard). The Free Hit tab headline is the same
  all-15 player-for-player figure as the Chips tab. Bench bars: You teal, Process yellow, Hindsight red.

## Code layout
- `refresh.py` is the orchestrator (`main`, plan, captain/bench audits, transfers, targets, leagues). Builders live in
  modules that import only from `fplbase.py`, never from `refresh.py`: `fplbase.py` (logging, constants, memoised GET,
  deadline state, fixtures), `chips.py` (per-half chips, chip results, Free Hit/Wildcard audit, free-transfer ledger,
  chip strategy), `signals.py` (xG/xA + track record, form, DEFCON, rotation/congestion, value, injuries, price radar),
  `ai_run.py` (model inputs, clone of your team, running the AI team, daily check). `refresh.py` re-exports all of them,
  so `refresh.chips_by_half` etc. still work for tests and `wildcard_recommend.py`.
- Shared page code lives in `dashboard-common.js`; per-team wording for shared renderers is the `W` table at the top of
  each page's script.
- `planner.py` (multi-GW transfer planner): beam search over the next 5 open gameweeks from your locked squad (sell prices, bank, free
  transfers, -4 hits) on `ai_team.player_values` per gameweek; shown on the Plan tab (`plannerCard`, `data["planner"]`). It says
  "roll" unless the plan beats rolling by 1+ expected points. Chips are not planned. `signals.build_elite_ownership` gives
  top-50 ownership (`data["elite"]`: Captain tab card and a Top 50 column on Target lists).
- **Live matchday layer.** The browser cannot read FPL's API (no CORS), so `.github/workflows/live.yml` runs `live_update.py` every
  10 minutes in match windows; it writes `live-data.js` (your squad's provisional live points, scores, who has played) only when a
  gameweek is live, so the repo changes only on match days. The pages load it with a cache-busting query (`loadLive`, not stamped)
  and show `liveBar` above the tabs, re-reading it every 5 minutes while open. Auto-subs and vice promotion are not applied until the
  gameweek settles.
- **Intel tab.** News themes are matched by `fpl_common.load_player_index` (full name + initial/surname aliases, the more-owned
  player wins a shared surname, a bare common first name is not a match) and their tags are checked against FPL (`sane_tags`:
  injury only if FPL flags him, differential only under 15% owned, no fade on heavy buying). News numbers come from
  `data["news_players"]`; `data["set_pieces"]` (taker orders) feeds the Set pieces tab (a separate Team news tab was removed: it repeated the Injury tab); Injury, Rotation and Price radar moved into Intel. The scraper's processed-URL list lives in
  `news_seen.json` (not shipped to the page). Counts read "N/M sites with fresh articles (K checked)".
- **News verdicts.** `fpl_common.stance_quotes` / `sentence_stance` read the sentences around each player's name (cue within 80
  chars; "not buy" flips; roundup headlines listing several names, boilerplate and "managers sold him" market facts are ignored) and
  `build_themes` turns them into a verdict (`stance_verdict`), cue counts and up to four quotes per theme. News articles in the
  window get their full text fetched every run (`MAX_BODY_FETCHES`), since the verdicts live in the body. It is a heuristic, not
  an LLM: the page says so.
- **Claude summaries on News (optional).** `news_llm.py` sends each theme's player-mentioning sentences plus FPL facts to the Claude API
  (`claude-haiku-5-5`, override with `NEWS_LLM_MODEL`) in one batched call per run and stores a validated verdict / summary /
  risks / confidence as `llm` on the theme (unchanged excerpts are not re-sent). It only runs when the `ANTHROPIC_API_KEY` repo secret
  exists (the workflow passes it to the "Pull live FPL data" step); without it, or on any error, the rule-based verdicts stay.
  Article text is treated as untrusted in the prompt and the output is bounded before it is stored.
- **One transfer brain.** Every transfer suggestion uses all the data the program has. `ai_run.build_transfer_signals` turns news verdicts
  (Claude's read when present), top-50 ownership, price momentum, set-piece duties and your mini-league position (defend a lead with the
  template, chase with differentials; AI team ignores this one) into small capped bonuses in expected points (`ADJ_CAP` 1.2, reasons
  listed). They feed `ai_team.plan_transfers` (AI team) and `planner.py` (Plan tab planner); the Plan tab's transfer line is the
  planner's first step (`plan["transfer"].source = "planner"`), the news-rule idea survives only as an advisory line with its xP cost, and
  the Plan XI/bench/captain come from `refresh._lineup_by_xp`. Target 1/3/6 and the transfer-target tables carry `xp` and `sig`
  (`ai_run.enrich_with_model`). In `main()` everything that needs these signals (AI team, pred_log, planner, daily check) runs last.
- **Fixture swing** (Strategy > Fixtures): `fixture_swing.py` builds `data["swing"]` (20 clubs x next 8 gameweeks, opponent, FDR, attack and
  defence difficulty, blank/double flags, owned clubs), `swing.js` renders it (3/6/8 GW windows, Overall/Attack/Defence, clubs to
  target / sell, 20-club heat table). FPL's `strength_*` team fields are all 0 this season, so attack/defence difficulty comes from each
  club's goals for/against per game (`ai_run._team_form`, shrunk to the league mean). The Wildcard line in the chip hints only
  appears when the Wildcard is available this half. `elo.py` fetches Club Elo (api.clubelo.com) into `data["elo_ratings"]` and
  `elo_cache.json`; it returned 502 from the dev sandbox, so it is unverified from Actions and silently skipped when unavailable.
- **Price changes** use FPL's own `price_change_percent` / `price_change_projections` (likelihood -5..4; +-90% projects a move),
  with transfer momentum only as a fallback; both the Price radar and the transfer signals use it.
- **xG/xA volume lists** (after the track-record review): goal list = MID/FWD only; assist list needs 6+ chances created or 3+ big
  chances (defenders at double that); regular starters only (55%+ of available minutes); flags carry `pos` and the track record shows
  hit rates by position; a gameweek is graded only when FPL has settled it (`finished AND data_checked`). The regression tags are shown as
  "Overperforming"/"Underperforming" (not transfer orders); squad rows show next fixture, FDR and ownership.
- **AI plan stability.** An unlocked AI plan keeps its previous transfers unless the fresh plan beats them by `HYSTERESIS` (0.6 expected
  points) or a kept move becomes illegal / its in-player drops below 75% fit (`rescore_transfers`, `keep_previous` in `ai_team.py`), so a
  model tweak cannot flip a near-tie. The daily-check log is transfer-level (`kind: "transfer"`, with `cause`, `cause_ref` = git sha from
  `ai_run._model_ref`), reversals are merged away (`merge_changes`), and `aiChangesCard` groups lines by check time. Old `swap` entries
  from before this change may still appear in the log.
- **Free data sources.** `odds.py` (football-data.co.uk `fixtures.csv`): bookmaker odds -> margin-free probabilities -> Poisson goal
  expectations and clean-sheet chances; `ai_run.setup_odds` registers them in `fplbase.ODDS` and `fixture_scan` merges them into the
  fixtures, so `ai_team.model_xp` blends the market's clean-sheet / goal expectations with the FDR guess whenever a match is priced
  (usually only the next matchweek; nothing during an international break, as now). `calibrate.py` + `calibration.json` backtest the
  xP model on vaastav's FPL history (fit 2024-25, graded on 2025-26 GW6-38, 11.5k player-gameweeks): the model is level with or slightly
  better than plain form (MAE 1.97 vs 2.09) and far better than FPL's own xP column; slopes are 0.75-0.95 (NOT compressed: the earlier
  117-regular in-sample audit was a selection effect), so the linear correction is not applied (it is shown as a row on the accuracy card,
  `data["model_accuracy"]`). Re-run `python calibrate.py` to refresh it. Club Elo (`elo.py`) returns 502 from both the dev sandbox and
  Actions, so it is skipped silently.
- **Specific news facts.** `news_scrape` tags each article segment with its URL and headline (`\x02url\x03title\x02` header, parsed by
  `fpl_common.items_of`); `fact_sentences` pulls the sentences that mention a player with a concrete cue (fitness, role, fixture, form,
  price, captaincy; roundups, lineup lists, emoji and sign-up boilerplate dropped) and `build_themes` keeps the best per topic as
  `facts` with the source link. Player names match as whole tokens (`_name_re`: "White" is not found in "Gibbs-White").
- **Good / bad / neutral news.** Every news fact has a `tone` (`fpl_common.tone_of`: cue words with negation flipping; reads wording, not
  meaning) and each theme an `overall_tone`; the News card is point form: 🔴 bad first, then 🟢 good, neutral folded, each bullet a short
  sentence with its topic and linked source.
- **Overperforming list** (xG/xA tab): MID/FWD only, each row shows next fixture, FDR, ownership and G+A per 90, plus a "hold / watch" pill when
  the next fixture is easy; defenders and keepers are read separately (goals conceded vs xGC, `top_def_lucky`); under 10 played gameweeks a
  one-line note says to treat it as a watch list, not a sell list. Scouting lists use `signals.scouting_ok` (270+ mins and 45% of minutes so
  far, available, 75%+ chance of playing).
- **xG/xA follow-ups (GrokDoor 111):** Overperforming rows show minutes; Top xGI/90 rows show next fixture, FDR, ownership and minutes; the Underperforming list uses a softer bar (`UNDER_SOFT` 1.5, squad tag still 2.0); assist volume needs 7+ chances created (defenders 14) in 3+ of the last 4 appearances; Understat-based squad tags say "(Understat)".
- **XGA tab review** (tab renamed from xG/xA): GKP never get the attacking over/underperforming tag and DEF need double the threshold (their luck is read from goals conceded vs xGC); "Defence running lucky" caps 2 per club and sits before the volume lists; the league over/under lists are one table; the track record shows distinct players behind the flags and says plainly when the hit rate is below the baseline (it is, ~9% vs 16%, GW3-6).
- **Automation hardening (scan 3):** `refresh.yml` records which builder failed (`steps.pull.outputs.failed`), still commits what succeeded, then fails the run; unit tests run last (red email, but data still refreshes); `watchdog.yml` runs `check_data.py --age-only` on its own 6-hourly cron so a stopped refresh still turns red. `check_data` also fails on a missing `team_recovery.fetched_at` and an unlocked AI plan older than 12h; `enrich_model` and `daily_check` write `_health`. `live_update.py` skips the write when only `generated_at` changed and never fails the run on an FPL error. `swing.js` is stamped; `news.js`/`news_seen.json` are written atomically.
- **Scan 4 (GrokDoor 114-118):** Free Hit XI headings no longer show the played-XI totals (one headline: the all-15 figure); `_health` marks optional sources that answered nothing (`elo`, `odds`) as `empty: true` (still ok, never fails the run); FPL Page (no feed, never produced anything) and the unused `x_accounts` are gone from `sources.json`; the Rotation tab counts a start as 45+ minutes, like the model's minutes-falling rule.
- **Scan 5 (model review):** reported-rotation flags are keyed on the element id (`signals.rotation_flag`, `id:<n>`) so a shared web_name no longer penalises everyone; recent minutes are capped at 90 and skip a club's blank gameweeks (`ai_run.model_inputs`, `build_rotation_risk`); a kept AI transfer that is a hit must clear `HIT_COST + KEEP_FLOOR`; chip windows expire once the last gameweek whose deadline has passed reaches their end; a Plan captain who did not play is graded as 0. Known and not done: rest/rotation penalties still apply to every future gameweek in the planner, and club ranking in Fixture swing ignores blanks/doubles.
- **Scan 6 (GrokDoor 119-120):** "Sell value" label when `live_value` is used; Plan transfer header says MAKE when the model has chosen moves; the news advisory line only shows when it does not cost expected points; "him"/"them" grammar; all-used chips collapse to one line; the Wildcard room card hides once this half's wildcard is used; the empty AI Results note is exempt from the ⓘ collapse (`data-keep`).
- **Scan 7 (page review):** `trendNote(gt, pronoun, gap)` words the last-GW swing by who is ahead; `newsVsSquad` classifies news on the structured verdict/LLM verdict, not the text line; swing Wildcard hint no longer needs a never-written flag; track-record footnote uses `baseline_att` and the verdict ignores a missing baseline; the chip-window countdown counts GW next..stop; `plan-intel.js` reads chips per half (`_h2` from GW20); a vice who took the armband shows his own points; Watkins-style players show LEFT; news fitness/bad cues need "miss + match/game/weeks" context. Not done: bacalhau still has "You/Your" strings in a few shared renderers (`eliteCard`, `captainBlock`, `rivalsCard`), and bacalhau does not load plan-intel.js.
- **Scan 8:** shared renderers now use the `W` table for You/Your (`captainBlock`, `eliteCard`, `rivalsCard`, news "Yours" pill, set-piece note); the planner applies next-match rest and reported rotation only to the first gameweek; Fixture swing ranks "clubs to target / sell" on per-gameweek ease (a double counts twice, a blank nothing) while still showing mean FDR; the planner's weekly line shows the -4 hit.
- **Scan 9 (GrokDoor 121-122):** Target rows need 2.5+ expected points per gameweek (`xp` is a horizon sum); the Bench tab's second list is labelled as the process XI's view, not advice; the Wildcard captain line reads "Your captain · model pick".
- **Notes toggle (`minimize` in dashboard-common.js) hid the AI plan's transfer list by accident.** Anything that carries decisions (not explanation) must be marked `data-keep`; the AI plan card now opens with a "Planning: ..." line and keeps its facts and transfer lists visible.
- **Scan 10 (GrokDoor 124):** league differential tags read `vs_a`/`vs_b` (they read non-existent `vs_first`/`vs_second`); Leagues "1st:/2nd:" labels print the real rank (P1/P3); the AI model no longer applies availability twice to `ep_next`; Target rows sort by score then xP. Deliberately not changed: league ownership counts all 15 squad slots (labelled "owned", not EO), `fdr_att` centring (calibrated), "defence luck" cap stays 2 per club.
- **Live matchday layer is ON again** (the user asked for live predictions and AI points): `live.yml` runs `live_update.py` every 10 minutes in match windows; the snapshot now also carries `pred` (`live_update.pred_live`: where each prediction for the live gameweek stands: not started / in play / done, with goals, assists, DEFCON count or goals conceded). The followed picks are the saved top-10s (`prediction_log.json`) when they exist, else the older saved lists (volume_log flags + `legacy_predictions.json`), so GW7 shows the earlier method and GW8 on shows the new top 10. The Predictions page renders it at the top (`labPredLiveHtml`, refreshed by `loadLive` every 5 minutes).
- **Code-quality pass (GrokDoor 125):** tuned model numbers in `ai_team.py` are named constants at the top (`MINUTES_FALLING_FACTOR`, `REST_FACTOR`, `EP_NEXT_WEIGHT`, `FDR_*`; values unchanged, checked with a hash of `player_values` before/after); `fplbase.FETCH_ERRORS` names what a failed FPL request raises and replaces the catch-all in the fixtures fallback; `parse_deadline` and the Understat cache load catch only the expected errors. The deliberate catch-alls (`section()`, AI team, optional sources) stay. Still not done: `logging` module, splitting large modules.
- **Logging:** `fpl_common.get_logger(tag)` gives each script a stdlib logger printing `[tag] LEVEL: message` to stderr (same lines as before); `fplbase._warn`, `fixtures_external._warn`, the `get()` retry notice, `event_window` and the Understat cache messages go through it. The remaining `print` calls are scripts' own progress output (news scrape, calibrate, check_data).
- **`ai_changes.py`** holds the AI team's change log (`diff_plans`, `merge_changes`, `watch_locked`, `_transfer_cause`, flag text); `ai_team.py` re-exports the names so `ai_team.diff_plans` etc. still work. First module split; checked with the model hash, the unit tests and a same-plan comparison of a full refresh before/after. Next candidates if wanted: `plan_transfers` / `rescore_transfers` / `keep_previous`.
- **Review fixes (GW7 live):** `check_data` no longer fails on a live gameweek (points reconcile only checks "not above FPL's total" while the locked GW has no row points yet) or on AI sell value + bank that exceeds the starting money by price rises (4% headroom); reported-rotation flags need a news verdict of "Fitness or rotation doubts" (the bare "rotation risk" tag fires on any Champions League mention and was cutting a Captain-candidate Haaland by 20%).
- **Plan pitch view has three modes:** Current / Recommended / AI (`labSquads` builds `ai` from `data.ai_team.plan` when it is for the same gameweek; the choice is remembered per page). The AI view shows the AI team's own XI, bench, C/V and its transfers as IN badges.
- **Target cards are three per row** (compact `.lab-pc` styles at the end of `dashboard.css`; two per row only under 360px).
- **Predictions (More tab, first box):** `ai_run.build_predictions` -> `data["predictions"]` for the next gameweek: top scorers and assisters (expected goals / assists from `ai_team.model_outlook`, the same ingredients as `model_xp`, plus the chance of at least one), clubs likeliest to keep a clean sheet, and rotation risks (decent xP, ranked by chance of rotation = 1 - minutes share x fitness x the rest / minutes / reported-rotation factors). Rendered by `labPred` as the first accordion in More (above the Decision log).
- **Navigation is the bottom bar only** (Plan / Target / More); the duplicate top tab bar is gone.
- **More is a menu of pages, not dropdowns:** each entry (Predictions, Decision log, the old tab groups) is a button (`.lab-mi`) that opens its own page with a "← More" back button; groups with several sections show them as pill tabs (`.lab-stabs`) inside the page. Tapping More on the bottom bar while on a page returns to the menu; the Plan tab's "Last GW" link opens the Decision log page (`data-declog`).
- **`hidden` needs a CSS guard on anything with its own `display`:** `.lab-menu` is `display:flex`, which beat the `hidden` attribute, so opening a More page left the menu showing and the page below the fold (looked like "the buttons do nothing"). `.lab-menu[hidden], .lab-mpage[hidden], .lab-spane[hidden]` are forced to `display:none`. Check computed display, not just `el.hidden`, when testing show/hide.
- **Predictions rows are compact** (`.lab-pr`: name + club, percentage on the right, one small line for fixture and xG/xA).
- **Prediction log and recalibration (`pred_track.py`):** the Predictions page shows the top 10 for goals, assists, clean sheets (clubs) and DEFCON (plus a rotation list that is not graded). Each run saves the next gameweek's top 10 into `prediction_log.json` / `bacalhau-prediction_log.json` (committed by the workflow) until its deadline passes; once FPL has finished and data-checked the gameweek, `grade()` marks each pick right or wrong from the live stats and fixtures (goal / assist >= 1, club conceded 0, `defensive_contribution` >= 10 for DEF and 12 for MID/FWD) with a reason. `view()` feeds the track record (hit %, per category, per GW), the "why picks missed" counts and the calibration: from 30 graded picks a category's probabilities are scaled by actual hit rate / predicted rate (shrunk towards 1, bounded 0.6-1.4); `raw` keeps the uncorrected value. First results arrive after GW8 is settled.
- **Earlier-method scorecard:** the Predictions page also shows what was saved before `pred_track` existed, kept apart from the new hit rate and recalibration: the old chance-volume goal/assist lists (`volume_log`, played-only; GW3-6 were rebuilt afterwards) and the DEFCON top-10 lists taken from the committed `data.js` just before the GW6 and GW7 deadlines (`legacy_predictions.json`, graded by `pred_track.grade_legacy` once FPL settles the gameweek). Nothing exists for clean sheets or for GW1-5.
- **AI results are a squad view:** More > AI team > Results shows the selected gameweek as a pitch (shirts, points per player, C/V, bench with points, auto-subs once final) plus a season / GW / bench strip; GW pills switch weeks. `score_plan` now returns `bench_lines`. While the gameweek is open the points are provisional ("Live · updating"): they refresh whenever a data refresh lands, and the open page re-reads `data.js` every 5 minutes. The comparison with you is only shown once the gameweek is final. Match-by-match freshness depends on how often the refresh runs (the live workflow is paused).
- **AI plan is a squad view too:** More > AI team > Plan shows the planned XI and bench as a pitch (`labPitchHtml`, with xP, fixture, C/V, IN, doubt badges) under the stat boxes and transfer cards; the old XI/bench tables are gone.
- **Predictions v2 (goal-or-assist, Target log, player snapshots, Scorecard):** `build_predictions` also returns `gi` (chance of a goal or an assist), `chances` (name|club -> [goal%, assist%, either%] for every player with xP >= 1, shown on each Target card) and the rows behind a per-player snapshot. `_predictions()` saves, per gameweek, the model's five top-10s plus the Target tab's 1-GW top 10 (`pred_track.TARGET`) into `prediction_log.json`, and one row per relevant player (inputs, chances, Target rank/score; `PLAYER_COLS`) into the shared `player_log.json`; once FPL settles the gameweek `grade()` marks the Target picks three ways (scored / assisted / either, `grade_target`) and `player_grade()` appends minutes, goals, assists, DEFCON and points (`OUTCOME_COLS`). More > Scorecard compares the model's top 10 with Target's top 10 on the same gameweeks (`labScorecard`, `view()["target"]` and `model_same_weeks`). The live box also tracks the goal-or-assist list and the Target top 10. `docs/prediction_investigations.md` holds the Manzambi / Iwobi analysis behind this.
- **The Plan tab's live card is a squad view** (`liveBar`): your XI on a pitch with each player's live points (C doubled, bonus so far, "–" = yet to play), the bench with points, a strip of live scores and a summary row. `live_update.team_snapshot` now carries `id`, `club`, `pos` and the vice flag per player so the shirts can be drawn.
- **Predicted rotations are saved, tracked live and graded:** the Predictions rotation list (with player ids) goes into `prediction_log.json` under `rotation`; the live box shows each one as it plays (not started / benched / started and off early / full game) and `pred_track.grade_rotation` marks it once settled (rotated = did not start, or played under 60 minutes); the rate is shown as a Rotation box in the track record but is not part of the recalibration. GW7 has no saved rotation picks (they were not logged before GW8).
- **Goal or assist leads; attacking points added:** the Predictions page now opens its lists with "Goal or assist" (chance of either), then "Attacking points" (expected FPL points: goals x 6/6/5/4 + assists x 3, `ai_run.build_predictions` -> `ap`), then Goals and Assists. The `ap` top 10 is saved in the log and graded with the actual attacking points made (`pred_track.atk_pts`); `view()["points"]` gives mean attacking points per pick for the model's lists and for Target over the same gameweeks, shown on the Scorecard and as a line in the track record. The live box tracks `ap` too ("4 pts (exp 3.8)").
- **The Plan tab's live card only shows while a gameweek is under way** (`labLiveOn`): at least one match has kicked off and at least one has not finished, and the snapshot is not of an earlier gameweek. When the last match ends it hides; it comes back when the next gameweek's first match starts. `live_update.live_gameweek` prefers the gameweek with a match in play, so a new gameweek takes over even if FPL has not settled the previous one yet.
- **Process grading (shots / chances).** The model's goal and assist chances are xG/xA based (FPL season + Understat last 4). Understat shot data is now also used to grade on process: `understat.gw_process` sums each player's shots, shots on target, big chances (xG >= 0.3), chances created and big chances created over a gameweek's matches (needs the match in the 7-match cache, so grading must run soon after the gameweek settles); `pred_track.add_process` attaches it to graded goals / assists / gi / ap / Target results and flags a miss as `near` (shots on target or a big chance for goals; a big chance created or 2+ chances created for assists). `view()["near"]` -> "Missed but created chances" line in the track record; the result's `why` ends "· but 4 shots (2 on target), 1 big chance". Predictions rows show the last-4-appearance volume (`vol`), and `player_log.json` stores it (`sh4 sot4 big4 cc4 bcc4`). Not yet in the probability itself (xG already contains shot quality): test on the logged data before adding.
- **Predictions rows are name + club + figure; the detail is behind an ⓘ button** (`.lab-inf`, one delegated click handler in `dashboard-common.js` toggles the row's `.s` line). Graded "How GW N went" rows keep their reason visible.
- **Predictions: one attacking table.** The Goal or assist / Attacking points / Goals / Assists lists are merged into one table (`labPred` -> `atkTable`: union of the four top-10s, columns G, A, AP, G/A, sorted by G/A, abbreviation key underneath, ⓘ opens a detail row). The four lists are still saved and graded separately in `prediction_log.json`.
- **Recent minutes include a gameweek as soon as the club's own matches are over** (`ai_run.model_inputs`): FPL only marks a gameweek `finished` after its checks, so a player who sat out a just-played match (Cherki, GW7) used to look like a regular for another day. A club counts for a gameweek once every one of its fixtures there is `finished_provisional`.
- **Target only recommends players likely to start** (`ai_run.start_chance`, applied in `enrich_with_model`): chance of starting = 40% season starts per gameweek + 60% his last three gameweeks (60+ minutes counts as a start, the latest game weighs 50%), times fitness and the rest / reported-rotation factors. The figure is the lower of that and the Predictions rotation list's own number (`rotation_start`: minutes share x fitness x every model factor), so the two pages agree. Below 50% (`START_FLOOR`) a player is removed from the Target 1/3/6 lists; below 75% (`START_WARN`) he gets a "Rotation risk · starts ~N%" tag; every row carries `start`. Target picks are graded on `started` too (`grade_target`, shown on the Scorecard). The wildcard top 3 and the transfer-target tables are not gated yet.
- **Target order = expected points over the horizon (`xp`), then the rule score** (`enrich_with_model` sorts after the start gate). `xp` already carries minutes, rotation, fitness, fixtures, bookmaker odds and the capped news / ownership / price signals; the score's reason tags stay as the explanation.

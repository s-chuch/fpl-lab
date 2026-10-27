# Chasing points, FPL's form forecast and the free-transfer hurdle (backtest, 27 Oct 2026)

Script: `python calibrate_decisions.py` (all tests) and `python calibrate_decisions.py --chasing`; raw numbers in `decision_backtest.json`.
Data: vaastav FPL history 2024-25 and 2025-26, GW6 on, players with 270+ prior minutes (about 11.4k player-gameweeks a season). The model is the
simplified backtest version of `ai_team.model_xp` (FDR 3, no Understat / rest / odds), so absolute numbers are indicative, not the live model.

## What "chasing points" is
Buying a player after a big week. Research (FantasyFootballGeek's 20-player test, Fantasy Football Scout's "why does good form end", the 2019 form-streak
analysis) agrees on the mechanism, regression to the mean, and finds hauls are a coin flip as a buy signal: after a 10+ point week the next six games beat
the player's season average about 50% of the time. Nothing there is a rigorous out-of-sample test, so we ran one.

## Findings
1. **After a 10+ point week FPL's form forecast is far too high; our model is close.** Next-gameweek points of players who had just scored 10+:
   2024-25 actual 3.9 (n=377) against model 3.1 and FPL form 6.1; 2025-26 actual 3.5 (n=452) against model 3.1 and form 5.9. Form overshoots by ~2.3 points
   (it keeps about 60% of the haul), the model undershoots by 0.4-0.8. That is the chasing trap, and it is why raw form must not drive decisions.
2. **At the live 20% weight, form is not chasing on average.** Blending 0.2 x form with 0.8 x model leaves a bias of -0.23 (2024-25) and +0.12 (2025-26)
   points for players after a haul, because the model's slight undershoot cancels form's overshoot. MAE improves marginally (1.815 to 1.790 and 1.973 to 1.944);
   what the top-rated players actually score (captain / transfer use) moves by less than one standard error between w = 0 and 0.3, and gets worse at 0.4+
   in 2025-26. Capping form at 1.25-1.5x the model's own number changes nothing measurable. **Decision: `EP_NEXT_WEIGHT` stays 0.2.**
3. **The recent xG/xA window (0.45 weight in the model) is not harmful**: MAE falls slightly as its weight rises (1.805 at 0.45, 1.800 at 1.0). Unchanged.
4. **Predicted swap gains are real.** For every predicted-gain bin the realised gain (this gameweek + 0.35 x next) is about equal to the prediction
   (all pairs: 0.6-1.0 predicted -> 0.5-0.8 realised, 1.5-2.5 -> 1.4-1.8, 2.5-4 -> 2.3-3.0, 4+ -> 3.6-4.5). No winner's-curse correction is needed
   (and the learned `transfers` hurdle multiplier stays off until the AI's own moves show otherwise).
5. **A banked free transfer is worth about 2.5 points.** In a squad drawn from the better half of each position, the best swap realised 2.6-3.5 and the
   *second*-best 2.1-2.7 (se 0.12), i.e. what the extra transfer next week buys. A swap predicted at 0.6-1.5 therefore gives up more than it gains. **Decision:
   a free transfer needs `FREE_HURDLE` = 1.5 expected points (capped well below the measured 2.5 because squads in the sample were not optimised); the old 0.6
   applies only when the bank is already full (5), where waiting wastes one.** `KEEP_FLOOR` follows (0.75); `HYSTERESIS` stays 0.6.
6. Caveat found on the way: the 2025-26 file's `xP` column is on a different scale (mean 0.3-0.9 against 2-4 points), so tests that used FPL's real `xP` in
   2025-26 are not valid; the live `ep_next` equals `form` anyway, so the form tests above are the relevant ones.

## What it means for Calafiori -> Gabriel (GW9)
Gain +3.7 clears the new 1.5 hurdle, so that move still happens: it rests on Calafiori's 75% hip doubt and Gabriel's defensive-contribution rate (9.0 vs 4.0 per 90),
not on chasing his 17-point week. What stops changing is the 0.6-1.5 band of marginal swaps.

# Prediction investigations (log)

Findings worth keeping for when the prediction model is tuned. Newest first. Numbers are from the committed data and FPL's API at the time.

## 2026-10-17 · GW7 · Target vs Predictions: Manzambi, Iwobi and others

**Question.** Target recommended Manzambi for two gameweeks and he scored; Predictions never listed him. Iwobi was Target #1 and also scored. Why do the two sections disagree, and does it matter?

**Why they differ.** Target is a buy list (score = form, xGI per 90, value, fixtures, ownership/differential, news; small samples count fully). Predictions ranks one gameweek's chance of an event among ~430 players using shrunk per-90 rates x fixture x minutes.

**Manzambi (AVL, MID, 5.9m, 2.1% owned).**
- 226 minutes, 3 starts in 7 gameweeks; recent minutes 27, 71, 85 (rising); form 9.0; xG/90 0.55, xA/90 0.17; 2 goals, 2 assists.
- Target: 1-GW rank 4 (score 4), 3-GW and 6-GW rank 2.
- Predictions GW8: 16% to score, 49th of 433 (10th place needs ~30%). Even as a certain starter he would be 39th: GW8 is Man City at home (difficulty 4).
- Causes: (1) small sample, so xG/90 is shrunk towards the average (weight 0.45 after 226 minutes); (2) minutes share 0.52 = half season share (0.36) + half last-3 average (0.68), which undersells a player whose minutes are rising; (3) hard fixture.
- Understat window (3 apps): 11 shots, 3 on target, xG 1.26, 1 goal, xA 0.63, 2 assists.

**Iwobi (FUL, MID).**
- 584 minutes, xG 0.70, xA 2.36, 1 goal and 0 assists before GW7; form 6.7; 0.8% owned.
- Target: 1-GW rank 1 (score 5).
- Predictions GW8: 15% goal (50th) but 34% assist (2nd). He scored in GW7 (a roughly 1-in-7 event). His assists (0 from xA 2.36) are the thing that looks due.
- A creator, so a combined goal-or-assist chance (~44%) describes him better than either list alone.

**GW7 scorers on a Target list (provisional, gameweek not finished):** Neto (2), Iwobi, Manzambi, Isak, Foden. Only Neto and Foden were on the old-method goal list; Iwobi and Isak are in the GW8 top 10 (Iwobi for assists). One gameweek is not evidence either way.

**Ideas, in order of cost**
1. Weight recent minutes harder: if a player had 60+ minutes in each of the last two gameweeks, treat him as a starter. Test it as a second version and compare hit rates rather than changing the main numbers.
2. Show the Predictions chance on each Target card so the two sections stop looking contradictory.
3. Add a combined "goal or assist" list (separate goal and assist lists stay, graded separately).
4. Log Target's top 10 beside the Predictions top 10 each gameweek and grade both: which is the better scorer-spotter over 3-4 gameweeks.
5. Log a per-player feature snapshot at each deadline (inputs, Target score, model chances) with the outcome, so the shrinkage, minutes and fixture weights can be fitted on this season's own data.

"""Offline tests for the Scout-style recent-volume weight and the set-piece boosts in ai_team.model_xp / model_outlook.
Run with:  python -m unittest discover -s tests"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_team
import understat

FX = [{"fdr": 3, "opp": "X", "side": "H"}]
FWD = {"element_type": 4, "minutes": 720, "expected_goals_per_90": 0.40, "expected_assists_per_90": 0.10, "clean_sheets_per_90": 0.0,
       "status": "a", "chance_of_playing_next_round": None}
# a window as understat.player_windows builds it (the keys the model reads)
QUIET = {"apps": 4, "shots": 6, "sot": 3, "big": 1, "goals": 0, "xg": 1.0, "cc": 3, "big_cc": 0, "assists": 0, "xa": 0.3, "pens": 0, "pen_xg": 0.0}


def w(**kw):
    return {**QUIET, **kw}


class RecentWeight(unittest.TestCase):
    def test_boost_fires_on_many_shots_and_few_goals(self):
        self.assertAlmostEqual(ai_team.recent_weight(w(shots=10, goals=1)), 0.45 + 0.18)
        self.assertAlmostEqual(ai_team.recent_weight(w(shots=14, goals=0)), 0.63)

    def test_boost_fires_on_many_chances_and_few_assists(self):
        self.assertAlmostEqual(ai_team.recent_weight(w(cc=8, assists=1)), 0.63)
        self.assertAlmostEqual(ai_team.recent_weight(w(cc=19, assists=0)), 0.63)

    def test_no_boost_otherwise(self):
        self.assertEqual(ai_team.recent_weight(QUIET), 0.45)
        self.assertEqual(ai_team.recent_weight(w(shots=9, goals=0)), 0.45)            # not enough shots
        self.assertEqual(ai_team.recent_weight(w(shots=12, goals=2)), 0.45)           # converting: nothing "due"
        self.assertEqual(ai_team.recent_weight(w(cc=7, assists=0)), 0.45)             # not enough chances
        self.assertEqual(ai_team.recent_weight(w(cc=12, assists=2)), 0.45)
        self.assertEqual(ai_team.recent_weight(None), 0.45)
        self.assertEqual(ai_team.recent_weight({}), 0.45)
        self.assertEqual(ai_team.recent_weight({"apps": 0, "shots": 20}), 0.45)

    def test_weight_is_capped_at_070(self):
        self.assertAlmostEqual(ai_team.recent_weight(w(shots=15, cc=15)), 0.63)      # both conditions still add the boost once
        old = ai_team.RECENT_VOLUME_WEIGHT_BOOST
        try:
            ai_team.RECENT_VOLUME_WEIGHT_BOOST = 0.60
            self.assertEqual(ai_team.recent_weight(w(shots=15)), 0.70)
        finally:
            ai_team.RECENT_VOLUME_WEIGHT_BOOST = old

    def test_blend_uses_the_weight(self):
        hi = w(shots=12, goals=0, xg=2.4, xa=0.8)           # 0.6 xG and 0.2 xA per appearance
        xg, xa = ai_team.blend_recent(0.30, 0.10, hi)
        self.assertAlmostEqual(xg, 0.37 * 0.30 + 0.63 * 0.6)
        self.assertAlmostEqual(xa, 0.37 * 0.10 + 0.63 * 0.2)
        lo = w(xg=2.4, xa=0.8)
        xg, xa = ai_team.blend_recent(0.30, 0.10, lo)
        self.assertAlmostEqual(xg, 0.55 * 0.30 + 0.45 * 0.6)       # unchanged old behaviour
        self.assertEqual(ai_team.blend_recent(0.30, 0.10, None), (0.30, 0.10))

    def test_understat_window_carries_every_key_the_model_reads(self):
        shots = [["Striker", "", "SavedShot", 0.2, "h"], ["Striker", "", "Goal", 0.761, "h"], ["Striker", "", "MissedShots", 0.05, "h"],
                 ["Mate", "Striker", "Goal", 0.3, "h"], ["Striker", "", "MissedShots", 0.752, "h"]]
        fetched = ([{"id": "1", "datetime": "2026-10-01 12:00:00", "h": {"title": "A"}, "a": {"title": "B"}}],
                   {"1": {"shots": shots, "mins": {"Striker": "h", "Mate": "h"}}})
        win = understat.player_windows(fetched=fetched)["Striker"]
        for k in ("apps", "shots", "goals", "xg", "cc", "assists", "xa", "pens", "pen_xg"):
            self.assertIn(k, win)
        self.assertEqual((win["shots"], win["goals"], win["cc"], win["assists"], win["pens"]), (4, 1, 1, 1, 1))   # cc/assists: Striker also assisted Mate (the 4th row has "player_assisted" = Striker)
        self.assertAlmostEqual(win["pen_xg"], 0.761)          # only the penalty; the 0.752 shot is not one

    def test_helper_is_the_one_both_functions_use(self):
        hi = w(shots=12, goals=0, xg=3.0, xa=0.4)
        calls = []
        real = ai_team.blend_recent
        ai_team.blend_recent = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
        try:
            ai_team.model_xp(FWD, FX, 8, hi)
            ai_team.model_outlook(FWD, FX, 8, hi)
        finally:
            ai_team.blend_recent = real
        self.assertEqual(len(calls), 2)

    def test_model_xp_and_outlook_both_move_with_volume(self):
        hi = w(shots=12, goals=0, xg=3.0, xa=0.4)      # 0.75 xG per appearance vs a 0.40 season rate
        lo = {**hi, "shots": 6}
        self.assertGreater(ai_team.model_xp(FWD, FX, 8, hi), ai_team.model_xp(FWD, FX, 8, lo))
        self.assertGreater(ai_team.model_outlook(FWD, FX, 8, hi)["goals"], ai_team.model_outlook(FWD, FX, 8, lo)["goals"])

    def test_outlook_goals_match_the_blend_exactly(self):
        hi = w(shots=12, goals=0, xg=3.0, xa=0.4)
        o = ai_team.model_outlook(FWD, FX, 8, hi)
        w_ = min(1.0, 720 / ai_team.SHRINK_MINUTES)
        base = w_ * 0.40 + (1 - w_) * ai_team.PRIOR["FWD"]["xg"]
        want = ((1 - 0.63) * base + 0.63 * 0.75) * (1.12 - 0.06 * 3) * o["mp"]
        self.assertAlmostEqual(o["goals"], want, places=6)


class SetPieces(unittest.TestCase):
    TAKER = {**FWD, "penalties_order": 1}

    def test_non_takers_get_nothing(self):
        self.assertEqual(ai_team.set_piece_boosts(FWD, "FWD", QUIET), (0.0, 0.0))
        self.assertEqual(ai_team.set_piece_boosts({**FWD, "penalties_order": 2, "corners_and_indirect_freekicks_order": 2}, "FWD", QUIET), (0.0, 0.0))
        self.assertEqual(ai_team.set_piece_boosts({**FWD, "penalties_order": None}, "FWD", QUIET), (0.0, 0.0))

    def test_primary_penalty_taker_gets_the_capped_boost(self):
        pk, corner = ai_team.set_piece_boosts(self.TAKER, "FWD", QUIET)
        self.assertEqual((pk, corner), (ai_team.PENALTY_TAKER_XG_BOOST, 0.0))
        self.assertLessEqual(pk, ai_team.PENALTY_TAKER_XG_BOOST)

    def test_penalty_already_in_his_recent_rate_is_not_counted_twice(self):
        took_one = w(pens=1, pen_xg=0.761)                    # 0.19 penalty xG per appearance >= the 0.12 boost
        self.assertEqual(ai_team.set_piece_boosts(self.TAKER, "FWD", took_one)[0], 0.0)
        part = w(pens=1, pen_xg=0.761, apps=8)                # 0.095 per appearance already in: only the remainder
        self.assertAlmostEqual(ai_team.set_piece_boosts(self.TAKER, "FWD", part)[0], 0.12 - 0.761 / 8)

    def test_no_window_or_unknown_penalty_info_means_no_penalty_boost(self):
        self.assertEqual(ai_team.set_piece_boosts(self.TAKER, "FWD", None)[0], 0.0)
        no_info = {k: v for k, v in QUIET.items() if k != "pen_xg"}
        self.assertEqual(ai_team.set_piece_boosts(self.TAKER, "FWD", no_info)[0], 0.0)

    def test_corner_taker_gets_the_small_xa_boost(self):
        el = {**FWD, "corners_and_indirect_freekicks_order": 1}
        self.assertEqual(ai_team.set_piece_boosts(el, "MID", None), (0.0, ai_team.CORNER_TAKER_XA_BOOST))

    def test_keepers_get_nothing(self):
        gk = {"element_type": 1, "penalties_order": 1, "corners_and_indirect_freekicks_order": 1}
        self.assertEqual(ai_team.set_piece_boosts(gk, "GKP", QUIET), (0.0, 0.0))

    def test_total_boost_is_small(self):
        both = {**FWD, "penalties_order": 1, "corners_and_indirect_freekicks_order": 1}
        base = ai_team.model_xp(FWD, FX, 8, QUIET)
        with_sp = ai_team.model_xp(both, FX, 8, QUIET)
        extra = with_sp - base
        self.assertGreater(extra, 0)
        self.assertLessEqual(extra, ai_team.PENALTY_TAKER_XG_BOOST * ai_team.GOAL_PTS["FWD"] + ai_team.CORNER_TAKER_XA_BOOST * 3 + 1e-9)

    def test_boost_adds_to_xp_and_to_outlook_goals_and_assists(self):
        both = {**FWD, "penalties_order": 1, "corners_and_indirect_freekicks_order": 1}
        a, b = ai_team.model_outlook(FWD, FX, 8, QUIET), ai_team.model_outlook(both, FX, 8, QUIET)
        scale = (1.12 - 0.06 * 3) * a["mp"]
        self.assertAlmostEqual(b["goals"] - a["goals"], 0.12 * scale, places=6)
        self.assertAlmostEqual(b["assists"] - a["assists"], 0.08 * scale, places=6)

    def test_boost_is_scaled_by_minutes_and_gone_for_unavailable_players(self):
        taker = {**self.TAKER, "corners_and_indirect_freekicks_order": 1}
        none = {"minutes": 0}
        self.assertEqual(ai_team.model_xp({**taker, **none}, FX, 8, QUIET), 0.0)           # no minutes: nothing, boost included
        self.assertEqual(ai_team.model_outlook({**taker, **none}, FX, 8, QUIET)["goals"], 0.0)
        self.assertEqual(ai_team.model_xp(taker, [], 8, QUIET), 0.0)                       # blank gameweek
        boot = {"teams": [{"id": 1, "short_name": "AAA"}],
                "elements": [{**taker, "id": 1, "team": 1, "web_name": "Out", "now_cost": 80, "selected_by_percent": "5", "status": "i", "chance_of_playing_next_round": 0,
                              "chance_of_playing_this_round": 0, "news": "Injured", "bonus": 0},
                             {**taker, "id": 2, "team": 1, "web_name": "Fit", "now_cost": 80, "selected_by_percent": "5", "status": "a", "news": "", "bonus": 0}]}
        vals = ai_team.player_values(boot, {1: FX}, {1: FX}, 8, {1: QUIET, 2: QUIET}, None)
        self.assertEqual(vals[1]["xp"], 0.0)
        self.assertGreater(vals[2]["xp"], 0.0)


if __name__ == "__main__":
    unittest.main()

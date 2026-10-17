import unittest
from datetime import datetime, timezone
import pred_track as pt

EL = {1: {"id": 1, "team": 10, "element_type": 3}, 2: {"id": 2, "team": 10, "element_type": 2}}
FX = [{"team_h": 10, "team_a": 20, "team_h_score": 2, "team_a_score": 0, "finished": True}]


class Grade(unittest.TestCase):
    def test_goal_hit_and_misses(self):
        live = {1: {"minutes": 90, "goals_scored": 1}, 2: {"minutes": 0}}
        self.assertTrue(pt.grade_pick("goals", {"id": 1}, live, FX, EL)["hit"])
        r = pt.grade_pick("goals", {"id": 2}, live, FX, EL)
        self.assertFalse(r["hit"]); self.assertEqual(r["why"], "did not play")
        r = pt.grade_pick("assists", {"id": 1}, {1: {"minutes": 90, "assists": 0}}, FX, EL)
        self.assertIn("team scored 2", r["why"])

    def test_clean_sheet_and_defcon(self):
        self.assertTrue(pt.grade_pick("clean_sheets", {"team": 10}, {}, FX, EL)["hit"])
        r = pt.grade_pick("clean_sheets", {"team": 20}, {}, FX, EL)
        self.assertFalse(r["hit"]); self.assertEqual(r["why"], "conceded 2")
        self.assertTrue(pt.grade_pick("defcon", {"id": 2}, {2: {"minutes": 90, "defensive_contribution": 10}}, FX, EL)["hit"])   # DEF needs 10
        r = pt.grade_pick("defcon", {"id": 1}, {1: {"minutes": 90, "defensive_contribution": 10}}, FX, EL)                      # MID needs 12
        self.assertFalse(r["hit"]); self.assertEqual(r["why"], "10 of 12 contributions")


class Calibration(unittest.TestCase):
    def log(self, n, hits, p):
        picks = [{"id": i, "p": p, "raw": p} for i in range(n)]
        res = [{"hit": i < hits, "why": ""} for i in range(n)]
        return {"gws": {"8": {"gw": 8, "graded": True, "picks": {"goals": picks}, "results": {"goals": res}}}}

    def test_no_scale_until_enough_picks(self):
        self.assertEqual(pt.scales(self.log(10, 2, 40))["goals"], 1.0)

    def test_overconfident_model_is_scaled_down_and_bounded(self):
        s = pt.scales(self.log(40, 8, 40))["goals"]          # predicted 40%, hit 20%
        self.assertTrue(pt.SCALE_RANGE[0] <= s < 1.0)
        self.assertGreaterEqual(pt.scales(self.log(40, 0, 40))["goals"], pt.SCALE_RANGE[0])

    def test_record_keeps_graded_gameweek(self):
        log = {"gws": {"8": {"gw": 8, "graded": True, "picks": {"goals": []}}}}
        pt.record(log, 8, {"goals": [{"id": 1}]}, datetime.now(timezone.utc))
        self.assertEqual(log["gws"]["8"]["picks"]["goals"], [])
        pt.record(log, 9, {"goals": [{"id": 1}]}, datetime.now(timezone.utc))
        self.assertFalse(log["gws"]["9"]["graded"])

    def test_view_counts_and_reasons(self):
        log = self.log(10, 3, 40)
        log["gws"]["8"]["results"]["goals"][5] = {"hit": False, "why": "did not play"}
        v = pt.view(log)
        self.assertEqual(v["per_gw"][0]["goals"], [3, 10])
        self.assertIn(("did not play or played under an hour", 1), v["why"]["goals"])


class Legacy(unittest.TestCase):
    def test_legacy_view_totals_played_only(self):
        vl = {"gw3": {"gw": 3, "graded": True, "backfilled": True, "flags": [
            {"kind": "goal", "played": True, "got": 1}, {"kind": "goal", "played": True, "got": 0}, {"kind": "goal", "played": False, "got": 0},
            {"kind": "assist", "played": True, "got": 0}]}}
        leg = {"gws": {"6": {"gw": 6, "graded": True, "results": {"defcon": [{"hit": True}, {"hit": False}]}}, "7": {"gw": 7, "graded": False}}}
        v = pt.legacy_view(leg, vl)
        self.assertEqual(v["total"], {"goals": [1, 2], "assists": [0, 1], "defcon": [1, 2]})
        self.assertEqual(v["pending"], [7])
        self.assertTrue(v["goals_assists"][0]["rebuilt"])


class TargetAndGi(unittest.TestCase):
    def test_gi_pick_hits_on_goal_or_assist(self):
        live = {1: {"minutes": 90, "goals_scored": 0, "assists": 1}}
        self.assertTrue(pt.grade_pick("gi", {"id": 1}, live, FX, EL)["hit"])
        r = pt.grade_pick("gi", {"id": 1}, {1: {"minutes": 90}}, FX, EL)
        self.assertFalse(r["hit"]); self.assertIn("no goal or assist", r["why"])

    def test_target_is_graded_three_ways_and_compared(self):
        log = {"gws": {"8": {"gw": 8, "graded": True, "picks": {"goals": [{"id": 1}], "target": [{"id": 1}, {"id": 2}]},
                             "results": {"goals": [{"hit": True, "why": ""}], "target": [pt.grade_target({"id": 1}, {1: {"minutes": 90, "goals_scored": 1}}),
                                                                                           pt.grade_target({"id": 2}, {2: {"minutes": 0}})]}}}}
        v = pt.view(log)
        self.assertEqual((v["target"]["n"], v["target"]["goal"], v["target"]["gi"]), (2, 1, 1))
        self.assertEqual(v["model_same_weeks"]["goals"], [1, 1])


if __name__ == "__main__":
    unittest.main()

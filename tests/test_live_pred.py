import unittest
import live_update as lu


class PredLive(unittest.TestCase):
    def test_goal_defcon_and_clean_sheet_states(self):
        els = {1: {"id": 1, "team": 10, "element_type": 4, "web_name": "A"}, 2: {"id": 2, "team": 20, "element_type": 2, "web_name": "B"}}
        live = {1: {"goals_scored": 1, "minutes": 60}, 2: {"defensive_contribution": 7, "minutes": 50}}
        fx = [{"team_h": 10, "team_a": 20, "team_h_score": 1, "team_a_score": 0, "started": True, "finished": False, "minutes": 55}]
        orig = lu.pred_picks
        lu.pred_picks = lambda gw, boot: ("test", {"goals": [{"id": 1, "name": "A", "club": "X"}], "assists": [], "defcon": [{"id": 2, "name": "B", "club": "Y"}],
                                                    "clean_sheets": [{"team": 20, "club": "Y"}]})
        try:
            out = lu.pred_live(7, {}, live, fx, els)["cats"]
        finally:
            lu.pred_picks = orig
        self.assertTrue(out["goals"][0]["hit"]); self.assertEqual(out["goals"][0]["state"], "live")
        self.assertFalse(out["defcon"][0]["hit"]); self.assertEqual((out["defcon"][0]["val"], out["defcon"][0]["need"]), (7, 10))
        self.assertEqual(out["clean_sheets"][0]["val"], 1); self.assertFalse(out["clean_sheets"][0]["hit"])


    def test_rotation_states(self):
        els = {i: {"id": i, "team": 10, "element_type": 3, "web_name": f"P{i}"} for i in (1, 2, 3)}
        live = {1: {"starts": 0, "minutes": 0}, 2: {"starts": 1, "minutes": 50}, 3: {"starts": 1, "minutes": 90}}
        fx_done = [{"team_h": 10, "team_a": 20, "team_h_score": 0, "team_a_score": 0, "started": True, "finished": True, "finished_provisional": True, "minutes": 90}]
        fx_live = [{"team_h": 10, "team_a": 20, "started": True, "finished": False, "minutes": 30}]
        orig = lu.pred_picks
        lu.pred_picks = lambda gw, boot: ("t", {"rotation": [{"id": 1, "name": "P1", "club": "X"}, {"id": 2, "name": "P2", "club": "X"}, {"id": 3, "name": "P3", "club": "X"}]})
        try:
            done = lu.pred_live(7, {}, live, fx_done, els)["cats"]["rotation"]
            mid = lu.pred_live(7, {}, live, fx_live, els)["cats"]["rotation"]
        finally:
            lu.pred_picks = orig
        self.assertEqual([r["hit"] for r in done], [True, True, False])      # benched, off early, full game
        self.assertEqual([r["hit"] for r in mid], [True, False, False])      # benched is known once the match is on; the others are still playing


if __name__ == "__main__":
    unittest.main()

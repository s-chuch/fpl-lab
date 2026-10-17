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


class LiveGw(unittest.TestCase):
    NOW = lu.datetime(2026, 10, 25, 12, 0, tzinfo=lu.timezone.utc)

    def boot(self):
        ev = lambda i, fin, chk, dl: {"id": i, "finished": fin, "data_checked": chk, "deadline_time": dl}
        return {"events": [ev(7, True, False, "2026-10-17T10:00:00Z"), ev(8, False, False, "2026-10-23T17:30:00Z"), ev(9, False, False, "2026-11-01T10:00:00Z")]}

    def test_new_gameweek_takes_over_from_an_unsettled_one(self):
        fx = [{"event": 7, "started": True, "finished": True}, {"event": 8, "started": True, "finished": False}]
        self.assertEqual(lu.live_gameweek(self.boot(), fx, self.NOW), 8)

    def test_unsettled_finished_gameweek_stays_until_settled(self):
        fx = [{"event": 7, "started": True, "finished": True}, {"event": 8, "started": False, "finished": False}]
        self.assertEqual(lu.live_gameweek(self.boot(), fx, self.NOW), 7)

    def test_nothing_started_is_none(self):
        self.assertIsNone(lu.live_gameweek({"events": [{"id": 9, "finished": False, "data_checked": False, "deadline_time": "2026-11-01T10:00:00Z"}]}, [], self.NOW))


if __name__ == "__main__":
    unittest.main()

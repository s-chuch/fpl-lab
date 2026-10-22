import unittest
import learn
import start_model as S

REG = {"minutes": 600, "starts": 7, "status": "a", "chance_of_playing_next_round": None, "news": ""}
FIT3 = [{"min": 90, "starts": 1}, {"min": 84, "starts": 1}, {"min": 90, "starts": 1}]


class StartModel(unittest.TestCase):
    def test_regular_starts_and_more_minutes_means_more_likely(self):
        full = S.start_prob(REG, FIT3, 7)["p"]
        benched = S.start_prob(REG, [{"min": 90, "starts": 1}, {"min": 90, "starts": 1}, {"min": 0, "starts": 0}], 7)["p"]
        sub = S.start_prob({"minutes": 200, "starts": 1, "status": "a"}, [{"min": 20, "starts": 0}] * 3, 7)["p"]
        self.assertGreater(full, 0.85)
        self.assertGreater(full, benched)
        self.assertGreater(benched, sub)
        self.assertLess(sub, 0.35)

    def test_doubt_ordering_and_fit_unchanged(self):
        def p(c):
            return S.start_prob({**REG, "status": "d" if c < 100 else "a", "chance_of_playing_next_round": c}, FIT3, 7)["p"]
        self.assertAlmostEqual(p(100), S.start_prob(REG, FIT3, 7)["p"])
        self.assertGreater(p(100), p(75)); self.assertGreater(p(75), p(50)); self.assertGreater(p(50), p(25)); self.assertGreater(p(25), p(0) - 1e-9)
        self.assertLess(p(50), 0.5 * p(100) + 1e-9)       # a 50% doubt starts less than half as often as a fit regular
        self.assertEqual(S.start_prob({**REG, "status": "i", "chance_of_playing_next_round": 0}, FIT3, 7)["p"], 0.0)

    def test_reported_rotation_and_new_players(self):
        self.assertAlmostEqual(S.start_prob(REG, FIT3, 7, 0.8)["p"], 0.8 * S.start_prob(REG, FIT3, 7)["p"])
        new = S.start_prob({"minutes": 90, "starts": 1, "status": "a"}, [], 7)["p"]       # too little history: falls back to his season share
        self.assertLess(new, 0.3)

    def test_learned_band_multiplier_is_applied_and_logged_value_is_not(self):
        r = S.start_prob({**REG, "status": "d", "chance_of_playing_next_round": 50}, FIT3, 7, learned={"50": 1.2})
        self.assertAlmostEqual(r["p"], min(1.0, r["raw"] * 1.2))
        self.assertEqual(S.band_of(50), "50"); self.assertEqual(S.band_of(100), None); self.assertEqual(S.band_of(20), "25")

    def test_model_file_beats_the_old_formulas_on_holdout(self):
        m = S.MODEL["metrics"]
        self.assertLess(m["brier_model"], m["brier_minutes_share"])
        self.assertLess(m["brier_model"], m["brier_starts_blend"])


class LearnStart(unittest.TestCase):
    def _log(self, n, pred, actual_rate, avail):
        rows = [[avail, pred, 1 if i < actual_rate * n else 0] for i in range(n)]
        return {"gws": {"9": {"gw": 9, "graded": True, "cols": ["avail", "p_start", "o_start"], "rows": rows}}}

    def test_too_few_doubted_rows_do_not_change_anything(self):
        per, cal = learn.fit_start(self._log(10, 0.35, 0.0, 0.5))
        self.assertFalse(per["50"]["applied"])

    def test_overrated_doubt_band_is_pulled_down_within_bounds(self):
        per, cal = learn.fit_start(self._log(200, 0.35, 0.1, 0.5))      # said 35%, happened 10%
        self.assertTrue(per["50"]["applied"])
        self.assertLess(per["50"]["mult"], 1.0)
        self.assertGreaterEqual(per["50"]["mult"], 0.5)
        self.assertEqual(cal["n"], 200)


if __name__ == "__main__":
    unittest.main()

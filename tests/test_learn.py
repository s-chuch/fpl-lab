import random
import unittest
import learn


def _log(n_per_pos, slope, shift, gws=(8, 9)):
    random.seed(1)
    cols = ["id", "pos", "xp", "o_min", "o_pts"]
    out = {"gws": {}}
    for gw in gws:
        rows = []
        for pos in learn.POSITIONS:
            for i in range(n_per_pos):
                x = random.uniform(1, 8)
                rows.append([i, pos, x, 90, max(0.0, shift + slope * x + random.gauss(0, 2))])
        out["gws"][str(gw)] = {"gw": gw, "graded": True, "cols": cols, "rows": rows}
    return out


class Learn(unittest.TestCase):
    def test_no_evidence_means_no_change(self):
        d = learn.fit(_log(5, 0.6, 0.0))
        self.assertFalse(d["applied"])
        for r in d["per_position"].values():
            self.assertEqual((r["a"], r["b"]), (0.0, 1.0))

    def test_overrated_model_is_pulled_down_but_bounded(self):
        d = learn.fit(_log(300, 0.6, 0.0))      # reality is 60% of what the model says
        for r in d["per_position"].values():
            self.assertTrue(r["applied"])
            self.assertGreaterEqual(r["b"], 0.7)
            self.assertLess(r["b"], 1.0)
        self.assertLess(d["mae_after"], d["mae_before"])

    def test_calibrated_model_stays_put(self):
        d = learn.fit(_log(300, 1.0, 0.0))
        for r in d["per_position"].values():
            self.assertAlmostEqual(r["b"], 1.0, delta=0.1)
            self.assertLess(abs(r["a"]), 0.35)

    def test_ungraded_rows_are_ignored(self):
        log = _log(300, 0.6, 0.0)
        for g in log["gws"].values():
            g["graded"] = False
        self.assertFalse(learn.fit(log)["applied"])


class Summary(unittest.TestCase):
    def test_per_gameweek_error_and_biggest_misses(self):
        cols = ["id", "pos", "xp", "o_min", "o_pts"]
        log = {"gws": {"8": {"graded": True, "cols": cols, "rows": [
            [1, "DEF", 3.0, 90, 12], [2, "MID", 4.0, 90, -1], [3, "FWD", 5.0, 0, 0], [4, "MID", 2.0, 90, 2]]}}}
        by, misses = learn.gw_summary(log)
        self.assertEqual(by[0]["n"], 4)
        self.assertEqual(misses["under"][0]["id"], 1)            # most points above expectation
        self.assertEqual(misses["over"][0]["id"], 2)             # most below; the player who did not play is left out
        self.assertNotIn(3, [m["id"] for m in misses["over"] + misses["under"]])


class AdjustXp(unittest.TestCase):
    def test_adjust_applies_only_applied_positions_and_keeps_zero(self):
        import ai_team
        old = ai_team.LEARNED
        try:
            ai_team.LEARNED = {"MID": {"a": 0.1, "b": 0.8, "applied": True}}
            self.assertAlmostEqual(ai_team.adjust_xp("MID", 5.0), 4.1)
            self.assertEqual(ai_team.adjust_xp("MID", 0.0), 0.0)
            self.assertEqual(ai_team.adjust_xp("DEF", 5.0), 5.0)
        finally:
            ai_team.LEARNED = old


if __name__ == "__main__":
    unittest.main()

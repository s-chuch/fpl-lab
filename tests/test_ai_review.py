import random
import unittest
import ai_review
import ai_team
import learn


def _plan():
    squad = [{"id": i, "name": f"P{i}", "pos": pos, "xp": xp} for i, (pos, xp) in enumerate(
        [("GKP", 4), ("GKP", 3), ("DEF", 5), ("DEF", 4), ("DEF", 4), ("DEF", 3), ("DEF", 3), ("MID", 6), ("MID", 5), ("MID", 4), ("MID", 3), ("MID", 2),
         ("FWD", 6), ("FWD", 4), ("FWD", 3)], start=1)]
    xi = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    return {"gw": 8, "squad": squad, "xi": xi, "bench": [2, 6, 7, 12], "captain": 8, "vice": 13,
            "transfers": [{"in": "P8", "out": "Old", "in_id": 8, "out_id": 99, "xp_in": 6.0, "xp_out": 2.0, "hit": False}]}


class Review(unittest.TestCase):
    def test_captain_regret_and_transfer_gap(self):
        plan = _plan()
        live = {i: {"minutes": 90, "points": 2} for i in range(1, 16)}
        live[13] = {"minutes": 90, "points": 11}      # the vice hauled
        live[8] = {"minutes": 90, "points": 2}        # the captain did not
        live[99] = {"minutes": 0, "points": 0}        # the player sold did not play
        lines = [{"id": i} for i in plan["xi"]]
        r = ai_review.review(plan, {"final": True, "lines": lines, "bench_pts": 8}, live)
        self.assertEqual(r["captain"]["best"], "P13")
        self.assertEqual(r["captain"]["regret"], (11 - 2) * 1)          # the armband doubles: one extra copy of the gap
        self.assertEqual(r["transfers"][0]["real"], 2)
        self.assertEqual(r["transfers"][0]["pred"], 4.0)
        self.assertGreaterEqual(r["xi"]["hindsight_pts"], r["xi"]["pts"])
        self.assertTrue(any(m["name"] == "P8" and m["cause"] == "played a full game, no returns" for m in r["misses"]))

    def test_totals(self):
        t = ai_review.totals({"8": {"final": True, "captain": {"regret": 6}, "xi": {"regret": 4, "bench_pts": 10}, "transfers": [{"real": 2, "pred": 4.0}]}})
        self.assertEqual((t["captain_regret"], t["xi_regret"], t["bench_pts"], t["moves"]), (6.0, 4.0, 10, 1))


def _rows(n, flag_cols, factor_effect, gw="8"):
    """n graded rows for each flag group; flagged players score `factor_effect` times what the unflagged do."""
    random.seed(3)
    cols = ["id", "pos", "xp", "o_pts", "o_min", "fac", "f_rest", "f_min", "f_rot", "e_own", "e_cap"]
    rows = []
    for i in range(n):
        for flagged in (0, 1):
            base = random.uniform(2, 6)
            fac = 0.93 if flagged else 1.0
            act = base * (factor_effect if flagged else 1.0) + random.gauss(0, 1.0)
            rows.append([len(rows), "MID", base * fac, act, 90, fac, 1 if flagged else 0, 0, 0, None, None])
    return {"gws": {gw: {"graded": True, "cols": cols, "rows": rows}}}


class Learning(unittest.TestCase):
    def test_a_multiplier_is_learned_only_with_enough_flagged_rows(self):
        few = learn.fit_factors(_rows(20, None, 0.7), priors={"rest": 0.93, "minutes": 0.85, "rotation": 0.8})
        self.assertFalse(few["rest"]["applied"])
        many = learn.fit_factors(_rows(400, None, 0.7), priors={"rest": 0.93, "minutes": 0.85, "rotation": 0.8})
        self.assertTrue(many["rest"]["applied"])
        self.assertLess(many["rest"]["factor"], 0.93)          # flagged players really scored 30% less than the unflagged ones
        self.assertGreaterEqual(many["rest"]["factor"], learn.FACTOR_RANGE[0])
        self.assertEqual(many["minutes"]["factor"], 0.85)      # nothing seen for the other flags: constant unchanged

    def test_transfer_hurdle_rises_only_when_moves_underdeliver(self):
        ok = learn.fit_transfers({"8": {"transfers": [{"pred": 3.0, "real": 3.0}] * 12}})
        self.assertFalse(ok["applied"])
        bad = learn.fit_transfers({"8": {"transfers": [{"pred": 3.0, "real": 0.5}] * 12}})
        self.assertTrue(bad["applied"])
        self.assertTrue(1.0 < bad["mult"] <= 2.0)

    def test_elite_weight_stays_at_the_prior_without_data(self):
        e = learn.fit_elite({"gws": {}}, {})
        self.assertEqual(e["own_weight"], learn.ELITE_PRIOR)
        self.assertFalse(e["own_applied"])


class Defaults(unittest.TestCase):
    def setUp(self):
        self._saved = ai_team.LEARNED_DOC
        ai_team.LEARNED_DOC = {}                 # whatever learned.json holds today, "nothing learned yet" is the default under test

    def tearDown(self):
        ai_team.LEARNED_DOC = self._saved

    def test_nothing_learned_means_the_old_constants(self):
        self.assertEqual(ai_team.learned_factor("rest", 0.93), 0.93)
        self.assertEqual(ai_team.hurdle_mult(), 1.0)
        self.assertEqual(ai_team.captain_elite_weight(), 0.0)
        self.assertEqual(ai_team.elite_weight(), 0.4)


if __name__ == "__main__":
    unittest.main()

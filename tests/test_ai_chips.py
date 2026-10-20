import unittest
import ai_chips as C
import ai_team as T


def _vals(n_per=None, xp=None):
    """A small legal pool: ids 1-2 GKP, 3-7 DEF, 8-12 MID, 13-15 FWD, each on its own club group."""
    pos = ["GKP"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    out = {}
    for k, p in enumerate(pos, start=1):
        x = (xp or {}).get(k, 4.0)
        out[k] = {"id": k, "name": f"P{k}", "pos": p, "team": 100 + k // 3, "cost": 5.0, "xp": x, "xp2": x, "value": x, "avail": 1.0}
    return out


class Gains(unittest.TestCase):
    def test_triple_captain_is_the_captains_points(self):
        v = _vals(xp={13: 9.5})
        self.assertAlmostEqual(C.tc_gain(list(v), v), 9.5)

    def test_bench_boost_is_the_bench_points(self):
        v = _vals()
        xi, bench = T.pick_xi(list(v), v, "xp")
        self.assertAlmostEqual(C.bb_gain(list(v), v), sum(v[i]["xp"] for i in bench))
        self.assertEqual(len(bench), 4)

    def test_availability_resets_at_gw20(self):
        used = {"wildcard": 6, "freehit": 4, "bboost": 1, "3xc": 3}
        self.assertEqual(C.available(used, 8), [])
        self.assertEqual(C.available(used, 20), ["wildcard", "freehit", "bboost", "3xc"])
        self.assertEqual(C.available({**used, "freehit_h2": 22}, 25), ["wildcard", "bboost", "3xc"])
        self.assertEqual(C.used_key("freehit", 19), "freehit")
        self.assertEqual(C.used_key("freehit", 20), "freehit_h2")

    def test_window_end(self):
        self.assertEqual(C.window_end(8), 19)
        self.assertEqual(C.window_end(20), 38)


class Decide(unittest.TestCase):
    def test_holds_in_a_normal_week_and_plays_in_a_big_one(self):
        squad = list(range(1, 16))
        normal = _vals()
        big = _vals(xp={13: 15.0})         # a double-gameweek striker: triple captain is worth +15
        buys = {i: 5.0 for i in squad}
        d = C.decide(squad, buys, 0.0, 10, {"wildcard": 6, "freehit": 4, "bboost": 1}, [normal, normal, normal])
        self.assertIsNone(d["chip"])
        d = C.decide(squad, buys, 0.0, 10, {"wildcard": 6, "freehit": 4, "bboost": 1}, [big, normal, normal])
        self.assertEqual(d["chip"], "3xc")

    def test_waits_when_a_better_week_is_coming(self):
        squad = list(range(1, 16)); buys = {i: 5.0 for i in squad}
        now, later = _vals(xp={13: 10.0}), _vals(xp={13: 16.0})
        d = C.decide(squad, buys, 0.0, 10, {"wildcard": 6, "freehit": 4, "bboost": 1}, [now, later, now])
        self.assertIsNone(d["chip"])
        self.assertEqual(d["watch"]["3xc"]["best_gw"], 11)

    def test_use_it_or_lose_it_in_the_last_gameweek_of_the_half(self):
        squad = list(range(1, 16)); buys = {i: 5.0 for i in squad}
        d = C.decide(squad, buys, 0.0, 19, {"wildcard": 6, "freehit": 4, "bboost": 1}, [_vals()])
        self.assertEqual(d["chip"], "3xc")

    def test_nothing_left_nothing_played(self):
        squad = list(range(1, 16)); buys = {i: 5.0 for i in squad}
        d = C.decide(squad, buys, 0.0, 19, {"wildcard": 6, "freehit": 4, "bboost": 1, "3xc": 3}, [_vals()])
        self.assertIsNone(d["chip"])


class BenchBoostScoring(unittest.TestCase):
    def test_bench_scores_with_the_chip(self):
        squad = [{"id": i, "name": f"P{i}", "pos": p} for i, p in enumerate(["GKP"] + ["DEF"] * 4 + ["MID"] * 4 + ["FWD"] * 2 + ["GKP", "DEF", "MID", "FWD"], start=1)]
        plan = {"squad": squad, "xi": list(range(1, 12)), "bench": [12, 13, 14, 15], "captain": 11, "vice": 10, "hit_cost": 0}
        live = {i: {"minutes": 90, "points": 2} for i in range(1, 16)}
        base = T.score_plan(plan, live, True)["points"]
        boosted = T.score_plan({**plan, "chip": "bboost"}, live, True)["points"]
        self.assertEqual(boosted - base, 8)
        tc = T.score_plan({**plan, "chip": "3xc"}, live, True)["points"]
        self.assertEqual(tc - base, 2)


if __name__ == "__main__":
    unittest.main()

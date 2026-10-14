"""Offline tests for the money, chip and scoring maths that the dashboard's numbers depend on.
Run with:  python -m unittest discover -s tests"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_team
import refresh


class SellPrice(unittest.TestCase):
    def test_profit_is_shared_and_rounded_down(self):
        self.assertEqual(ai_team.sell_price(5.0, 5.3), 5.1)     # half of 0.3 -> 0.1 (rounded down)
        self.assertEqual(ai_team.sell_price(5.0, 5.2), 5.1)
        self.assertEqual(ai_team.sell_price(5.0, 5.1), 5.0)

    def test_losses_are_taken_in_full(self):
        self.assertEqual(ai_team.sell_price(5.0, 4.7), 4.7)

    def test_no_float_drift(self):
        self.assertEqual(ai_team.sell_price(4.3, 4.5), 4.4)


class Chips(unittest.TestCase):
    HIST = {"chips": [{"name": "wildcard", "event": 6}, {"name": "freehit", "event": 4},
                      {"name": "wildcard", "event": 22}, {"name": "bboost", "event": 25}]}

    def test_second_half_play_does_not_overwrite_the_first(self):
        used = refresh.chips_by_half(self.HIST)
        self.assertEqual(used["wildcard"], 6)
        self.assertEqual(used["wildcard_h2"], 22)
        self.assertEqual(used["bboost_h2"], 25)

    def test_chip_for_gw_uses_the_right_half(self):
        used = refresh.chips_by_half(self.HIST)
        self.assertEqual(refresh.chip_for_gw(used, "wildcard", 10), 6)
        self.assertEqual(refresh.chip_for_gw(used, "wildcard", 21), 22)
        self.assertIsNone(refresh.chip_for_gw(used, "freehit", 21))
        self.assertEqual(refresh.chip_base("freehit_h2"), "freehit")


class PairSquads(unittest.TestCase):
    def test_kept_players_are_paired_with_themselves(self):
        old = [{"name": "A", "pos": "MID", "pts": 5}, {"name": "B", "pos": "MID", "pts": 1}]
        new = [{"name": "A", "pos": "MID", "pts": 5}, {"name": "C", "pos": "MID", "pts": 9}]
        rows = refresh._pair_squads(old, new)
        kept = [r for r in rows if r["kept"]]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["old"]["name"], kept[0]["new"]["name"])
        swapped = [r for r in rows if not r["kept"]]
        self.assertEqual((swapped[0]["old"]["name"], swapped[0]["new"]["name"]), ("B", "C"))


def squad():
    spec = [("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]
    out, n = [], 1
    for pos, k in spec:
        for _ in range(k):
            out.append({"id": n, "name": f"{pos}{n}", "pos": pos}); n += 1
    return out


class ScorePlan(unittest.TestCase):
    def plan(self):
        sq = squad()
        xi = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
        bench = [i for i in range(1, 16) if i not in xi]
        return {"squad": sq, "xi": xi, "bench": bench, "captain": 13, "vice": 14, "hit_cost": 4}

    def test_captain_doubles_and_hits_come_off(self):
        live = {i: {"minutes": 90, "points": 2} for i in range(1, 16)}
        live[13]["points"] = 10
        res = ai_team.score_plan(self.plan(), live, True)
        self.assertEqual(res["gross"], 2 * 10 + 10 * 2)
        self.assertEqual(res["points"], res["gross"] - 4)

    def test_vice_and_autosubs_wait_until_the_gameweek_is_over(self):
        live = {i: {"minutes": 90, "points": 2} for i in range(1, 16)}
        live[13] = {"minutes": 0, "points": 0}      # captain has not played (yet)
        provisional = ai_team.score_plan(self.plan(), live, False)
        final = ai_team.score_plan(self.plan(), live, True)
        self.assertTrue(provisional["provisional"])
        self.assertEqual(provisional["captain"], "FWD13")
        self.assertEqual(final["captain"], "FWD14")      # vice takes over once it is certain


class Model(unittest.TestCase):
    def test_defcon_raises_a_defenders_expected_points(self):
        base = {"element_type": 2, "minutes": 900, "expected_goals_per_90": 0.05, "expected_assists_per_90": 0.05,
                "clean_sheets_per_90": 0.3, "expected_goals_conceded_per_90": 1.0, "bonus": 0, "saves_per_90": 0}
        fx = [{"fdr": 3, "opp": "X", "side": "H"}]
        low = ai_team.model_xp({**base, "defensive_contribution_per_90": 4.0}, fx, 10)
        high = ai_team.model_xp({**base, "defensive_contribution_per_90": 12.0}, fx, 10)
        self.assertGreater(high, low + 0.5)

    def test_blank_gameweek_is_zero(self):
        self.assertEqual(ai_team.model_xp({"element_type": 3, "minutes": 900}, [], 10), 0.0)


if __name__ == "__main__":
    unittest.main()

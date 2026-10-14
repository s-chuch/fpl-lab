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


class Planner(unittest.TestCase):
    def vals(self, upgrade_xp):
        """15-player squad where player 8 (a midfielder) is weak and player 99 is a cheap strong midfielder."""
        v = {}
        for p in squad():
            xp = {"GKP": 3.0, "DEF": 3.5, "MID": 4.0, "FWD": 4.5}[p["pos"]]
            v[p["id"]] = {"id": p["id"], "name": p["name"], "pos": p["pos"], "team": p["id"], "club": f"C{p['id']}", "cost": 5.0,
                          "xp": xp, "avail": 1.0}
        v[8]["xp"] = 1.0           # a starter in a bad run
        v[99] = {"id": 99, "name": "Upgrade", "pos": "MID", "team": 99, "club": "UPG", "cost": 5.0, "xp": upgrade_xp, "avail": 1.0}
        return v

    def run_plan(self, upgrade_xp, ft=1):
        import planner
        V = [self.vals(upgrade_xp) for _ in range(3)]
        ids = [p["id"] for p in squad()]
        buys = {i: 5.0 for i in ids}
        return planner.plan_path(ids, buys, 0, ft, V)

    def test_swaps_a_weak_starter_for_a_clearly_better_player(self):
        best, base = self.run_plan(7.0)
        self.assertGreater(best["banked"], base + 5)
        self.assertIn(99, best["steps"][0]["squad"])

    def test_no_move_when_nothing_is_better(self):
        best, base = self.run_plan(0.5)
        self.assertAlmostEqual(best["banked"], base, places=6)
        self.assertTrue(all(not s["moves"] for s in best["steps"]))


class NewsMatching(unittest.TestCase):
    BOOT = {"teams": [{"id": 1, "short_name": "MUN"}, {"id": 2, "short_name": "TOT"}, {"id": 3, "short_name": "BHA"}, {"id": 4, "short_name": "LEE"}],
            "elements": [
                {"id": 1, "web_name": "B.Fernandes", "first_name": "Bruno", "second_name": "Borges Fernandes", "team": 1, "selected_by_percent": "34.4", "minutes": 900},
                {"id": 2, "web_name": "Fernandes", "first_name": "Mateus", "second_name": "Fernandes", "team": 2, "selected_by_percent": "0.7", "minutes": 300},
                {"id": 3, "web_name": "David", "first_name": "Promise", "second_name": "David", "team": 3, "selected_by_percent": "0.2", "minutes": 100},
                {"id": 4, "web_name": "D.James", "first_name": "Daniel", "second_name": "James", "team": 4, "selected_by_percent": "2.0", "minutes": 500},
                {"id": 5, "web_name": "Raya", "first_name": "David", "second_name": "Raya", "team": 1, "selected_by_percent": "10", "minutes": 900},
                {"id": 6, "web_name": "Brooks", "first_name": "David", "second_name": "Brooks", "team": 3, "selected_by_percent": "5", "minutes": 900}]}

    def themes(self, text):
        import fpl_common
        idx = fpl_common.load_player_index(self.BOOT)
        agreed, split = fpl_common.build_themes({"A": text, "B": text, "C": text}, 7, idx)
        return {t["player"]: t for t in agreed + split}

    def test_shared_surname_goes_to_the_more_owned_player(self):
        th = self.themes("Fernandes is the pick of the week at United.")
        self.assertIn("B.Fernandes", th)
        self.assertNotIn("Fernandes", th)

    def test_bare_common_first_name_is_not_a_player(self):
        th = self.themes("David Moyes spoke before the weekend.")
        self.assertNotIn("David", th)

    def test_full_name_still_matches(self):
        th = self.themes("Promise David is flying at Brighton.")
        self.assertIn("David", th)

    def test_tags_are_checked_against_fpl(self):
        import fpl_common
        p = {"status": "a", "chance": 100, "owned": 75.0, "net_transfers": 200000}
        self.assertEqual(fpl_common.sane_tags({"injury/doubt", "differential", "fade/sell", "captain talk"}, p), {"captain talk"})
        q = {"status": "d", "chance": 75, "owned": 3.0, "net_transfers": 0}
        self.assertEqual(fpl_common.sane_tags({"injury/doubt", "differential"}, q), {"injury/doubt", "differential"})


class NewsStance(unittest.TestCase):
    def test_negation_and_market_facts(self):
        import fpl_common
        self.assertEqual(fpl_common.sentence_stance("I would not buy Haaland at that price.", "Haaland"), {"sell": 1})
        self.assertNotIn("sell", fpl_common.sentence_stance("Over 100,000 managers sold Schade after the injury.", "Schade"))
        self.assertIn("risk", fpl_common.sentence_stance("Over 100,000 managers sold Schade after the injury.", "Schade"))

    def test_roundup_headlines_are_not_a_verdict_on_each_name(self):
        import fpl_common
        text = "De Cuyper, Pedro, Cherki, Gibbs-White: Buy, keep or sell in Gameweek 7? Cherki is a must-have this week, bring him in."
        quotes = fpl_common.stance_quotes(text, "Cherki")
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0]["stance"], ["buy"])

    def test_verdicts(self):
        import fpl_common
        self.assertEqual(fpl_common.stance_verdict({"buy": 3}), "Leaning buy")
        self.assertEqual(fpl_common.stance_verdict({"sell": 2}), "Leaning sell / avoid")
        self.assertTrue(fpl_common.stance_verdict({"buy": 2, "sell": 2}).startswith("Mixed"))
        self.assertEqual(fpl_common.stance_verdict({}), "Mentioned, no clear view")


if __name__ == "__main__":
    unittest.main()

import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fixture_swing as fs


def team(i, short, dh, da, ah, aa):
    return {"id": i, "short_name": short, "strength_defence_home": dh, "strength_defence_away": da,
            "strength_attack_home": ah, "strength_attack_away": aa}


BOOT = {"teams": [
    team(1, "AAA", 1000, 1100, 1200, 1300),
    team(2, "BBB", 1200, 1300, 1000, 1100),
    team(3, "CCC", 1400, 1500, 1100, 1200),
    team(4, "DDD", 1300, 1200, 1400, 1500),
]}


def fx(side, opp, fdr):
    return {"side": side, "opp": opp, "fdr": fdr}


SCAN = {
    7: {1: [fx("H", "BBB", 2)], 2: [fx("A", "AAA", 3)], 3: [fx("H", "DDD", 4)], 4: [fx("A", "CCC", 4)]},
    8: {1: [fx("A", "CCC", 5), fx("H", "DDD", 4)], 2: [], 3: [fx("H", "AAA", 2)], 4: [fx("A", "AAA", 2)]},
    9: {1: [fx("H", "BBB", 1)], 2: [fx("A", "CCC", 4)], 3: [fx("A", "BBB", 3)], 4: [fx("H", "AAA", 2)]},
}


class Swing(unittest.TestCase):
    def setUp(self):
        self.s = fs.build_swing(BOOT, SCAN, {"AAA": ["Raya", "Saka"]}, near=2)
        self.c = {c["club"]: c for c in self.s["clubs"]}

    def test_shape_and_flags(self):
        self.assertEqual(self.s["gws"], [7, 8, 9])
        self.assertEqual([c["club"] for c in self.s["clubs"]], ["AAA", "BBB", "CCC", "DDD"])
        self.assertTrue(self.c["BBB"]["cells"][1]["blank"])
        self.assertFalse(self.c["AAA"]["cells"][1]["blank"])
        self.assertTrue(self.c["AAA"]["cells"][1]["double"])
        self.assertFalse(self.c["AAA"]["cells"][0]["double"])

    def test_att_def_range_and_strength(self):
        for c in self.s["clubs"]:
            for cell in c["cells"]:
                for f in cell["fixtures"]:
                    self.assertTrue(1 <= f["att"] <= 5 and 1 <= f["def"] <= 5)
        # AAA home vs BBB(away def 1300) is tougher than AAA away vs CCC? compare same venue:
        # AAA home vs BBB (def away 1300) vs AAA home vs DDD (def away 1200)
        a_bbb = self.c["AAA"]["cells"][0]["fixtures"][0]["att"]
        a_ddd = self.c["AAA"]["cells"][1]["fixtures"][1]["att"]
        self.assertGreater(a_bbb, a_ddd)

    def test_home_away_uses_opposite_venue(self):
        # AAA home vs BBB -> BBB defence AWAY 1300; range 1100..1500 -> 3.0
        self.assertEqual(self.c["AAA"]["cells"][0]["fixtures"][0]["att"], 3.0)
        # BBB away at AAA -> AAA defence HOME 1000 (min of 1000..1400) -> 1.0
        self.assertEqual(self.c["BBB"]["cells"][0]["fixtures"][0]["att"], 1.0)
        # def: AAA home vs BBB -> BBB attack AWAY 1100; range 1100..1500 -> 1.0
        self.assertEqual(self.c["AAA"]["cells"][0]["fixtures"][0]["def"], 1.0)
        # BBB away at AAA -> AAA attack HOME 1200, range 1000..1400 -> 3.0
        self.assertEqual(self.c["BBB"]["cells"][0]["fixtures"][0]["def"], 3.0)

    def test_avgs(self):
        self.assertAlmostEqual(self.c["AAA"]["avg_fdr_near"], (2 + 5 + 4) / 3, places=2)
        self.assertEqual(self.c["AAA"]["avg_fdr_far"], 1)
        self.assertEqual(self.c["BBB"]["avg_fdr_near"], 3)
        self.assertEqual(self.c["BBB"]["avg_fdr_far"], 4)

    def test_all_near_blank_is_none(self):
        scan = {7: {}, 8: {}, 9: {1: [fx("H", "BBB", 2)]}}
        s = fs.build_swing(BOOT, scan, near=2)
        self.assertIsNone(s["clubs"][0]["avg_fdr_near"])
        self.assertEqual(s["clubs"][0]["avg_fdr_far"], 2)

    def test_owned(self):
        self.assertEqual(self.c["AAA"]["own"], 2)
        self.assertEqual(self.c["AAA"]["players"], ["Raya", "Saka"])
        self.assertEqual(self.c["BBB"]["own"], 0)
        s = fs.build_swing(BOOT, SCAN)
        self.assertTrue(all(c["own"] == 0 for c in s["clubs"]))

    def test_elo(self):
        f = self.c["AAA"]["cells"][0]["fixtures"][0]
        self.assertNotIn("elo_diff", f)
        self.assertIsNone(self.c["AAA"]["elo"])
        s = fs.build_swing(BOOT, SCAN, elo={"AAA": 1800.0, "BBB": 1750.4})
        f = s["clubs"][0]["cells"][0]["fixtures"][0]
        self.assertEqual(f["elo_diff"], -50)
        self.assertEqual(s["clubs"][0]["elo"], 1800.0)
        self.assertNotIn("elo_diff", s["clubs"][0]["cells"][1]["fixtures"][0])  # CCC has no elo

    def test_rank_run(self):
        # window 3 means: AAA 12/4=3.0 wait -> (2+5+4+1)/4=3.0; BBB (3+4)/2=3.5; CCC (4+2+3)/3=3.0; DDD (4+2+2)/3=2.67
        self.assertEqual(fs.rank_clubs(self.s, 3, "run"), ["DDD", "AAA", "CCC", "BBB"])

    def test_rank_swing(self):
        # near minus rest: AAA 3.67-1=2.67; BBB 3-4=-1; CCC 3-3=0; DDD 3-2=1
        self.assertEqual(fs.rank_clubs(self.s, 3, "swing"), ["AAA", "DDD", "CCC", "BBB"])


class SwingForm(unittest.TestCase):
    def test_form_fills_attack_and_defence_when_fpl_strengths_are_empty(self):
        boot = {"teams": [{"id": i, "name": n, "short_name": n, "strength_defence_home": 0, "strength_defence_away": 0,
                           "strength_attack_home": 0, "strength_attack_away": 0} for i, n in ((1, "AAA"), (2, "BBB"), (3, "CCC"))]}
        scan = {7: {1: [{"side": "H", "opp": "BBB", "fdr": 3}], 2: [{"side": "A", "opp": "AAA", "fdr": 3}], 3: [{"side": "H", "opp": "AAA", "fdr": 3}]}}
        form = {"AAA": {"gf": 2.5, "ga": 0.5}, "BBB": {"gf": 0.5, "ga": 2.5}, "CCC": {"gf": 1.5, "ga": 1.5}}
        sw = fs.build_swing(boot, scan, form=form)
        by = {c["club"]: c["cells"][0]["fixtures"][0] for c in sw["clubs"]}
        self.assertGreater(by["BBB"]["att"], by["CCC"]["att"] - 5)       # sanity: values exist
        self.assertEqual(by["AAA"]["att"], 1.0)        # attacking the leakiest side (BBB) is as easy as it gets
        self.assertEqual(by["AAA"]["def"], 1.0)        # BBB score the least
        self.assertEqual(by["BBB"]["att"], 5.0)        # AAA concede the least
        sw0 = fs.build_swing(boot, scan)                  # without form it stays neutral
        self.assertEqual(sw0["clubs"][0]["cells"][0]["fixtures"][0]["att"], 3.0)


if __name__ == "__main__":
    unittest.main()

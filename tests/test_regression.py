import unittest
import regression


def hist(rows):
    return [{"round": g, "minutes": 90, "goals_scored": ga, "assists": 0, "expected_goals": x, "expected_assists": 0,
             "goals_conceded": 0, "expected_goals_conceded": 0} for g, ga, x in rows]


class Series(unittest.TestCase):
    def test_cumulative_gap_for_an_attacker(self):
        g = regression.series(hist([(1, 2, 0.5), (2, 0, 0.5), (3, 1, 0.2)]), "MID", 4)
        self.assertEqual([v for _, v in g], [1.5, 1.0, 1.8, 1.8])         # gameweek 4 has no match: carried forward

    def test_defenders_use_goals_conceded_against_xgc(self):
        h = [{"round": 1, "minutes": 90, "goals_conceded": 0, "expected_goals_conceded": 1.5}, {"round": 2, "minutes": 90, "goals_conceded": 2, "expected_goals_conceded": 1.0}]
        self.assertEqual([v for _, v in regression.series(h, "DEF", 2)], [1.5, 0.5])


class Status(unittest.TestCase):
    def gaps(self, vals):
        return list(enumerate(vals, start=1))

    def test_hot_player_who_keeps_overperforming(self):
        self.assertEqual(regression.status(self.gaps([0.5, 1.0, 1.5, 2.0, 2.6, 3.4]))[0], "widening")

    def test_hot_player_who_is_cooling(self):
        self.assertEqual(regression.status(self.gaps([1.0, 2.0, 3.5, 3.2, 3.0, 2.6]))[0], "reverting")

    def test_cold_player_warming_up(self):
        code, label = regression.status(self.gaps([-0.5, -1.0, -2.2, -2.0, -1.8, -1.6]))
        self.assertEqual((code, label), ("reverting", "Warming up"))

    def test_back_to_the_mean_after_a_flag(self):
        self.assertEqual(regression.status(self.gaps([1.0, 2.2, 2.4, 1.6, 1.2, 0.6]))[0], "back")

    def test_never_flagged_small_gap_is_just_holding(self):
        self.assertNotEqual(regression.status(self.gaps([0.1, 0.3, 0.2, 0.4, 0.3, 0.4]))[0], "back")


if __name__ == "__main__":
    unittest.main()

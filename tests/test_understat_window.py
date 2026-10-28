import unittest
import understat


def shot(player, assist, result, xg, x=0.9, y=0.5, sit="O", cross="", minute=10):
    return [player, assist, result, xg, "h", x, y, sit, cross, minute]


class Window(unittest.TestCase):
    def fetched(self, shots, tm=90):
        played = [{"id": "m1", "datetime": "2026-10-01 15:00:00", "h": {"title": "Alpha"}, "a": {"title": "Beta"}}]
        return played, {"m1": {"shots": shots, "mins": {"P": "h", "Q": "h"}, "tm": {"P": tm, "Q": 60}}}

    def test_new_counts(self):
        shots = [shot("P", "Q", "SavedShot", 0.4),                       # in the box, on target, big chance missed, created by Q
                 shot("P", "", "Goal", 0.1, x=0.6, y=0.1),               # a goal from distance, outside the box
                 shot("P", "", "Goal", 0.761, sit="P"),                  # a penalty: counted as a goal but not in non-penalty xG
                 shot("P", "", "MissedShots", 0.05, x=0.9, y=0.9),       # wide: outside the box
                 shot("Q", "P", "Goal", 0.2, sit="C"),                   # P's corner created Q's goal
                 shot("Q", "P", "BlockedShot", 0.1, cross="X")]          # P's cross
        w = understat.player_windows(fetched=self.fetched(shots))["P"]
        self.assertEqual((w["shots"], w["goals"], w["npg"], w["pens"]), (4, 2, 1, 1))
        self.assertAlmostEqual(w["npxg"], 0.55)                           # 0.4 + 0.1 + 0.05, penalty excluded
        self.assertAlmostEqual(w["pen_xg"], 0.761)
        self.assertEqual((w["box"], w["sot"], w["big"], w["big_missed"]), (1, 3, 2, 1))
        self.assertEqual((w["cc"], w["assists"], w["corner_cc"], w["cross_cc"]), (2, 1, 1, 1))
        self.assertEqual(w["mins"], 90)

    def test_old_five_field_shots_do_not_break_windows(self):
        played, matches = self.fetched([["P", "", "Goal", 0.761, "h"]])
        matches["m1"]["tm"] = {}
        w = understat.player_windows(fetched=(played, matches))["P"]
        self.assertEqual((w["goals"], w["pens"], w["box"]), (1, 1, 0))     # penalty still recognised by its xG; no position, no box count


if __name__ == "__main__":
    unittest.main()

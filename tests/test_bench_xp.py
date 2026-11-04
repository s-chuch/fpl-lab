"""The Bench audit's process XI can be judged on the model's saved expected points (not minutes alone)."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import refresh


def squad(spec):
    """spec: [(name, pos, xp, trail_mins, started, captain)]"""
    return [{"name": n, "pos": p, "xp": xp, "trail_mins": tm, "mins": 90, "pts": 0, "started": st, "captain": c} for n, p, xp, tm, st, c in spec]


SPEC = [("Tzolakis", "GKP", 4.09, 270, True, False), ("Raya", "GKP", 4.5, 270, False, False),
        ("A", "DEF", 4.5, 270, True, False), ("B", "DEF", 4.0, 270, True, False), ("C", "DEF", 3.9, 270, True, False),
        ("D", "DEF", 5.5, 270, True, False), ("Davis", "DEF", 2.8, 270, False, False),
        ("E", "MID", 4.4, 270, True, False), ("F", "MID", 4.1, 270, True, False), ("G", "MID", 3.9, 270, True, False), ("King", "MID", 3.5, 270, False, False),
        ("Haaland", "FWD", 7.7, 270, True, True), ("J", "FWD", 4.1, 270, True, False), ("Kostoulas", "FWD", 3.1, 270, True, False)]


class ProcessXiByExpectedPoints(unittest.TestCase):
    def test_expected_points_pick_the_better_keeper_when_minutes_tie(self):
        by_xp = {p["name"] for p in refresh._process_xi(squad(SPEC), mins_key="xp")}
        by_min = {p["name"] for p in refresh._process_xi(squad(SPEC), mins_key="trail_mins")}
        self.assertIn("Raya", by_xp)
        self.assertNotIn("Tzolakis", by_xp)
        self.assertIn("Tzolakis", by_min)          # equal minutes: the player who actually started stays

    def test_xi_is_legal_and_captain_is_kept(self):
        xi = refresh._process_xi(squad(SPEC), mins_key="xp")
        self.assertEqual(len(xi), 11)
        self.assertEqual(sum(p["pos"] == "GKP" for p in xi), 1)
        self.assertGreaterEqual(sum(p["pos"] == "DEF" for p in xi), 3)
        self.assertIn("Haaland", {p["name"] for p in xi})

    def test_lowest_rated_outfielders_are_left_out(self):
        names = {p["name"] for p in refresh._process_xi(squad(SPEC), mins_key="xp")}
        self.assertNotIn("Davis", names)           # 2.8 xP: behind every other defender and midfielder


class SavedExpectedPoints(unittest.TestCase):
    def test_missing_gameweek_gives_nothing(self):
        self.assertEqual(refresh._gw_xp(999), {})


if __name__ == "__main__":
    unittest.main()

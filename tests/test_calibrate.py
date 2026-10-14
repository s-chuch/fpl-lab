"""Offline tests for calibrate.py. Run: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import calibrate


class CalibrateTests(unittest.TestCase):
    def test_fit_recovers_line(self):
        xs = [1, 2, 3, 4, 5]
        a, b = calibrate.fit_linear(xs, [0.5 + 1.5 * x for x in xs])
        self.assertAlmostEqual(a, 0.5)
        self.assertAlmostEqual(b, 1.5)

    def test_fit_shrink(self):
        xs = [1, 2, 3, 4]
        a, b = calibrate.fit_linear(xs, [2 * x for x in xs], shrink=0.5)
        self.assertAlmostEqual(b, 1.5)
        self.assertAlmostEqual(a + b * 2.5, 5.0)

    def test_apply_clips_and_passthrough(self):
        cal = {"per_position": {"MID": {"a": -2.0, "b": 1.5, "n": 9}}}
        self.assertEqual(calibrate.apply_calibration(cal, "MID", 1.0), 0.0)
        self.assertAlmostEqual(calibrate.apply_calibration(cal, "MID", 4.0), 4.0)
        self.assertEqual(calibrate.apply_calibration(cal, "DEF", 3.3), 3.3)
        self.assertEqual(calibrate.apply_calibration(None, "MID", 3.3), 3.3)

    def test_metrics_toy(self):
        m = calibrate.metrics([1, 2, 3], [2, 4, 6])
        self.assertAlmostEqual(m["mae"], 2.0)
        self.assertAlmostEqual(m["rmse"], (14 / 3) ** 0.5, places=3)
        self.assertAlmostEqual(m["pearson"], 1.0)
        self.assertAlmostEqual(m["spearman"], 1.0)
        self.assertAlmostEqual(m["slope"], 2.0)
        self.assertAlmostEqual(m["mean_pred"], 2.0)
        self.assertAlmostEqual(m["mean_actual"], 4.0)

    def test_build_el_per90(self):
        rows = [{"position": "FWD", "minutes": "90", "expected_goals": "0.9", "expected_assists": "0.1",
                 "clean_sheets": "0", "expected_goals_conceded": "1", "saves": "0", "bonus": "2"},
                {"position": "FWD", "minutes": "90", "expected_goals": "0.3", "expected_assists": "0.1",
                 "clean_sheets": "1", "expected_goals_conceded": "1", "saves": "0", "bonus": "1"}]
        el = calibrate.build_el(rows)
        self.assertEqual(el["element_type"], 4)
        self.assertEqual(el["minutes"], 180)
        self.assertAlmostEqual(el["expected_goals_per_90"], 0.6)
        self.assertAlmostEqual(el["clean_sheets_per_90"], 0.5)
        self.assertEqual(el["bonus"], 3)
        self.assertEqual(el["defensive_contribution_per_90"], 0.0)


if __name__ == "__main__":
    unittest.main()

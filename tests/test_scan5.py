import unittest
import signals


class RotationKey(unittest.TestCase):
    def test_id_keyed_flag_hits_only_that_player(self):
        flagged = {"id:7": "rested for the cup"}
        self.assertEqual(signals.rotation_flag(flagged, {"id": 7, "web_name": "Silva"}), "rested for the cup")
        self.assertIsNone(signals.rotation_flag(flagged, {"id": 8, "web_name": "Silva"}))

    def test_name_fallback_when_theme_has_no_id(self):
        self.assertEqual(signals.rotation_flag({"Silva": "x"}, {"id": 8, "web_name": "Silva"}), "x")


class RotationFromNews(unittest.TestCase):
    def test_only_doubts_verdict_flags_rotation(self):
        import tempfile, json, os, time, pathlib
        d = tempfile.mkdtemp()
        news = {"generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "agreed": [
            {"player": "Haaland", "id": 1, "tags": ["rotation risk"], "verdict": "Captain candidate (1 buy)", "text": "x"},
            {"player": "Saka", "id": 2, "tags": ["rotation risk"], "verdict": "Fitness or rotation doubts (3)", "text": "y"}], "split": []}
        pathlib.Path(d, "news.js").write_text("window.FPL_NEWS = " + json.dumps(news) + ";\n")
        got = signals._rotation_flagged_players(pathlib.Path(d))
        self.assertNotIn("id:1", got)
        self.assertIn("id:2", got)


if __name__ == "__main__":
    unittest.main()

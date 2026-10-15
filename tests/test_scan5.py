import unittest
import signals


class RotationKey(unittest.TestCase):
    def test_id_keyed_flag_hits_only_that_player(self):
        flagged = {"id:7": "rested for the cup"}
        self.assertEqual(signals.rotation_flag(flagged, {"id": 7, "web_name": "Silva"}), "rested for the cup")
        self.assertIsNone(signals.rotation_flag(flagged, {"id": 8, "web_name": "Silva"}))

    def test_name_fallback_when_theme_has_no_id(self):
        self.assertEqual(signals.rotation_flag({"Silva": "x"}, {"id": 8, "web_name": "Silva"}), "x")


if __name__ == "__main__":
    unittest.main()

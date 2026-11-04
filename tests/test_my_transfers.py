"""Hand-logged transfers: validation, applying them, replacing an earlier log, and the Plan view."""
import sys, unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import my_transfers as T
import log_transfers as L

POS = [1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4]


def boot():
    els = [{"id": i, "web_name": f"P{i}", "first_name": "F", "second_name": f"P{i}", "team": 1 + (i % 6), "element_type": POS[i - 1] if i <= 15 else 3} for i in range(1, 16)]
    els += [{"id": 20, "web_name": "NewMid", "first_name": "N", "second_name": "M", "team": 8, "element_type": 3},
            {"id": 21, "web_name": "NewDef", "first_name": "N", "second_name": "D", "team": 8, "element_type": 2},
            {"id": 22, "web_name": "Twin", "first_name": "A", "second_name": "T", "team": 8, "element_type": 3},
            {"id": 23, "web_name": "Twin", "first_name": "B", "second_name": "T", "team": 9, "element_type": 3}]
    return {"elements": els, "teams": [{"id": i, "short_name": n} for i, n in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "TOT", "ZZZ"], 1)],
            "events": [{"id": 9, "finished": True, "deadline_time": "2026-10-31T11:00:00Z"}, {"id": 10, "finished": False, "deadline_time": "2026-11-06T18:30:00Z"}]}


SQUAD = list(range(1, 16))
NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def req(moves, gw=10, team="Shaaland"):
    return {"team": team, "gw": gw, "moves": moves}


class Validate(unittest.TestCase):
    def test_legal_move_by_name_and_id(self):
        m, e = T.validate(req([{"out": {"id": 9}, "in": {"name": "NewMid"}}]), boot(), SQUAD, NOW)
        self.assertEqual(e, []); self.assertEqual(m, [{"out": 9, "in": 20}])

    def test_wrong_position_unowned_seller_and_duplicates_are_refused(self):
        self.assertTrue(T.validate(req([{"out": {"id": 9}, "in": {"name": "NewDef"}}]), boot(), SQUAD, NOW)[1])
        self.assertTrue(T.validate(req([{"out": {"id": 20}, "in": {"name": "Twin", "club": "TOT"}}]), boot(), SQUAD, NOW)[1])
        self.assertTrue(T.validate(req([{"out": {"id": 9}, "in": {"id": 20}}, {"out": {"id": 10}, "in": {"id": 20}}]), boot(), SQUAD, NOW)[1])

    def test_shared_name_needs_a_club(self):
        _, e = T.validate(req([{"out": {"id": 9}, "in": {"name": "Twin"}}]), boot(), SQUAD, NOW)
        self.assertIn("matches 2 players", e[0])
        m, e = T.validate(req([{"out": {"id": 9}, "in": {"name": "Twin", "club": "TOT"}}]), boot(), SQUAD, NOW)
        self.assertEqual((m, e), ([{"out": 9, "in": 22}], []))

    def test_only_the_next_open_gameweek_before_its_deadline(self):
        self.assertTrue(T.validate(req([{"out": {"id": 9}, "in": {"id": 20}}], gw=9), boot(), SQUAD, NOW)[1])
        late = datetime(2026, 11, 7, tzinfo=timezone.utc)
        self.assertTrue(T.validate(req([{"out": {"id": 9}, "in": {"id": 20}}]), boot(), SQUAD, late)[1])

    def test_unknown_team_is_refused(self):
        self.assertTrue(T.validate(req([{"out": {"id": 9}, "in": {"id": 20}}], team="Nobody"), boot(), SQUAD, NOW)[1])


class Store(unittest.TestCase):
    def test_apply_and_replace(self):
        self.assertEqual(T.apply_moves([1, 2, 3], [{"out": 2, "in": 9}]), [1, 9, 3])
        d = T.record({}, 1360999, 10, [{"out": 9, "in": 20}], issue=1)
        d = T.record(d, 1360999, 10, [{"out": 9, "in": 22}], issue=2)
        self.assertEqual(d["1360999"]["10"]["moves"], [{"out": 9, "in": 22}]); self.assertEqual(d["1360999"]["10"]["issue"], 2)

    def test_issue_body_parsing(self):
        self.assertEqual(L.parse_body('hi\n```json\n{"a": 1}\n```')["a"], 1)
        self.assertEqual(L.parse_body('{"a": 2}')["a"], 2)
        with self.assertRaises(ValueError):
            L.parse_body("no json here")


class View(unittest.TestCase):
    def test_view_has_lineup_hits_and_comparison(self):
        names = {i: ("GKP" if POS[i - 1] == 1 else "DEF" if POS[i - 1] == 2 else "MID" if POS[i - 1] == 3 else "FWD") if i <= 15 else "MID" for i in range(1, 21)}
        vals = {i: {"id": i, "name": f"P{i}", "pos": names[i], "club": "AAA", "cost": 5.0, "xp": 3.0 + (0.1 * i if i != 20 else 2.0), "avail": 1.0} for i in range(1, 21)}
        import ai_team
        v = T.build_view({"moves": [{"out": 9, "in": 20}], "gw": 10, "logged_at": "t"}, list(range(1, 16)), vals, {"xp": 50.0, "transfers": []}, 0, ai_team.pick_xi)
        self.assertEqual(v["hits"], 1); self.assertEqual(v["hit_cost"], 4)
        self.assertEqual(len(v["lineup"]["xi"]), 11); self.assertEqual(len(v["lineup"]["bench"]), 4)
        self.assertEqual(v["model_xp"], 50.0); self.assertIn("diff_vs_model", v)


if __name__ == "__main__":
    unittest.main()

"""Offline tests for the xG/xA high-chance-volume lists, their track record and the squad rows.
Run with:  python -m unittest discover -s tests"""
import sys, types, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import signals


def el(eid, etype, minutes=900, team=1, **kw):
    d = {"id": eid, "web_name": f"P{eid}", "element_type": etype, "team": team, "now_cost": 70, "minutes": minutes,
         "selected_by_percent": "12.5", "goals_scored": 0, "assists": 0}
    d.update(kw)
    return d


def boot_of(elements, events=None):
    return {"elements": elements, "teams": [{"id": 1, "short_name": "ARS"}, {"id": 2, "short_name": "CHE"}],
            "events": events or [{"id": g, "finished": True, "data_checked": True} for g in (1, 2, 3, 4, 5, 6)]
                      + [{"id": 7, "finished": False, "data_checked": False}]}


def win(**kw):
    w = {"apps": 4, "shots": 5, "sot": 0, "big": 0, "goals": 0, "xg": 0.5, "cc": 0, "big_cc": 0, "assists": 0, "xa": 0.2}
    w.update(kw)
    return w


def fake_understat(windows):
    return types.SimpleNamespace(WINDOW=4, match_to_fpl=lambda w, b: (w, []))


def run(elements, windows, **bkw):
    # 6 finished GWs -> full share is 540 minutes; 55% is 297
    padded = dict(windows)
    for i in range(1000, 1100):     # the >=100 matched-players guard
        padded[i] = win(); elements = elements + [el(i, 3)]
    return signals._imminent_understat(boot_of(elements, **bkw), [], 50, fake_understat(padded), None, windows=padded)


class Volume(unittest.TestCase):
    """The Fantasy Football Scout rule: 10+ shots and <= 1 goal / 8+ chances created and <= 1 assist over the last four appearances."""
    def test_goal_rule_is_ten_shots_and_at_most_one_goal(self):
        els = [el(i, 3, 540) for i in (1, 2, 3, 4)]
        res = run(els, {1: win(shots=10), 2: win(shots=9), 3: win(shots=12, goals=1), 4: win(shots=12, goals=2)})
        self.assertEqual({x["eid"] for x in res["goal"]}, {1, 3})
        self.assertIn("10+", res["goal_rule"])

    def test_goal_list_is_ordered_by_non_penalty_xg_delta_and_includes_defenders(self):
        els = [el(1, 3, 540), el(2, 2, 540), el(3, 4, 540)]
        res = run(els, {1: win(shots=11, npg=0, npxg=1.0), 2: win(shots=11, npg=0, npxg=2.0), 3: win(shots=11, npg=1, npxg=1.2)})
        self.assertEqual([x["eid"] for x in res["goal"]], [2, 1, 3])               # -2.0, -1.0, -0.2
        self.assertEqual(res["goal"][0]["pos"], "DEF")

    def test_non_starter_dropped(self):
        res = run([el(1, 3, 300), el(2, 3, 290)], {1: win(shots=10), 2: win(shots=10)})   # 300 >= 297, 290 < 297
        self.assertEqual([x["eid"] for x in res["goal"]], [1])
        res = run([el(1, 3, 290)], {1: win(cc=9)})
        self.assertEqual(res["assist"], [])

    def test_assist_rule_is_eight_chances_and_at_most_one_assist(self):
        els = [el(i, 3, 540) for i in (1, 2, 3, 4)]
        res = run(els, {1: win(cc=7), 2: win(cc=8), 3: win(cc=12, assists=1), 4: win(cc=12, assists=2)})
        self.assertEqual({x["eid"] for x in res["assist"]}, {2, 3})
        self.assertIn("8+", res["assist_rule"])

    def test_defenders_use_the_same_assist_bar(self):
        res = run([el(1, 2, 540), el(2, 2, 540)], {1: win(cc=8), 2: win(cc=7)})
        self.assertEqual({x["eid"] for x in res["assist"]}, {1})

    def test_assist_needs_three_appearances(self):
        res = run([el(1, 3, 540), el(2, 3, 540)], {1: win(cc=9, apps=2), 2: win(cc=9, apps=3)})
        self.assertEqual({x["eid"] for x in res["assist"]}, {2})

    def test_flags_carry_pos_and_rule(self):
        res = run([el(1, 3, 540)], {1: win(shots=11, cc=8)})
        self.assertEqual(res["goal"][0]["pos"], "MID")
        log = signals.update_volume_log({}, {"source": "understat", **res}, {"next_gw": 7}, boot_of([el(1, 3, 540)]))
        self.assertTrue(all(f["pos"] == "MID" for f in log["gw7"]["flags"]))
        self.assertEqual(log["gw7"]["rule"], 2)                                      # old weeks have no rule: they were the 3-shots-on-target version


class Grading(unittest.TestCase):
    def setUp(self):
        self._get = signals.get
        signals.get = lambda url, *a, **k: {"elements": [
            {"id": 1, "stats": {"minutes": 90, "goals_scored": 1, "assists": 0}},
            {"id": 2, "stats": {"minutes": 90, "goals_scored": 0, "assists": 0}}]}

    def tearDown(self):
        signals.get = self._get

    def test_waits_for_data_checked_and_backfills_pos(self):
        elements = [el(1, 3), el(2, 4)]
        old = {"gw5": {"gw": 5, "graded": False, "flags": [{"eid": 1, "name": "P1", "club": "ARS", "kind": "goal"}]}}
        events = [{"id": 5, "finished": True, "data_checked": False}]
        log = signals.update_volume_log(old, None, {}, boot_of(elements, events))
        self.assertFalse(log["gw5"]["graded"])
        self.assertEqual(log["gw5"]["flags"][0]["pos"], "MID")
        events[0]["data_checked"] = True
        log = signals.update_volume_log(log, None, {}, boot_of(elements, events))
        self.assertTrue(log["gw5"]["graded"])
        self.assertIn("baseline_att", log["gw5"])
        self.assertEqual(log["gw5"]["flags"][0]["got"], 1)


class SquadRows(unittest.TestCase):
    def test_rows_carry_next_fdr_owned(self):
        orig_get, orig_imm = signals.get, signals._imminent_returns
        signals.get = lambda url, *a, **k: {"picks": [{"element": 1}, {"element": 2}]}
        signals._imminent_returns = lambda *a, **k: {}
        try:
            boot = boot_of([el(1, 3, 540, team=1), el(2, 4, 540, team=2)])
            res = signals.build_xg_signal(boot, 1, 6, next_fixture_map={1: {"side": "H", "opp": "CRY", "fdr": 2}})
        finally:
            signals.get, signals._imminent_returns = orig_get, orig_imm
        by = {r["name"]: r for r in res["rows"]}
        self.assertEqual((by["P1"]["next"], by["P1"]["fdr"], by["P1"]["owned_pct"]), ("CRY (H)", 2, 12.5))
        self.assertEqual((by["P2"]["next"], by["P2"]["fdr"]), ("Blank", None))


class ScoutingFilter(unittest.TestCase):
    def test_injured_and_low_minute_players_are_not_suggestions(self):
        from signals import scouting_ok
        ok = {"minutes": 540, "status": "a", "chance_of_playing_next_round": None}
        self.assertTrue(scouting_ok(ok, 6))
        self.assertFalse(scouting_ok({**ok, "minutes": 200}, 6))                   # under 270
        self.assertFalse(scouting_ok({**ok, "minutes": 270}, 8))                   # under 45% of the minutes so far (324)
        self.assertFalse(scouting_ok({**ok, "status": "i"}, 6))
        self.assertFalse(scouting_ok({**ok, "chance_of_playing_next_round": 50}, 6))
        self.assertTrue(scouting_ok({**ok, "chance_of_playing_next_round": 75}, 6))


if __name__ == "__main__":
    unittest.main()

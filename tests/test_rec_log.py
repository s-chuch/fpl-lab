import sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rec_log

POSS = ["GKP", "GKP"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def squad():
    return [{"id": i + 1, "name": f"P{i + 1}", "pos": POSS[i], "club": "AAA", "xp": 1.0} for i in range(15)]


def rec(**kw):
    # XI: GK 1, DEF 3-6 (4), MID 8-11 (4), FWD 13-14 (2); bench: GK 2, then 7 (DEF), 12 (MID), 15 (FWD)
    r = {"squad": squad(), "xi": [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14], "bench": [2, 7, 12, 15],
         "captain": 8, "vice": 9, "chip": None, "hit_cost": 0, "transfers": []}
    r.update(kw)
    return r


def actual_from(r, points=None, hit_cost=0, chip=None, transfers=None, captain=None, vice=None):
    order = r["xi"] + r["bench"]
    picks = [{"element": i, "position": n + 1, "is_captain": i == (captain or r["captain"]),
              "is_vice_captain": i == (vice or r["vice"]), "pos": POSS[i - 1], "name": f"P{i}"} for n, i in enumerate(order)]
    return {"picks": picks, "chip": chip, "points": points, "hit_cost": hit_cost, "transfers": transfers or []}


def live(pts=2, mins=90, **over):
    lv = {i: {"minutes": mins, "points": pts} for i in range(1, 16)}
    for k, v in over.items():
        lv[int(k[1:])] = v
    return lv


class Scoring(unittest.TestCase):
    def test_same_team_same_points(self):
        r = rec(); s = rec_log.score_entry(r, actual_from(r), live())
        self.assertEqual(s["model"], 11 * 2 + 2)          # 11 starters x 2 pts + captain bonus
        self.assertEqual(s["you"], s["model"]); self.assertEqual(s["verdict"], "Same")

    def test_captain_difference(self):
        r = rec()
        lv = live(p8={"minutes": 90, "points": 10}, p9={"minutes": 90, "points": 3})
        s = rec_log.score_entry(r, actual_from(r, captain=9, vice=8), lv)
        self.assertEqual(s["captain"]["model_pts"] * s["captain"]["model_mult"], 20)
        self.assertEqual(s["captain"]["you_pts"] * s["captain"]["you_mult"], 6)
        self.assertEqual(s["captain"]["diff"], 3 - 10)
        self.assertEqual(s["diff"], -7); self.assertEqual(s["verdict"], "Model +7")
        self.assertEqual(s["lineup"]["diff"], 0)

    def test_vice_takes_armband_when_captain_blanks(self):
        r = rec(); lv = live(p8={"minutes": 0, "points": 0}, p9={"minutes": 90, "points": 8})
        s = rec_log.score_entry(r, actual_from(r), lv)
        self.assertEqual(s["captain"]["model"], "P9"); self.assertEqual(s["captain"]["model_pts"], 8)

    def test_hits_are_subtracted(self):
        r = rec(hit_cost=4, transfers=[{"out": "Old", "out_id": 99, "in": "P13", "in_id": 13}])
        lv = live(p13={"minutes": 90, "points": 9}); lv[99] = {"minutes": 90, "points": 1}
        s = rec_log.score_entry(r, actual_from(rec(), points=None, hit_cost=0), lv)
        self.assertEqual(s["model"], s["you"] - 4)
        self.assertEqual(s["transfers"]["model_net"], 9 - 1 - 4)
        self.assertEqual(s["transfers"]["you_net"], 0)

    def test_actual_uses_fpl_points_net_of_hits(self):
        r = rec(); s = rec_log.score_entry(r, actual_from(r, points=70, hit_cost=8), live())
        self.assertEqual(s["you"], 62)
        self.assertEqual(s["you_check"], 24)

    def test_autosub_first_bench_player_who_keeps_formation(self):
        # DEF 3 doesn't play: bench order is GK2, DEF7, MID12, FWD15 -> DEF 7 comes on
        r = rec(); lv = live(p3={"minutes": 0, "points": 0}, p7={"minutes": 90, "points": 6})
        s = rec_log.score_entry(r, actual_from(r), lv)
        self.assertEqual(s["lineup"]["model_autosubs"], [{"out": "P3", "in": "P7"}])
        self.assertEqual(s["model"], 10 * 2 + 6 + 2)

    def test_autosub_respects_minimum_defenders(self):
        # 3-5-2 XI: a non-playing DEF can only be replaced by a DEF, so MID 12 (first on the bench) is skipped
        r = rec(xi=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14], bench=[2, 15, 6, 7])
        lv = live(p3={"minutes": 0, "points": 0}, p15={"minutes": 90, "points": 5}, p6={"minutes": 90, "points": 4})
        s = rec_log.score_entry(r, actual_from(r), lv)
        self.assertEqual(s["lineup"]["model_autosubs"], [{"out": "P3", "in": "P6"}])

    def test_goalkeeper_autosub(self):
        r = rec(); lv = live(p1={"minutes": 0, "points": 0}, p2={"minutes": 90, "points": 7})
        s = rec_log.score_entry(r, actual_from(r), lv)
        self.assertIn({"out": "P1", "in": "P2"}, s["lineup"]["model_autosubs"])

    def test_triple_captain_and_bench_boost(self):
        r = rec()
        s = rec_log.score_entry(r, actual_from(r, chip="3xc"), live())
        self.assertEqual(s["you"], 11 * 2 + 4)
        s = rec_log.score_entry(r, actual_from(r, chip="bboost"), live())
        self.assertEqual(s["you"], 15 * 2 + 2)

    def test_totals(self):
        r = rec()
        log = {"gw1": {"status": "scored", "score": rec_log.score_entry(r, actual_from(r, points=30), live())},
               "gw2": {"status": "scored", "score": rec_log.score_entry(r, actual_from(r, points=20), live())},
               "gw3": {"status": "pending"}}
        t = rec_log.totals(log)
        self.assertEqual((t["gws"], t["you"], t["model"], t["you_wins"], t["model_wins"]), (2, 50, 48, 1, 1))


class PickAndFreeze(unittest.TestCase):
    def test_pick_xi_legal(self):
        ps = [{"name": f"G{i}", "pos": "GKP", "xp": i} for i in range(2)] + [{"name": f"D{i}", "pos": "DEF", "xp": 0.1 * i} for i in range(5)] \
             + [{"name": f"M{i}", "pos": "MID", "xp": 5 + i} for i in range(5)] + [{"name": f"F{i}", "pos": "FWD", "xp": 4 + i} for i in range(3)]
        xi, bench = rec_log.pick_xi(ps)
        c = {p: sum(1 for x in xi if x["pos"] == p) for p in ("GKP", "DEF", "MID", "FWD")}
        self.assertEqual(c, {"GKP": 1, "DEF": 3, "MID": 5, "FWD": 2})
        self.assertEqual(bench[0]["pos"], "GKP"); self.assertEqual(len(bench), 4)

    def test_snapshot_frozen_after_deadline(self):
        dl = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
        boot = {"events": [{"id": 7, "deadline_time": "2026-10-17T10:00:00Z", "finished": False}], "elements": [], "teams": []}
        old = {"gw7": {"gw": 7, "status": "pending", "captain_name": "A"}}
        orig = rec_log.build_snapshot
        try:
            rec_log.build_snapshot = lambda data, boot, now, sha=None: {"gw": 7, "status": "pending", "captain_name": "B"}
            before = rec_log.update(old, {}, boot, 1, None, now=dl - timedelta(minutes=5), sha="x")
            self.assertEqual(before["gw7"]["captain_name"], "B")
            after = rec_log.update(before, {}, boot, 1, None, now=dl + timedelta(minutes=1), sha="x")
            self.assertEqual(after["gw7"]["status"], "frozen")
            again = rec_log.update(after, {}, boot, 1, None, now=dl + timedelta(minutes=2), sha="x")
            self.assertEqual(again["gw7"]["captain_name"], "B"); self.assertEqual(again["gw7"]["status"], "frozen")
        finally:
            rec_log.build_snapshot = orig

    def test_net_moves_ignore_undone_swaps(self):
        pos = {1: "GKP", 2: "DEF", 3: "DEF", 4: "MID", 5: "MID", 6: "FWD"}
        name = {i: f"P{i}" for i in pos}
        m = rec_log.net_moves({1, 2, 4}, {1, 3, 5}, pos, name)
        self.assertEqual([(x["out"], x["in"]) for x in m], [("P2", "P3"), ("P4", "P5")])

    def test_log_path(self):
        self.assertEqual(rec_log.log_path("data.js").name, "rec_log.json")
        self.assertEqual(rec_log.log_path("bacalhau-data.js").name, "bacalhau-rec_log.json")


if __name__ == "__main__":
    unittest.main()


class FairTotals(unittest.TestCase):
    def _e(self, gw, diff, you_ch=None, backfilled=False, sha="abc1234", cap_you="A", cap_model="B", you_mv=(), model_mv=()):
        sc = {"you": 60 + diff, "model": 60, "diff": diff, "chip": {"you": you_ch, "model": None},
              "captain": {"you": cap_you, "model": cap_model, "diff": diff},
              "transfers": {"you": [{"out": o, "in": i} for o, i in you_mv], "model": [{"out": o, "in": i} for o, i in model_mv], "diff": diff},
              "lineup": {"diff": 0}}
        return {"gw": gw, "status": "scored", "backfilled": backfilled, "code_sha": sha, "score": sc}

    def test_only_like_for_like_weeks_count(self):
        log = {"gw1": self._e(1, 10), "gw2": self._e(2, -4, you_ch="wildcard"), "gw3": self._e(3, 6, backfilled=True),
               "gw4": self._e(4, 8, sha="ed836692c8a3")}
        t = rec_log.totals(log)
        self.assertEqual((t["gws"], t["you"], t["model"], t["diff"]), (1, 70, 60, 10))
        self.assertEqual(t["excluded"], {"backfilled": 1, "chip": 1, "known_issue": 1})
        self.assertEqual(t["all"]["gws"], 4)

    def test_too_few_weeks_is_flagged_and_enough_weeks_get_a_noise_band(self):
        few = rec_log.totals({f"gw{i}": self._e(i, 5) for i in range(1, 4)})
        self.assertFalse(few["noise"]["enough"])
        many = rec_log.totals({f"gw{i}": self._e(i, d) for i, d in enumerate([5, -3, 8, 2, -6, 4, 7, 1], start=1)})
        self.assertTrue(many["noise"]["enough"])
        self.assertIsNotNone(many["noise"]["se"])

    def test_disagreements_count_only_where_choices_differ(self):
        log = {"gw1": self._e(1, 7, cap_you="A", cap_model="A", you_mv=[("x", "y")], model_mv=[("x", "y")]),
               "gw2": self._e(2, -3, cap_you="A", cap_model="B", you_mv=[("x", "y")], model_mv=[("p", "q")])}
        d = rec_log.totals(log)["disagree"]
        self.assertEqual((d["captain"]["n"], d["captain"]["model"], d["captain"]["you"]), (1, 1, 0))
        self.assertEqual((d["transfers"]["n"], d["transfers"]["avg"]), (1, -3.0))

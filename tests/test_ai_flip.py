"""Offline tests: the AI team's unlocked plan must not flip-flop on near-ties. Run: python -m unittest discover -s tests"""
import sys, unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_team

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
DEADLINE = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)


def mk(i, pos, team, xp, cost=5.0, avail=1.0, name=None, risks=None):
    return {"id": i, "name": name or f"{pos}{i}", "pos": pos, "team": team, "club": f"T{team}", "cost": cost, "xp": xp,
            "xp2": xp, "value": xp + ai_team.NEXT_WEIGHT * xp, "fixture": "X (H)", "fdr": 3, "avail": avail,
            "status": "a", "news": "", "owned": 10.0, "risks": risks or [], "adj_factors": []}


def world(xp_c=4.0, avail_b=1.0):
    """15-man squad (ids 1-15, weak MID 10 = A is the one to sell) + candidates B (20), C (21), both MID."""
    v = {}
    spec = [("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]
    n = 1
    for pos, k in spec:
        for _ in range(k):
            v[n] = mk(n, pos, n, 4.0 if pos != "GKP" else 3.0); n += 1
    v[10] = mk(10, "MID", 10, 2.0, name="A")          # sold
    v[20] = mk(20, "MID", 20, 5.0, name="B", avail=avail_b)
    v[21] = mk(21, "MID", 21, xp_c, name="C")
    state = {"squad": list(range(1, 16)), "buys": {str(i): 5.0 for i in range(1, 16)}, "bank": 1.0, "ft": 1}
    return v, state


def plan_of(vals, state, forced=None):
    return ai_team.make_plan(8, DEADLINE, vals, state, {}, NOW, None, forced=forced)


def pair_names(plan):
    return [(t["out"], t["in"]) for t in plan["transfers"]]


class Hysteresis(unittest.TestCase):
    def setUp(self):
        vals, self.state = world()
        self.prev = plan_of(vals, self.state)
        self.assertEqual(pair_names(self.prev), [("A", "B")])

    def test_near_tie_is_suppressed(self):
        vals, _ = world(xp_c=5.1)                       # C now marginally better than B
        new = plan_of(vals, self.state)
        self.assertEqual(pair_names(new), [("A", "C")])  # a plain re-plan would flip
        kept = ai_team.keep_previous(self.state, vals, self.prev, new)
        self.assertIsNotNone(kept)
        sticky = plan_of(vals, self.state, forced=kept)
        self.assertEqual(pair_names(sticky), [("A", "B")])

    def test_clear_improvement_switches(self):
        vals, _ = world(xp_c=7.0)                       # C is clearly better
        new = plan_of(vals, self.state)
        self.assertIsNone(ai_team.keep_previous(self.state, vals, self.prev, new))
        self.assertEqual(pair_names(new), [("A", "C")])

    def test_unavailable_in_player_forces_switch(self):
        vals, _ = world(xp_c=5.1, avail_b=0.5)
        new = plan_of(vals, self.state)
        self.assertIsNone(ai_team.keep_previous(self.state, vals, self.prev, new))
        self.assertEqual(pair_names(new), [("A", "C")])

    def test_illegal_move_is_none(self):
        vals, _ = world()
        self.assertIsNone(ai_team.rescore_transfers(self.state, vals, [(99, 20)]))
        vals[20]["cost"] = 9.0                           # no longer affordable
        self.assertIsNone(ai_team.rescore_transfers(self.state, vals, [(10, 20)]))


class ChangeLog(unittest.TestCase):
    def plans(self, xp_c=5.1):
        vals, state = world(xp_c=xp_c)
        a = plan_of(world()[0], state)
        b = plan_of(vals, state)
        return state, vals, a, b

    def test_single_transfer_entry_with_cause(self):
        _, vals, a, b = self.plans(7.0)
        a["model_ref"], b["model_ref"] = "abc1234", "def5678"
        out = ai_team.diff_plans(a, b, vals, NOW, "def5678")
        self.assertEqual([e["kind"] for e in out if e["kind"] != "captain"], ["transfer"])
        e = out[0]
        self.assertEqual(e["cause"], "model update"); self.assertEqual(e["cause_ref"], "def5678")
        self.assertIn("A→C", e["text"]); self.assertIn("A→B", e["text"])
        self.assertEqual(e["moves"][0]["in"], "C")
        self.assertFalse(any(x["kind"] == "swap" for x in out))

    def test_fitness_cause(self):
        state, _, a, _ = self.plans()
        vals, _ = world(xp_c=7.0, avail_b=0.5)
        vals[20]["news"] = "knock"
        a["squad"] = [{**p, "avail": 1.0} for p in a["squad"]]
        b = plan_of(vals, state)
        out = ai_team.diff_plans(a, b, vals, NOW)
        self.assertEqual([e for e in out if e["kind"] == "transfer"][0]["cause"], "injury/fitness")

    def test_no_entry_when_transfers_same(self):
        _, vals, a, _ = self.plans()
        self.assertEqual(ai_team.diff_plans(a, plan_of(vals, self.plans()[0], forced=ai_team.keep_previous(self.plans()[0], vals, a, plan_of(vals, self.plans()[0])) ), vals, NOW), [])

    def test_reversal_adds_no_noise(self):
        state, vals7, a, c = self.plans(7.0)             # A->B then A->C
        log = ai_team.merge_changes([], ai_team.diff_plans(a, c, vals7, NOW))
        self.assertEqual([e["kind"] for e in log if e["kind"] == "transfer"], ["transfer"])
        back = ai_team.diff_plans(c, a, world()[0], NOW)  # and back to A->B
        log = ai_team.merge_changes(log, back)
        self.assertEqual(log, [])                        # the intermediate entry is removed, nothing added
        again = ai_team.diff_plans(a, c, vals7, NOW)
        log = ai_team.merge_changes(ai_team.merge_changes([], again), again)
        self.assertEqual([e["kind"] for e in log if e["kind"] == "transfer"], ["transfer"])   # an entry equal to the last logged set adds nothing


if __name__ == "__main__":
    unittest.main()

"""Offline tests for the Intel-tab builders: price ETA / gameweek reset, rotation gameweeks and squeeze, set pieces, injury trim.
Run with:  python -m unittest discover -s tests"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import signals


class PriceEta(unittest.TestCase):
    def test_fpl_projection_drives_the_label(self):
        for pct, want in ((88.9, "close"), (88.6, "close"), (95.3, "tonight"), (91, "tonight"), (117.7, "tonight"), (-92, "tonight")):
            self.assertEqual(signals.price_eta({"fpl_pct": pct, "momentum": 0}, 0)[0], want, pct)

    def test_high_projection_beats_a_one_day_streak(self):
        self.assertEqual(signals.price_eta({"fpl_pct": 117.7, "momentum": 8}, 1)[0], "tonight")

    def test_direction(self):
        self.assertEqual(signals.price_eta({"fpl_pct": -95}, 0), ("tonight", -1))
        self.assertEqual(signals.price_eta({"fpl_pct": 70}, 0), ("close", 1))

    def test_streak_is_the_fallback(self):
        self.assertEqual(signals.price_eta({"fpl_pct": 10, "momentum": 6}, 3), ("soon", 1))
        self.assertEqual(signals.price_eta({"fpl_pct": None, "momentum": -6}, 1), ("trend", -1))
        self.assertEqual(signals.price_eta({"fpl_pct": 10, "momentum": 1}, 0), ("flat", 0))


class PriceTrendReset(unittest.TestCase):
    row = {"name": "A", "club": "ARS", "momentum": 6.0, "fpl_pct": 10}

    def test_streak_builds_within_a_gameweek(self):
        t1 = signals.build_price_trend({}, [self.row], "2026-11-01", event=10)
        t2 = signals.build_price_trend(t1, [self.row], "2026-11-02", event=10)
        self.assertEqual(t2["A|ARS"]["streak_days"], 2)

    def test_gameweek_change_resets_history(self):
        t1 = signals.build_price_trend({}, [self.row], "2026-11-01", event=10)
        t2 = signals.build_price_trend(t1, [self.row], "2026-11-02", event=11)
        self.assertEqual(t2["A|ARS"]["streak_days"], 1)
        self.assertEqual(t2["A|ARS"]["days_tracked"], 1)
        self.assertEqual(t2["A|ARS"]["event"], 11)

    def test_current_event(self):
        self.assertEqual(signals.current_event({"events": [{"id": 9}, {"id": 10, "is_current": True}, {"id": 11, "is_next": True}]}), 10)
        self.assertEqual(signals.current_event({"events": [{"id": 11, "is_next": True}]}), 11)


class RotationGws(unittest.TestCase):
    def fx(self, gw, h, a, prov):
        return {"event": gw, "team_h": h, "team_a": a, "finished": False, "finished_provisional": prov}

    def test_provisional_gameweek_counts_per_club(self):
        boot = {"events": [{"id": 9, "finished": True}, {"id": 10, "finished": False}]}
        fixtures = [self.fx(10, 1, 2, True), self.fx(10, 3, 4, False)]
        gws, over = signals.rotation_gws(boot, fixtures, 3)
        self.assertEqual(gws, [9, 10])
        self.assertTrue(signals._club_done(over, 10, 1))      # his club's match is over
        self.assertFalse(signals._club_done(over, 10, 3))     # not yet
        self.assertTrue(signals._club_done(over, 9, 3))       # settled gameweek: everyone

    def test_gameweek_with_nothing_over_is_not_read(self):
        boot = {"events": [{"id": 9, "finished": True}, {"id": 10, "finished": False}]}
        gws, _ = signals.rotation_gws(boot, [self.fx(10, 1, 2, False)], 3)
        self.assertEqual(gws, [9])

    def test_double_gameweek_needs_both_matches(self):
        boot = {"events": [{"id": 10, "finished": False}]}
        fixtures = [self.fx(10, 1, 2, True), self.fx(10, 1, 3, False)]
        _, over = signals.rotation_gws(boot, fixtures, 3)
        self.assertFalse(signals._club_done(over, 10, 1))


class Squeeze(unittest.TestCase):
    def test_nailed_on_player_is_not_squeezed(self):
        self.assertFalse(signals.squeeze_applies(3, 4, [90, 90, 90]))

    def test_regular_with_a_short_game_is_squeezed(self):
        self.assertTrue(signals.squeeze_applies(3, 4, [90, 60, 90]))

    def test_international_break_gap_is_not_a_squeeze(self):
        self.assertFalse(signals.squeeze_applies(3, 13, [60, 60, 60]))
        self.assertFalse(signals.squeeze_applies(3, 7, [60, 60, 60]))

    def test_no_following_match_or_long_turnaround(self):
        self.assertFalse(signals.squeeze_applies(None, 4, [60, 60, 60]))
        self.assertFalse(signals.squeeze_applies(5, 4, [60, 60, 60]))

    def test_start_means_46_plus(self):
        self.assertEqual(signals.START_MINS, 46)
        self.assertEqual(signals.build_rotation_risk.__defaults__[2], signals.START_MINS)


class RotationEndToEnd(unittest.TestCase):
    """Belloumi-style: GW10 not settled by FPL, but his club's match is over and he played 0."""
    def test_provisional_gameweek_is_used_and_squeeze_demoted(self):
        def stats(m):
            return {"stats": {"minutes": m}}
        live = {9: [{"id": 1, "stats": {"minutes": 90}}, {"id": 9, "stats": {"minutes": 90}}, {"id": 2, "stats": {"minutes": 90}}],
                8: [{"id": 1, "stats": {"minutes": 90}}, {"id": 9, "stats": {"minutes": 90}}, {"id": 2, "stats": {"minutes": 85}}],
                10: [{"id": 1, "stats": {"minutes": 0}}, {"id": 9, "stats": {"minutes": 90}}, {"id": 2, "stats": {"minutes": 90}}]}
        fixtures = [{"event": 10, "team_h": 1, "team_a": 2, "finished": False, "finished_provisional": True}]
        elements = [el(1, 1, "Belloumi"), el(2, 1, "Raya", element_type=1), el(9, 2, "Other")]
        boot = dict(boot_of(elements), events=[{"id": 8, "finished": True}, {"id": 9, "finished": True}, {"id": 10, "finished": False}])
        recovery = {"ARS": {"rest_days": 13, "next_match": {"date": "2099-01-01", "opponent": "NEW", "competition": "Premier League"},
                            "following_match": {"date": "2099-01-04", "opponent": "BVB", "competition": "Champions League", "days_after": 3}}}
        picks = {"picks": [{"element": 1}, {"element": 2}]}

        def fake_get(url, *a, **k):
            if "/picks/" in url:
                return picks
            if "/fixtures/" in url:
                return fixtures
            gw = int(url.rstrip("/").split("/")[-2])
            return {"elements": live[gw]}
        old_get, old_flag = signals.get, signals._rotation_flagged_players
        signals.get, signals._rotation_flagged_players = fake_get, lambda root: {}
        try:
            res = signals.build_rotation_risk(boot, 1, 9, team_recovery=recovery)
        finally:
            signals.get, signals._rotation_flagged_players = old_get, old_flag
        self.assertEqual(res["gws"], [8, 9, 10])
        by = {r["name"]: r for r in res["rows"]}
        self.assertEqual(by["Belloumi"]["minutes"], [90, 90, 0])
        self.assertEqual(by["Belloumi"]["trend"], "falling")
        self.assertEqual(by["Raya"]["minutes"], [85, 90, 90])
        self.assertIsNone(by["Raya"]["reason"])               # nailed on, 13 days since last match: no squeeze


def el(eid, team, name, **kw):
    d = {"id": eid, "web_name": name, "team": team, "element_type": 3, "now_cost": 70, "status": "a", "news": "",
         "selected_by_percent": "5.0", "chance_of_playing_next_round": None, "chance_of_playing_this_round": None}
    d.update(kw)
    return d


def boot_of(elements):
    return {"elements": elements, "teams": [{"id": 1, "short_name": "ARS"}, {"id": 2, "short_name": "BRE"}]}


class SetPieces(unittest.TestCase):
    def test_injured_first_taker_gets_a_deputy(self):
        els = [el(1, 1, "Saka", status="i", chance_of_playing_next_round=0, news="Knee", penalties_order=1),
               el(2, 1, "Gyokeres", penalties_order=2), el(3, 1, "Odegaard", penalties_order=3),
               el(4, 1, "Rice", direct_freekicks_order=1, corners_and_indirect_freekicks_order=1)]
        row = signals.build_set_pieces(boot_of(els), {2})["rows"][0]
        saka = row["pens"][0]
        self.assertEqual((saka["status"], saka["label"]), ("out", "INJ"))
        self.assertEqual(saka["deputy"]["name"], "Gyokeres")
        self.assertTrue(saka["deputy"]["yours"])
        self.assertNotIn("status", row["fks"][0])            # fit taker: no flag, no deputy
        self.assertNotIn("deputy", row["fks"][0])

    def test_deputy_skips_a_player_who_is_also_out(self):
        els = [el(1, 2, "Thiago", status="s", penalties_order=1),
               el(2, 2, "Out2", status="i", penalties_order=2),
               el(3, 2, "Schade", penalties_order=3)]
        pens = signals.build_set_pieces(boot_of(els))["rows"][1]["pens"]
        self.assertEqual(pens[0]["label"], "SUS")
        self.assertEqual(pens[0]["deputy"]["name"], "Schade")

    def test_doubt_is_flagged_without_a_deputy(self):
        els = [el(1, 1, "Xhaka", status="d", chance_of_playing_next_round=50, corners_and_indirect_freekicks_order=1),
               el(2, 1, "Rice", corners_and_indirect_freekicks_order=2)]
        c = signals.build_set_pieces(boot_of(els))["rows"][0]["corners"][0]
        self.assertEqual((c["status"], c["label"]), ("doubt", "DOUBT 50%"))
        self.assertNotIn("deputy", c)

    def test_no_deputy_when_nobody_is_next(self):
        els = [el(1, 1, "Saka", status="i", penalties_order=1)]
        self.assertNotIn("deputy", signals.build_set_pieces(boot_of(els))["rows"][0]["pens"][0])


class PriceRadar(unittest.TestCase):
    def test_no_market_lists_and_watch_keys_on_club(self):
        els = [el(1, 1, "Smith", price_change_percent="95"), el(2, 2, "Smith", price_change_percent="-95"),
               el(3, 1, "Isak", price_change_percent="95", selected_by_percent="0.0")]
        b = boot_of(els)
        b["total_players"] = 1000000
        for e in els:
            e.update(cost_change_start=0, cost_change_event=0, transfers_in_event=0, transfers_out_event=0, element_type=3)
        b["elements"] = els
        radar = signals.build_price_radar(b, 1, None, extra_names={"Smith|BRE", "Isak"})
        self.assertNotIn("rising", radar)
        self.assertNotIn("falling", radar)
        self.assertEqual(sorted((r["name"], r["club"]) for r in radar["watch"]), [("Isak", "ARS"), ("Smith", "BRE")])


class InjuryTrim(unittest.TestCase):
    def rows(self):
        return [{"id": 1, "label": "INJ", "owned_pct": 20.0, "yours": False},
                {"id": 2, "label": "LEFT", "owned_pct": 9.0, "yours": False},
                {"id": 3, "label": "INJ", "owned_pct": 0.1, "yours": False},
                {"id": 4, "label": "INJ", "owned_pct": 0.1, "yours": True},
                {"id": 5, "label": "DOUBT 50%", "owned_pct": 0.1, "yours": False},
                {"id": 6, "label": "INJ", "owned_pct": 0.5, "yours": False}]

    def test_trim(self):
        out = signals.trim_injury_watch({"top_n": 15, "rows": self.rows()}, keep_ids={5})
        self.assertEqual([r["id"] for r in out["rows"]], [1, 4, 5, 6])    # LEFT and the unconnected 0.1% row gone
        self.assertEqual(out["top_n"], 15)

    def test_never_empties_a_busy_list(self):
        out = signals.trim_injury_watch({"rows": self.rows()})
        self.assertGreaterEqual(len(out["rows"]), 1)


if __name__ == "__main__":
    unittest.main()

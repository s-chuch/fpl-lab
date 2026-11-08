"""Offline tests for the 8 Nov Intel review fixes: theme age rule, stance / tone idioms, table dumps, fresh tags, Exa one-per-URL."""
import sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_run, exa_news, fpl_common, signals

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def write_news(root, generated_at):
    (Path(root) / "news.js").write_text('window.FPL_NEWS = {"generated_at": %s, "agreed": [{"player": "Haaland", "id": 1}], "split": []};' % generated_at)


class ThemeAge(unittest.TestCase):
    def stamp(self, days):
        return '"%s UTC"' % (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")

    def test_fresh_stale_and_unparseable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_news(root, self.stamp(1))
            self.assertEqual(len(signals.load_fresh_themes(root)["agreed"]), 1)
            write_news(root, self.stamp(5))
            self.assertEqual(signals.load_fresh_themes(root), {})
            write_news(root, '"garbage"')
            self.assertEqual(signals.load_fresh_themes(root), {})           # fail closed
            write_news(root, "null")
            self.assertIsNone(signals._load_theme_file(root, "news.js"))

    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(signals.load_fresh_themes(Path(d)), {})


class StanceIdioms(unittest.TestCase):
    def risk(self, s):
        return fpl_common.sentence_stance(s, "Haaland").get("risk", 0)

    def test_idioms_are_not_risk(self):
        self.assertEqual(self.risk("If in doubt, give Haaland the armband this week."), 0)
        self.assertEqual(self.risk("There's no doubt Haaland knows where the back of the net is."), 0)
        self.assertEqual(self.risk("Without doubt Haaland is the best captain on the board."), 0)
        self.assertEqual(self.risk("There is little doubt Haaland starts on Saturday."), 0)

    def test_real_doubt_still_counts(self):
        self.assertGreater(self.risk("Haaland is a doubt for Saturday after a knock."), 0)
        self.assertGreater(self.risk("Haaland is in doubt for the derby."), 0)

    def test_positive_fitness_cancels_risk(self):
        for s in ("Haaland is back to full fitness after his injury, so we can safely recommend him.",
                  "After proving his fitness in training Haaland should start; we recommend him.",
                  "Haaland is fully fit again after the knock."):
            self.assertEqual(self.risk(s), 0, s)
        self.assertEqual(fpl_common.tone_of("Haaland is back to full fitness after the injury."), "good")
        self.assertEqual(fpl_common.tone_of("If in doubt, captain Haaland."), "neutral")
        self.assertEqual(fpl_common.tone_of("Haaland is a doubt after a knock."), "bad")
        self.assertNotIn("injury/doubt", fpl_common.qualifiers_near("There is no doubt Haaland is the pick.", "Haaland"))
        self.assertIn("injury/doubt", fpl_common.qualifiers_near("Haaland is a doubt with an injury.", "Haaland"))

    def test_market_facts_do_not_set_stance_or_tags(self):
        self.assertEqual(fpl_common.sentence_stance("Most popular defender transfer in this week was Haaland.", "Haaland"), {})
        self.assertEqual(fpl_common.sentence_stance("Most sold midfielders along with Haaland were those who sell early.", "Haaland"), {})
        self.assertNotIn("fade/sell", fpl_common.qualifiers_near("Most sold midfielders along with Haaland, who many will sell.", "Haaland"))
        self.assertIn("fade/sell", fpl_common.qualifiers_near("I would sell Haaland now.", "Haaland"))


class FactFilters(unittest.TestCase):
    def facts(self, text, gw=None):
        return fpl_common.fact_sentences(text, "Jackson", gw=gw)

    def test_table_dumps_dropped(self):
        self.assertEqual(self.facts("Player fixtures Next 5 GWs for Jackson are listed here and elsewhere."), [])
        self.assertEqual(self.facts("Forward £ 6.8 m N.Jackson FUL ( H ) is a Jackson fixture row from a table."), [])
        self.assertTrue(self.facts("Jackson has three goals in four games and the penalty duties look likely."))

    def test_older_gameweek_dropped(self):
        old = "Jackson had two goals in GW8 and looks a good buy for the coming weeks."
        self.assertEqual(self.facts(old, gw=11), [])
        self.assertTrue(self.facts(old, gw=8))
        self.assertTrue(self.facts("Jackson has a good run in GW9-12, with two home games to come.", gw=11))      # a range counts by its end
        self.assertTrue(self.facts(old))                                                                         # no current gw known: nothing dropped


class FreshTags(unittest.TestCase):
    def test_tags_checked_against_current_bootstrap(self):
        el = {"selected_by_percent": "22.6", "status": "a", "chance_of_playing_next_round": None, "transfers_in_event": 0, "transfers_out_event": 0}
        p = ai_run.fresh_player(el)
        self.assertEqual(p["owned"], 22.6)
        self.assertEqual(sorted(fpl_common.sane_tags({"differential", "injury/doubt", "captain talk"}, p)), ["captain talk"])
        low = ai_run.fresh_player({**el, "selected_by_percent": "4.0", "status": "d", "chance_of_playing_next_round": 50})
        self.assertEqual(sorted(fpl_common.sane_tags({"differential", "injury/doubt"}, low)), ["differential", "injury/doubt"])
        self.assertEqual(ai_run.fresh_player(None)["status"], "a")


def cand(id, name, team_id, first, second):
    return {"id": id, "name": name, "full": f"{first} {second}", "first": first, "second": second, "team": "X", "team_id": team_id,
            "club": "Club", "status": "d", "chance": 75, "news": "", "owned": 10.0, "squads": []}


def res(title, highlights, url="https://www.bbc.co.uk/sport/a"):
    return {"title": title, "url": url, "highlights": highlights, "publishedDate": (NOW - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}


class ExaReview(unittest.TestCase):
    def test_one_article_one_player(self):
        cs = [cand(1, "Gvardiol", 1, "Josko", "Gvardiol"), cand(2, "Guehi", 1, "Marc", "Guehi"), cand(3, "Semenyo", 1, "Antoine", "Semenyo")]
        r = [res("Gvardiol latest", ["Gvardiol is a doubt with a knock. Guehi is also a doubt for the trip. Semenyo is a doubt with a hamstring problem."])]
        out = exa_news.items_from_results(r, cs, NOW)
        self.assertEqual(list(out), [1])          # the headline names Gvardiol

    def test_snippet_must_add_to_headline(self):
        c = cand(1, "Gvardiol", 1, "Josko", "Gvardiol")
        r = [res("Gvardiol is a doubt for Sunday", ["Gvardiol is a doubt for Sunday."])]
        self.assertEqual(exa_news.items_from_results(r, [c], NOW, only=c), {})
        r = [res("Gvardiol is a doubt for Sunday", ["Gvardiol is a doubt for Sunday after a calf knock in training."])]
        self.assertIn(1, exa_news.items_from_results(r, [c], NOW, only=c))

    def test_predicted_lineup_for_played_match_dropped(self):
        c = cand(1, "Gvardiol", 7, "Josko", "Gvardiol")
        r = [res("Predicted lineup", ["Gvardiol is a doubt but could start in the predicted lineup against Spurs."])]
        played = {7: NOW - timedelta(hours=1)}            # his club kicked off an hour ago: the article is older than the match
        self.assertEqual(exa_news.items_from_results(r, [c], NOW, only=c, played=played), {})
        self.assertIn(1, exa_news.items_from_results(r, [c], NOW, only=c, played={7: NOW - timedelta(days=2)}))
        self.assertIn(1, exa_news.items_from_results(r, [c], NOW, only=c))

    def test_last_played(self):
        fx = [{"team_h": 1, "team_a": 2, "finished": True, "kickoff_time": "2026-11-01T15:00:00Z"},
              {"team_h": 1, "team_a": 3, "finished": False, "kickoff_time": "2026-11-09T15:00:00Z"}]
        lp = exa_news.last_played(fx)
        self.assertEqual(lp[1], datetime(2026, 11, 1, 15, tzinfo=timezone.utc))
        self.assertNotIn(3, lp)


if __name__ == "__main__":
    unittest.main()

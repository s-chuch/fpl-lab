"""Offline tests for exa_news.py (no network, no key): matching, snippet picking, cache and the never-break rules."""
import json, os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import exa_news

NOW = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)


def cand(id, name, team, club, first, second, status="d", chance=75, squads=()):
    return {"id": id, "name": name, "full": f"{first} {second}", "first": first, "second": second, "team": team, "club": club,
            "status": status, "chance": chance, "news": "", "owned": 10.0, "squads": list(squads)}


def res(title, highlights, url="https://www.bbc.co.uk/sport/x", days=0):
    return {"title": title, "url": url, "highlights": highlights, "publishedDate": (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}


class Matching(unittest.TestCase):
    def test_thomas_does_not_match_thomas_asante(self):
        c = cand(1, "Thomas", "COV", "Coventry", "Luke", "Thomas")
        r = [res("Coventry report", ["Brandon Thomas-Asante continues to play out of position on the right wing for Coventry."])]
        self.assertEqual(exa_news.items_from_results(r, [c], NOW, only=c), {})

    def test_initial_name_needs_full_name(self):
        c = cand(2, "N.Williams", "NFO", "Nott'm Forest", "Neco", "Williams")
        r = [res("Forest injuries", ["Dylan Williams (hamstring) remains out while others return soon."])]
        self.assertEqual(exa_news.items_from_results(r, [c], NOW, only=c), {})
        r = [res("Forest injuries", ["Neco Williams (arm) is a doubt for Saturday after a knock in training."])]
        self.assertIn(2, exa_news.items_from_results(r, [c], NOW, only=c))

    def test_long_surname_matches_and_snippet_is_trimmed_sentence(self):
        c = cand(3, "Calafiori", "ARS", "Arsenal", "Riccardo", "Calafiori", squads=["1360999"])
        long = "Calafiori is a doubt for Sunday with a hip problem " + "and the manager will decide later " * 12 + "."
        out = exa_news.items_from_results([res("Arsenal news", [long])], [c], NOW, only=c)[3]
        self.assertLessEqual(len(out["snippet"]), exa_news.MAX_SNIPPET)
        self.assertTrue(out["snippet"].startswith("Calafiori is a doubt"))
        self.assertEqual(out["yours"], ["1360999"])
        self.assertEqual(out["published"], "2026-10-28")

    def test_old_or_undated_results_dropped(self):
        c = cand(3, "Calafiori", "ARS", "Arsenal", "Riccardo", "Calafiori")
        old = res("Arsenal news", ["Calafiori is out with a hip problem for a few weeks."], days=5)
        undated = {**old, "publishedDate": None}
        self.assertEqual(exa_news.items_from_results([old, undated], [c], NOW, only=c), {})

    def test_fragment_snippets_rejected(self):
        c = cand(3, "Calafiori", "ARS", "Arsenal", "Riccardo", "Calafiori")
        r = [res("Arsenal news", ["-winning team, with Calafiori continuing to play on the left of the back three."])]
        self.assertEqual(exa_news.items_from_results(r, [c], NOW, only=c), {})

    def test_trusted_domain_wins_over_blog(self):
        c = cand(3, "Calafiori", "ARS", "Arsenal", "Riccardo", "Calafiori")
        blog = res("FPL blog", ["Calafiori is 75% to start on Sunday after a hip problem."], url="https://some-fpl-blog.com/a")
        good = res("BBC", ["Calafiori is a doubt for the trip to Liverpool with a hip injury."], url="https://www.bbc.co.uk/s/1", days=1)
        self.assertEqual(exa_news.items_from_results([blog, good], [c], NOW, only=c)[3]["source_domain"], "bbc.co.uk")


class Safety(unittest.TestCase):
    def test_missing_key_exits_cleanly_and_keeps_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "exa-news.js"
            p.write_text('window.EXA_NEWS = {"items": [1]};\n')
            old_out, old_env = exa_news.OUT, os.environ.pop("EXA_API_KEY", None)
            exa_news.OUT = p
            try:
                self.assertEqual(exa_news.main(), 0)
            finally:
                exa_news.OUT = old_out
                if old_env is not None:
                    os.environ["EXA_API_KEY"] = old_env
            self.assertIn('"items": [1]', p.read_text())

    def test_write_output_is_valid_js_under_60kb(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.js"
            items = [{"player": "P%d" % i, "snippet": "x" * 220, "headline": "h" * 140, "url": "https://e.com/" + "u" * 200} for i in range(300)]
            exa_news.write_output({"generated_at": "2026-10-28T18:00:00Z", "items": items}, p)
            raw = p.read_text()
            self.assertLess(len(raw.encode()), 60_000)
            self.assertTrue(raw.startswith("window.EXA_NEWS = "))
            json.loads(raw[raw.index("{"): raw.rindex("}") + 1])

    def test_month_counter_resets(self):
        prev = {"month_usage": {"month": "2026-09", "searches": 99, "cost_usd": 1.0}}
        self.assertEqual(exa_news.carry_counter(prev, NOW)["searches"], 0)
        prev = {"month_usage": {"month": "2026-10", "searches": 20, "cost_usd": 0.14}}
        self.assertEqual(exa_news.carry_counter(prev, NOW)["searches"], 20)

    def test_cap_constants(self):
        self.assertLessEqual(exa_news.MAX_SEARCHES, 10)


if __name__ == "__main__":
    unittest.main()

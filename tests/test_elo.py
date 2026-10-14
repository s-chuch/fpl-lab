import os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import elo

TEAMS = [("Arsenal", "ARS"), ("Aston Villa", "AVL"), ("Bournemouth", "BOU"), ("Brentford", "BRE"),
         ("Brighton", "BHA"), ("Chelsea", "CHE"), ("Coventry City", "COV"), ("Crystal Palace", "CRY"),
         ("Everton", "EVE"), ("Fulham", "FUL"), ("Hull City", "HUL"), ("Ipswich Town", "IPS"),
         ("Leeds", "LEE"), ("Liverpool", "LIV"), ("Man City", "MCI"), ("Man Utd", "MUN"),
         ("Newcastle", "NEW"), ("Nott'm Forest", "NFO"), ("Spurs", "TOT"), ("Sunderland", "SUN")]
BOOT = {"teams": [{"id": i + 1, "name": n, "short_name": s} for i, (n, s) in enumerate(TEAMS)]}
ELO_NAMES = ["Arsenal", "AstonVilla", "Bournemouth", "Brentford", "Brighton", "Chelsea", "Coventry",
             "Crystal Palace", "Everton", "Fulham", "Hull", "Ipswich", "Leeds", "Liverpool",
             "ManCity", "Man United", "Newcastle", "Forest", "Tottenham", "Sunderland"]
D = "2026-10-14"


def csv_text(extra=""):
    rows = ["Rank,Club,Country,Level,Elo,From,To"]
    for i, n in enumerate(ELO_NAMES):
        rows.append(f"{i+1},{n},ENG,1,{1900-i*10}.5,2026-10-01,2026-10-20")
    rows.append("99,Newcastle,SCO,1,1500.0,2026-10-01,2026-10-20")
    rows.append("5,OldRow,ENG,1,1234.0,2026-01-01,2026-02-01")
    return "\n".join(rows) + extra


class EloTests(unittest.TestCase):
    def test_all_clubs_mapped(self):
        r = elo.fetch_ratings(BOOT, D, getter=lambda u: csv_text())
        self.assertEqual(r["unmatched"], [])
        self.assertEqual(len(r["ratings"]), 20)
        self.assertEqual(r["date"], D)
        self.assertEqual(r["ratings"]["ARS"], 1900.5)
        self.assertEqual(r["ratings"]["NEW"], 1900.5 - 160)  # English row wins the clash

    def test_unmatched_reported(self):
        txt = "\n".join(l for l in csv_text().splitlines() if "Sunderland" not in l)
        r = elo.fetch_ratings(BOOT, D, getter=lambda u: txt)
        self.assertEqual(r["unmatched"], ["Sunderland"])
        self.assertNotIn("SUN", r["ratings"])

    def test_csv_date_row(self):
        txt = ("Rank,Club,Country,Level,Elo,From,To\n"
               "1,Arsenal,ENG,1,1800.0,2026-09-01,2026-09-30\n"
               "1,Arsenal,ENG,1,1850.0,2026-10-01,2026-10-31\n")
        rows = elo.parse_csv(txt, D)
        self.assertEqual([r["elo"] for r in rows], [1850.0])
        with self.assertRaises(ValueError):
            elo.parse_csv(txt, "2025-01-01")

    def test_probs(self):
        p = elo.match_probs(1800, 1800)
        self.assertAlmostEqual(sum(p.values()), 1.0)
        self.assertGreater(p["home"], p["away"])
        for a, b in [(2000, 1500), (1500, 2000), (1700, 1750)]:
            q = elo.match_probs(a, b)
            self.assertAlmostEqual(sum(q.values()), 1.0)
            self.assertTrue(all(v >= 0 for v in q.values()))
        self.assertGreater(elo.match_probs(2000, 1500)["home"], 0.8)

    def test_gap(self):
        self.assertEqual(elo.elo_gap({"A": 1800, "B": 1700}, "A", "B"), 100)
        self.assertIsNone(elo.elo_gap({"A": 1800}, "A", "B"))

    def test_failure_never_raises(self):
        def boom(u):
            raise OSError("down")
        r = elo.fetch_ratings(BOOT, D, getter=boom)
        self.assertEqual(r["ratings"], {})
        self.assertIn("down", r["error"])
        r = elo.fetch_ratings(BOOT, D, getter=lambda u: "<html>nope</html>")
        self.assertEqual(r["ratings"], {})
        self.assertIn("error", r)

    def test_cache(self):
        now = datetime.now(timezone.utc)
        c = {"ratings": {"ARS": 1}, "date": D, "fetched_at": (now - timedelta(hours=1)).isoformat()}
        self.assertTrue(elo.cache_fresh(c, D, now))
        self.assertFalse(elo.cache_fresh(c, "2026-10-15", now))
        c["fetched_at"] = (now - timedelta(hours=13)).isoformat()
        self.assertFalse(elo.cache_fresh(c, D, now))
        self.assertFalse(elo.cache_fresh({}, D, now))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            calls = []
            def g(u):
                calls.append(u)
                return csv_text()
            elo.fetch_ratings(BOOT, D, getter=g, cache_path=p)
            r = elo.fetch_ratings(BOOT, D, getter=g, cache_path=p)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(r["ratings"]), 20)


if __name__ == "__main__":
    unittest.main()

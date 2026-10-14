import math, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odds

TEAMS = [("Arsenal", "ARS"), ("Aston Villa", "AVL"), ("Bournemouth", "BOU"), ("Brentford", "BRE"),
         ("Brighton", "BHA"), ("Chelsea", "CHE"), ("Coventry City", "COV"), ("Crystal Palace", "CRY"),
         ("Everton", "EVE"), ("Fulham", "FUL"), ("Hull City", "HUL"), ("Ipswich Town", "IPS"),
         ("Leeds", "LEE"), ("Liverpool", "LIV"), ("Man City", "MCI"), ("Man Utd", "MUN"),
         ("Newcastle", "NEW"), ("Nott'm Forest", "NFO"), ("Spurs", "TOT"), ("Sunderland", "SUN")]
BOOT = {"teams": [{"id": i + 1, "name": n, "short_name": s} for i, (n, s) in enumerate(TEAMS)]}
ID = {s: i + 1 for i, (_, s) in enumerate(TEAMS)}
RAW = ["Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Chelsea", "Coventry",
       "Crystal Palace", "Everton", "Fulham", "Hull", "Ipswich", "Leeds", "Liverpool",
       "Man City", "Man United", "Newcastle", "Nott'm Forest", "Tottenham", "Sunderland"]

HEAD = "﻿Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\n"


def synth(lh, la, margin=1.06):
    w, d, l, o = odds.model_probs(lh, la)
    f = lambda p: round(1 / (p * margin), 3)
    return f(w), f(d), f(l), f(o), f(1 - o)


class OddsTests(unittest.TestCase):
    def test_csv_bom_and_missing(self):
        txt = (HEAD +
               "E0,17/10/2026,15:00,Arsenal,Nott'm Forest,1.5,4.5,6.5,1.5,4.4,6.6,1.8,2.0\n"
               "E0,17/10/2026,15:00,Chelsea,Fulham,2.0,3.5,3.8,,,,,\n"          # only B365
               "E0,17/10/2026,15:00,Leeds,Everton,,,,,,,,\n"                    # nothing
               "D1,17/10/2026,15:00,Bayern,Koln,1.1,9,20,1.1,9,20,1.3,3\n")     # other league
        rows = odds.parse_csv(txt)
        self.assertEqual([(r["home"], r["source"]) for r in rows], [("Arsenal", "Avg"), ("Chelsea", "B365")])
        self.assertIsNone(rows[1]["over25"])
        self.assertEqual(rows[0]["date"], "2026-10-17")
        self.assertAlmostEqual(rows[0]["p_home"] + rows[0]["p_draw"] + rows[0]["p_away"], 1.0)

    def test_margin_removal(self):
        p = odds.remove_margin([1.5, 4.5, 6.5])
        self.assertAlmostEqual(sum(p), 1.0)
        self.assertAlmostEqual(sum(odds.remove_margin([1.8, 2.0])), 1.0)
        self.assertGreater(p[0], p[1])

    def test_fit_recovers_lambdas(self):
        for lh, la in [(1.8, 0.9), (1.0, 1.0), (0.8, 2.0), (2.5, 0.6)]:
            h, d, a, o, u = synth(lh, la)
            ph, pd, pa = odds.remove_margin([h, d, a])
            over = odds.remove_margin([o, u])[0]
            fh, fa = odds.fit_lambdas(ph, pd, pa, over)
            self.assertAlmostEqual(fh, lh, delta=0.05)
            self.assertAlmostEqual(fa, la, delta=0.05)

    def test_fit_without_totals(self):
        h, d, a, _, _ = synth(1.6, 1.1, margin=1.0)
        fh, fa = odds.fit_lambdas(*odds.remove_margin([h, d, a]))
        self.assertAlmostEqual(fh, 1.6, delta=0.2)
        self.assertAlmostEqual(fa, 1.1, delta=0.2)

    def test_clean_sheet(self):
        csh, csa = odds.clean_sheets(1.8, 0.9)
        self.assertAlmostEqual(csh, math.exp(-0.9))
        self.assertAlmostEqual(csa, math.exp(-1.8))

    def test_name_mapping(self):
        nm = odds.name_map(BOOT)
        for raw, (_, short) in zip(RAW, TEAMS):
            self.assertEqual(nm.get(odds.norm(raw)), short, raw)

    def _csv(self):
        h, d, a, o, u = synth(1.8, 0.9)
        return (HEAD + f"E0,17/10/2026,15:00,Arsenal,Nott'm Forest,{h},{d},{a},{h},{d},{a},{o},{u}\n"
                f"E0,18/10/2026,15:00,Man United,Tottenham,{h},{d},{a},{h},{d},{a},{o},{u}\n"
                f"E0,18/10/2026,15:00,Mystery FC,Tottenham,{h},{d},{a},{h},{d},{a},{o},{u}\n")

    def test_fetch_and_failure(self):
        r = odds.fetch_odds(BOOT, getter=lambda u: self._csv())
        self.assertEqual(len(r["matches"]), 2)
        self.assertEqual(r["unmatched"], ["Mystery FC"])
        m = r["matches"][0]
        self.assertEqual((m["home"], m["away"], m["date"], m["source"]), ("ARS", "NFO", "2026-10-17", "Avg"))
        self.assertAlmostEqual(m["xg_home"], 1.8, delta=0.05)
        self.assertAlmostEqual(m["cs_home"], math.exp(-m["xg_away"]), delta=0.001)

        def boom(u):
            raise OSError("down")
        e = odds.fetch_odds(BOOT, getter=boom)
        self.assertEqual(e["matches"], [])
        self.assertIn("down", e["error"])
        self.assertIn("error", odds.fetch_odds(BOOT, getter=lambda u: "<html>x</html>"))

    def test_cache(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            calls = []

            def g(u):
                calls.append(u)
                return self._csv()
            odds.fetch_odds(BOOT, getter=g, cache_path=p)
            r = odds.fetch_odds(BOOT, getter=g, cache_path=p)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(r["matches"]), 2)

    def test_by_team_alignment_dgw(self):
        res = {"matches": [
            {"home": "ARS", "away": "NFO", "xg_home": 1.8, "xg_away": 0.9, "cs_home": 0.41, "cs_away": 0.17,
             "p_home": 0.6, "p_away": 0.2},
            {"home": "TOT", "away": "ARS", "xg_home": 1.2, "xg_away": 1.5, "cs_home": 0.22, "cs_away": 0.30,
             "p_home": 0.3, "p_away": 0.45}]}
        scan = {10: {ID["ARS"]: [{"side": "H", "opp": "NFO", "fdr": 2},
                                  {"side": "H", "opp": "CHE", "fdr": 3},   # unpriced
                                  {"side": "A", "opp": "TOT", "fdr": 3}],
                     ID["NFO"]: [{"side": "A", "opp": "ARS", "fdr": 5}],
                     ID["LIV"]: [{"side": "H", "opp": "EVE", "fdr": 2}]}}
        out = odds.by_team(res, scan, BOOT)[10]
        a = out[ID["ARS"]]
        self.assertEqual([x["opp"] for x in a], ["NFO", "TOT"])
        self.assertEqual(a[0], {"opp": "NFO", "side": "H", "xg_for": 1.8, "xg_against": 0.9, "cs": 0.41, "p_win": 0.6})
        self.assertEqual((a[1]["xg_for"], a[1]["cs"], a[1]["p_win"]), (1.5, 0.30, 0.45))
        n = out[ID["NFO"]][0]
        self.assertEqual((n["xg_for"], n["xg_against"], n["cs"], n["p_win"]), (0.9, 1.8, 0.17, 0.2))
        self.assertNotIn(ID["LIV"], out)
        self.assertEqual(odds.by_team({"matches": []}, scan, BOOT), {})


if __name__ == "__main__":
    unittest.main()

import unittest
import fitness
import ai_team
from fplbase import player_availability


def el(**k):
    return {"status": "a", "chance_of_playing_next_round": None, "chance_of_playing_this_round": None, "news": "", **k}


class Chance(unittest.TestCase):
    def test_stated_numbers_win(self):
        self.assertEqual(fitness.chance(el(status="d", chance_of_playing_next_round=25)), (25, "next"))
        self.assertEqual(fitness.chance(el(status="d", chance_of_playing_this_round=75)), (75, "this"))

    def test_out_is_zero_whatever_the_number(self):
        for st in "isu":
            self.assertEqual(fitness.chance(el(status=st, chance_of_playing_next_round=75))[0], 0)

    def test_doubt_without_a_number_reads_the_news_then_assumes_half(self):
        self.assertEqual(fitness.chance(el(status="d", news="Knock - 25% chance of playing")), (25, "news"))
        self.assertEqual(fitness.chance(el(status="d", news="Late fitness test")), (50, "assumed"))

    def test_available_is_full(self):
        self.assertEqual(fitness.chance(el()), (100, "status"))

    def test_model_and_page_flag_agree(self):
        e = el(status="d", news="Late fitness test")
        self.assertEqual(ai_team.availability(e), 0.5)
        a = player_availability(e)
        self.assertEqual((a["chance"], a["kind"], a["label"], a["assumed"]), (50, "doubt", "DOUBT ~50%", True))
        e = el(status="d", chance_of_playing_next_round=75)
        self.assertEqual(ai_team.availability(e), 0.75)
        self.assertEqual(player_availability(e)["label"], "DOUBT 75%")
        self.assertFalse(player_availability(e)["assumed"])


class InjuryWatchYours(unittest.TestCase):
    def test_yours_is_by_player_id_not_name(self):
        import signals
        boot = {"teams": [{"id": 1, "short_name": "AAA"}, {"id": 2, "short_name": "BBB"}],
                "elements": [{"id": 10, "web_name": "Silva", "team": 1, "element_type": 3, "status": "i", "chance_of_playing_next_round": 0, "news": "", "now_cost": 50, "selected_by_percent": "5"},
                             {"id": 11, "web_name": "Silva", "team": 2, "element_type": 3, "status": "i", "chance_of_playing_next_round": 0, "news": "", "now_cost": 50, "selected_by_percent": "4"}]}
        rows = {r["id"]: r for r in signals.build_injury_watch(boot, squad_names={"Silva"}, squad_ids={10})["rows"]}
        self.assertTrue(rows[10]["yours"])
        self.assertFalse(rows[11]["yours"])


if __name__ == "__main__":
    unittest.main()

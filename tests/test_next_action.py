"""«Можно сделать сегодня» на первом экране: только доступные дела, без выдумок."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_test_save import write_test_save

from stardew_tracker import build_state
from stardew_tracker.state import clear_state_cache
from stardew_tracker.today import build_today, pick_next_action


def person(name, until=0, gifts_today=0):
    return {
        "key": name,
        "ru": name,
        "en": name,
        "p_idx": 1,
        "until": until,
        "gifts_today": gifts_today,
        "loved": [{"id": "1", "ru": "a", "en": "a", "sp": [0, 1]}] * 5,
    }


def museum(name):
    return {"id": name, "ru": name, "en": name, "sp": [0, 2], "found": True, "donated": False}


def fish(name, lock="open", trap=False, open_locs=True):
    loc = {"ru": "Река", "en": "River"}
    return {
        "id": name,
        "ru": name,
        "en": name,
        "sp": [0, 3],
        "lock": lock,
        "trap": trap,
        "locs": [loc, {"ru": "Канализация", "en": "The Sewers"}],
        "open_locs": [loc] if open_locs else [],
        "time": "600 1900",
    }


class PickNextActionTest(unittest.TestCase):
    def test_nothing_suitable_is_none_not_a_made_up_tip(self):
        self.assertIsNone(pick_next_action([], [], []))

    def test_birthday_without_gift_comes_first(self):
        action = pick_next_action([person("Abigail")], [museum("Seed")], [fish("Carp")])
        self.assertEqual(action["kind"], "birthday")
        self.assertEqual(action["route"], "people")
        self.assertEqual(len(action["loved"]), 3)

    def test_birthday_already_gifted_is_skipped(self):
        action = pick_next_action([person("Abigail", gifts_today=1)], [museum("Seed")], [])
        self.assertEqual(action["kind"], "museum")

    def test_museum_finds_count_and_preview(self):
        action = pick_next_action([], [museum(str(i)) for i in range(5)], [fish("Carp")])
        self.assertEqual((action["kind"], action["count"], len(action["items"])), ("museum", 5, 3))

    def test_fish_only_in_reachable_places(self):
        action = pick_next_action(
            [],
            [],
            [
                fish("Unknown", lock="unknown"),
                fish("Pot", trap=True),
                fish("NoPlace", open_locs=False),
                fish("Carp"),
            ],
        )
        self.assertEqual((action["kind"], action["en"], action["count"]), ("fish", "Carp", 1))
        # Только открытые места: закрытая Канализация не предлагается.
        self.assertEqual([loc["en"] for loc in action["locs"]], ["River"])

    def test_locked_or_unknown_fish_only_gives_none(self):
        self.assertIsNone(pick_next_action([], [], [fish("A", lock="locked"), fish("B", lock="unknown")]))

    def test_close_bundles_never_become_the_action(self):
        """«Осталось 2» в бандле не значит, что предметы есть у игрока."""

        room = {
            "ru": "Комната",
            "en": "Room",
            "list": [
                {
                    "slot": 1,
                    "color": 0,
                    "ru": "Бандл",
                    "en": "Bundle",
                    "have": 3,
                    "need": 4,
                    "complete": False,
                    "items": [{"have": False}],
                    "reward": None,
                }
            ],
        }
        state, _museum, _upcoming = build_today(
            fish_rows=[],
            museum_rows=[],
            people=[],
            bundle_rooms=[room],
            cook_rows=[],
            craft_rows=[],
            ship_rows=[],
        )
        self.assertEqual(len(state["bundles_close"]), 1)
        self.assertIsNone(state["next_action"])


class NextActionInStateTest(unittest.TestCase):
    def test_synthetic_save_suggests_museum_finds(self):
        tmp = tempfile.mkdtemp(prefix="sdv-next-")
        try:
            clear_state_cache()
            write_test_save(tmp)
            state = build_state(None, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        action = state["today"]["next_action"]
        self.assertEqual(action["kind"], "museum")
        self.assertEqual(action["count"], len(state["today"]["donate_museum"]))
        # open_locs — подмножество locs у каждой рыбы.
        for row in state["fish"]:
            self.assertTrue(all(loc in row["locs"] for loc in row["open_locs"]))


if __name__ == "__main__":
    unittest.main()

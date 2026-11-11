"""Формула перфекции: веса записаны один раз, итог не зависит от версии Python."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from stardew_tracker.perfection import build_perfection  # noqa: E402

EXPECTED_KEYS = [
    "shipped",
    "obelisks",
    "gold_clock",
    "monsters",
    "friends",
    "skills",
    "stardrops",
    "cooking",
    "crafting",
    "fish",
    "walnuts",
]


def _inputs(**overrides):
    """Вход, дающий ровно 53,05 %: на границе округления сумма зависит от порядка слагаемых."""

    kwargs = {
        "counts": {"shipped": [80, 0], "cooking": [81, 81], "fish": [9, 72], "monsters": [0, 0]},
        "craft_rows": [{"done": index < 26, "rec_en": f"recipe {index}"} for index in range(50)],
        "people": [{"perf_done": True}],
        "farmer_level": 3,
        "monster_rows": [],
        "monsters_state": {"slayer_hero": False},
        "obelisk_rows": [{"done": False} for _ in range(4)],
        "has_gold_clock": True,
        "stardrop_rows": [{"done": index < 4} for index in range(7)],
        "all_stardrops": True,
        "raw": {"walnuts": 200, "player_count": 2, "perfection_waivers": 0},
    }
    kwargs.update(overrides)
    return kwargs


class TestPerfectionFormula(unittest.TestCase):
    def test_categories_have_stable_order_and_weights_sum_to_100(self):
        state = build_perfection(**_inputs())
        self.assertEqual([row["key"] for row in state["categories"]], EXPECTED_KEYS)
        self.assertEqual(sum(row["weight"] for row in state["categories"]), 100)

    def test_total_is_the_sum_of_the_displayed_contributions(self):
        state = build_perfection(**_inputs())
        shown = sum(row["earned"] for row in state["categories"])
        # каждое ``earned`` округлено до сотых, итог — нет: разница не больше 11 * 0,005
        self.assertAlmostEqual(shown, state["raw_pct"], delta=0.06)

    def test_boundary_total_does_not_depend_on_python_version(self):
        # 10 + 10 + 11 + 10 + 5.2 + 1.25 + 5 + 0.6 = 53.05. Сложение слева направо
        # даёт 53.1, а ``sum()`` с Python 3.12 (компенсированное) — 53.0.
        state = build_perfection(**_inputs())
        self.assertEqual(state["raw_pct"], 53.1)
        self.assertEqual(state["pct"], 53.1)
        self.assertEqual(state["walnut_room_pct"], 53)

    def test_waivers_are_added_and_total_is_capped(self):
        raw = {"walnuts": 200, "player_count": 2, "perfection_waivers": 5}
        self.assertEqual(build_perfection(**_inputs(raw=raw))["pct"], 58.1)
        raw["perfection_waivers"] = 90
        self.assertEqual(build_perfection(**_inputs(raw=raw))["pct"], 100.0)

    def test_binary_categories_award_the_full_weight_or_nothing(self):
        done = build_perfection(**_inputs())
        by_key = {row["key"]: row for row in done["categories"]}
        self.assertEqual(by_key["gold_clock"]["earned"], 10.0)
        self.assertEqual(by_key["stardrops"]["earned"], 10.0)
        self.assertEqual(by_key["monsters"]["earned"], 0.0)
        empty = build_perfection(**_inputs(has_gold_clock=False, all_stardrops=False))
        by_key = {row["key"]: row for row in empty["categories"]}
        self.assertEqual(by_key["gold_clock"]["earned"], 0.0)
        self.assertEqual(by_key["stardrops"]["earned"], 0.0)
        self.assertEqual(by_key["stardrops"]["have"], 4)  # считаются найденные, а не флаг «все»

    def test_obelisks_are_worth_one_point_each(self):
        rows = [{"done": index < 3} for index in range(4)]
        by_key = {row["key"]: row for row in build_perfection(**_inputs(obelisk_rows=rows))["categories"]}
        self.assertEqual(by_key["obelisks"]["earned"], 3.0)
        self.assertEqual((by_key["obelisks"]["have"], by_key["obelisks"]["total"]), (3, 4))

    def test_wedding_ring_is_not_required_in_single_player(self):
        crafts = [{"done": True, "rec_en": "Wedding Ring"}] + [{"done": True, "rec_en": f"r{i}"} for i in range(149)]
        solo = build_perfection(
            **_inputs(craft_rows=crafts, raw={"walnuts": 0, "player_count": 1, "perfection_waivers": 0})
        )
        co_op = build_perfection(
            **_inputs(craft_rows=crafts, raw={"walnuts": 0, "player_count": 2, "perfection_waivers": 0})
        )
        self.assertEqual({r["key"]: r for r in solo["categories"]}["crafting"]["total"], 149)
        self.assertEqual({r["key"]: r for r in co_op["categories"]}["crafting"]["total"], 150)

    def test_counts_receive_the_final_percentage(self):
        inputs = _inputs()
        build_perfection(**inputs)
        self.assertEqual(inputs["counts"]["perfection"], [53.1, 100])


if __name__ == "__main__":
    unittest.main()

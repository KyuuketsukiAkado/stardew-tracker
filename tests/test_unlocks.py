"""Обязательные условия получения предметов (stardew_tracker.unlocks) и danger zone."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from make_test_save import write_test_save  # noqa: E402

from stardew_tracker import unlocks as req  # noqa: E402
from stardew_tracker.gamedata import load_json  # noqa: E402
from stardew_tracker.saveparser import clear_cache, parse_save  # noqa: E402
from stardew_tracker.state import build_state, clear_state_cache  # noqa: E402


def raw_save(**overrides):
    base = {
        "mail_received": set(),
        "skills": {"fishing": 4, "farming": 10, "mining": 10, "foraging": 10, "combat": 10},
        "walnuts": 0,
        "deepest_mine": 0,
        "museum": {},
        "season": "spring",
        "day": 1,
        "year": 1,
        "has_skull_key": False,
        "has_rusty_key": False,
        "has_dark_talisman": False,
        "axe_level": None,
        "farm_type": None,
        "house_level": 0,
        "areasComplete": [],
    }
    base.update(overrides)
    return base


class TestGates(unittest.TestCase):
    def test_island_opens_by_mail_or_walnuts(self):
        self.assertFalse(req.UnlockContext(raw_save()).status("island"))
        self.assertTrue(req.UnlockContext(raw_save(mail_received={"willyBoatFixed"})).status("island"))
        # Орехи бывают только на острове.
        self.assertTrue(req.UnlockContext(raw_save(walnuts=3)).status("island"))

    def test_walnut_room_needs_100_walnuts(self):
        self.assertFalse(req.UnlockContext(raw_save(walnuts=99)).status("walnut_room"))
        self.assertTrue(req.UnlockContext(raw_save(walnuts=100)).status("walnut_room"))

    def test_secret_woods_is_unknown_without_axe_in_inventory(self):
        self.assertIsNone(req.UnlockContext(raw_save()).status("secret_woods"))
        self.assertFalse(req.UnlockContext(raw_save(axe_level=1)).status("secret_woods"))
        self.assertTrue(req.UnlockContext(raw_save(axe_level=2)).status("secret_woods"))

    def test_skill_and_friend_gates(self):
        ctx = req.UnlockContext(raw_save(), hearts={"Gus": 4})
        self.assertFalse(ctx.status("skill_fishing_5"))
        self.assertTrue(ctx.status("skill_farming_10"))
        self.assertFalse(ctx.status("friend_Gus_5"))
        self.assertTrue(ctx.status("friend_Gus_4"))
        self.assertIn("4♥", ctx.describe("friend_Gus_5")["how_ru"])

    def test_railroad_opens_on_summer_3(self):
        self.assertFalse(req.UnlockContext(raw_save(season="summer", day=2)).status("railroad"))
        self.assertTrue(req.UnlockContext(raw_save(season="summer", day=3)).status("railroad"))

    def test_mastery_needs_all_skills_10(self):
        self.assertFalse(req.UnlockContext(raw_save()).status("mastery"))
        maxed = {"fishing": 10, "farming": 10, "mining": 10, "foraging": 10, "combat": 10}
        self.assertTrue(req.UnlockContext(raw_save(skills=maxed)).status("mastery"))


class TestEvaluate(unittest.TestCase):
    def test_any_open_alternative_opens_item(self):
        ctx = req.UnlockContext(raw_save())
        # Сом: Тайный лес (неизвестно) или город (без условий) — доступен.
        self.assertEqual(req.evaluate([["secret_woods"], []], ctx), ("open", []))

    def test_locked_and_unknown(self):
        ctx = req.UnlockContext(raw_save())
        self.assertEqual(req.evaluate([["desert"]], ctx), ("locked", ["desert"]))
        self.assertEqual(req.evaluate([["secret_woods"], ["farm_forest"]], ctx)[0], "unknown")

    def test_woodskip_suggests_secret_woods_first(self):
        fish = load_json("fish.json")
        alternatives, _common = req.fish_alternatives("734", fish["734"])
        self.assertEqual(alternatives[0], ["secret_woods"])

    def test_legendary_needs_fishing_level(self):
        fish = load_json("fish.json")
        _alts, common = req.fish_alternatives("163", fish["163"])
        self.assertIn("skill_fishing_10", common)
        _alts, common = req.fish_alternatives("900", fish["900"])
        self.assertEqual(common, ["qi_extended", "skill_fishing_10"])

    def test_night_market_fish_detection(self):
        fish = load_json("fish.json")
        self.assertTrue(req.is_night_market_only(fish["798"]))  # Ночной кальмар
        self.assertFalse(req.is_night_market_only(fish["149"]))  # Осьминог — ещё и пляж

    def test_recipe_sources_from_data(self):
        sources = load_json("recipe_sources.json")
        recipes = load_json("recipes.json")
        ru, en, kind, gates = req.recipe_source("Hopper", recipes["crafting"]["Hopper"], sources["crafting"]["Hopper"])
        self.assertEqual((kind, gates), ("qi", ["walnut_room"]))
        self.assertIn("самоцветов Ки", ru)
        ru, en, kind, gates = req.recipe_source("Omelet", recipes["cooking"]["Omelet"], sources["cooking"]["Omelet"])
        self.assertEqual(kind, "tv")
        self.assertIn("Королева соуса", ru)
        self.assertIn("Spring 28, Year 1", en)
        # Навык — из кода unlock в recipes.json.
        _ru, _en, kind, gates = req.recipe_source("Magnet", recipes["crafting"]["Magnet"], None)
        self.assertEqual((kind, gates), ("skill", ["skill_fishing_9"]))

    def test_every_override_names_existing_recipe(self):
        sources = load_json("recipe_sources.json")
        recipes = load_json("recipes.json")
        for kind in ("cooking", "crafting"):
            for name in sources[kind]:
                self.assertIn(name, recipes[kind], f"{kind}: {name}")


class TestSecretsData(unittest.TestCase):
    """Контент danger zone: ссылки, иконки и официальная локализация."""

    @classmethod
    def setUpClass(cls):
        cls.secrets = load_json("secrets.json")
        cls.items = load_json("items.json")
        cls.big = load_json("big_craftables.json")
        cls.entries = [entry for section in cls.secrets["sections"] for entry in section["entries"]]

    def test_item_ids_exist(self):
        for entry in self.entries:
            for uid in entry.get("items", []):
                if uid.startswith("BC:"):
                    self.assertIn(uid[3:], self.big, entry["id"])
                else:
                    self.assertIn(uid, self.items, entry["id"])

    def test_wiki_links_are_relative_pages(self):
        self.assertEqual(self.secrets["wiki_base"], "https://stardewvalleywiki.com/")
        for item in self.entries + self.secrets["sections"]:
            link = item.get("wiki")
            if link:
                self.assertFalse(link.startswith("http"), link)
                self.assertNotIn(" ", link)
                self.assertNotIn("#", link.split("#", 1)[1] if "#" in link else "")

    def test_official_russian_names(self):
        """В игре Qi — «Ки», Junimo — «джунимо» (см. items.json/big_craftables.json)."""

        self.assertEqual(self.items["858"]["ru"], "Самоцвет Ки")
        text = str(self.secrets)
        for wrong in ("Ци ", "Ци»", "Ци,", "Ци.", "юнимо", "Мисс Удильщ"):
            self.assertNotIn(wrong, text)


class TestStateIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_test_save(cls.tmp.name)
        clear_cache()
        clear_state_cache()
        cls.state = build_state(saves_dir=cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_locked_rows_and_gate_catalog(self):
        fish = {row["id"]: row for row in self.state["fish"]}
        self.assertEqual(fish["682"]["lock"], "locked")  # Карп-мутант: канализация
        self.assertEqual(fish["682"]["req"], ["sewers"])
        self.assertFalse(fish["682"]["now"])
        self.assertTrue(fish["900"]["extended"])
        gates = self.state["unlocks"]["gates"]
        self.assertFalse(gates["sewers"]["met"])
        self.assertTrue(gates["skull_cavern"]["met"])
        for row in self.state["fish"] + self.state["crafting"]:
            for key in row["req"]:
                self.assertIn(key, gates)

    def test_today_never_suggests_locked_or_extended_fish(self):
        for row in self.state["today"]["fish_now"]:
            self.assertNotEqual(row["lock"], "locked")
            self.assertFalse(row["extended"])

    def test_night_market_fish_not_available_in_fall(self):
        squid = next(row for row in self.state["fish"] if row["id"] == "798")
        self.assertTrue(squid["night_market"])
        self.assertFalse(squid["in_season"])
        self.assertEqual(squid["seasons"], ["winter"])

    def test_filters_and_secrets_are_exposed(self):
        self.assertTrue(self.state["filters"]["fish_locations"])
        groups = {g for row in self.state["fish"] for g in row["groups"]}
        self.assertIn("mines", groups)
        option_keys = {o["key"] for o in self.state["filters"]["fish_locations"]}
        self.assertTrue(groups <= option_keys)
        keys = [section["key"] for section in self.state["secrets"]["sections"]]
        self.assertIn("qi_orders", keys)
        qi = next(s for s in self.state["secrets"]["sections"] if s["key"] == "qi_orders")
        self.assertEqual(len(qi["entries"]), 10)
        for section in self.state["secrets"]["sections"]:
            for entry in section["entries"]:
                self.assertTrue(entry["sol_ru"] and entry["sol_en"], entry["id"])

    def test_secret_items_are_resolved_with_sprites(self):
        sections = {s["key"]: s for s in self.state["secrets"]["sections"]}
        route = next(e for e in sections["qi_story"]["entries"] if e["id"] == "mysterious_qi")
        names = [item["ru"] for item in route["items"]]
        self.assertEqual(names, ["Аккумулятор", "Радужная ракушка", "Свекла", "Солнечная эссенция"])
        self.assertTrue(all(item["sp"] for item in route["items"]))
        junimo = next(e for e in sections["secret_notes"]["entries"] if e["id"] == "n14")
        self.assertEqual(junimo["items"][0]["ru"], "Каменный джунимо")
        self.assertEqual(junimo["items"][0]["sp"][0], 2)
        self.assertEqual(route["wiki_url"], "https://stardewvalleywiki.com/The_Mysterious_Qi")
        self.assertEqual(route["scheme"], "qi_route")

    def test_new_save_flags_are_parsed(self):
        raw = parse_save(self.state["meta"]["save_path"])
        self.assertTrue(raw["has_skull_key"])
        self.assertIsNone(raw["axe_level"])
        self.assertEqual(raw["special_orders"], set())


if __name__ == "__main__":
    unittest.main()

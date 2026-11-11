"""Форматы реальных сейвов Stardew Valley 1.5.6 и 1.6.15.

Эти тесты появились после проверки на реальных сейвах: синтетические данные
повторяли формат 1.5, и три ошибки тихо жили в 1.6.

* флаги доступа (``hasSkullKey``…) в 1.6 лежат в письмах ``mailReceived``
  (``HasSkullKey``), а тег игрока остаётся пустым — Пещера Черепа, Болото ведьмы
  и Логово мутантов считались закрытыми у тех, кто там давно побывал;
* ``SaveGameInfo`` хранит дату как ``...ForSaveGame`` (сезон — числом), поэтому
  быстрая сводка для списка ферм никогда не срабатывала;
* уже пойманная рыба (Ночной рынок, Лосось Пустоты) помечалась «закрытой».
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from make_test_save import build_save_game_info, build_xml, write_test_save  # noqa: E402

from stardew_tracker import saveparser  # noqa: E402
from stardew_tracker.gamedata import load_json  # noqa: E402
from stardew_tracker.rows import build_fish_rows  # noqa: E402
from stardew_tracker.state import build_state, clear_state_cache, list_saves_info  # noqa: E402
from stardew_tracker.unlocks import UnlockContext  # noqa: E402

ACCESS_FLAGS = {
    "hasSkullKey": "has_skull_key",
    "hasRustyKey": "has_rusty_key",
    "hasDarkTalisman": "has_dark_talisman",
    "hasMagicInk": "has_magic_ink",
    "hasClubCard": "has_club_card",
}
MAIL_1_6 = ("HasSkullKey", "HasRustyKey", "HasDarkTalisman", "HasMagicInk", "HasClubCard")


def xml_1_6(mail=MAIL_1_6) -> str:
    """Тот же сейв в стиле 1.6: теги флагов пустые, значения — в письмах."""

    text = build_xml()
    assert "<hasSkullKey>true</hasSkullKey>" in text
    text = text.replace("<hasSkullKey>true</hasSkullKey>", "".join(f"<{tag} />" for tag in ACCESS_FLAGS))
    extra = "".join(f"<string>{name}</string>" for name in mail)
    return text.replace("<string>CF_Fair</string>", "<string>CF_Fair</string>" + extra)


class _SaveCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-real-formats-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        saveparser.clear_cache()
        clear_state_cache()
        self.addCleanup(saveparser.clear_cache)
        self.addCleanup(clear_state_cache)

    def parse(self, **kwargs):
        return saveparser.parse_save(write_test_save(self.tmp, **kwargs))


class TestAccessFlags(_SaveCase):
    def test_1_6_flags_come_from_mail_when_tags_are_empty(self):
        raw = self.parse(xml=xml_1_6())
        for name in ACCESS_FLAGS.values():
            self.assertTrue(raw[name], name)

    def test_1_5_boolean_tags_still_work(self):
        raw = self.parse()  # <hasSkullKey>true</hasSkullKey>, писем нет
        self.assertTrue(raw["has_skull_key"])
        for name in ("has_rusty_key", "has_dark_talisman", "has_magic_ink", "has_club_card"):
            self.assertFalse(raw[name], name)

    def test_no_flag_anywhere_means_false(self):
        text = build_xml().replace("<hasSkullKey>true</hasSkullKey>", "<hasSkullKey>false</hasSkullKey>")
        self.assertFalse(self.parse(xml=text)["has_skull_key"])

    def test_each_mail_flag_sets_only_its_own_flag(self):
        for mail, expected in zip(MAIL_1_6, ACCESS_FLAGS.values()):
            saveparser.clear_cache()
            raw = self.parse(xml=xml_1_6(mail=(mail,)))
            self.assertTrue(raw[expected], mail)
            others = [flag for flag in ACCESS_FLAGS.values() if flag != expected]
            self.assertFalse(any(raw[flag] for flag in others), mail)

    def test_unrelated_mail_does_not_set_flags(self):
        # в реальных сейвах рядом лежат HasUnlockedSkullDoor, hasPickedUpMagicInk, witchStatueGone…
        raw = self.parse(xml=xml_1_6(mail=("HasUnlockedSkullDoor", "hasPickedUpMagicInk", "witchStatueGone")))
        for name in ACCESS_FLAGS.values():
            self.assertFalse(raw[name], name)

    def test_mail_flag_is_case_insensitive(self):
        self.assertTrue(self.parse(xml=xml_1_6(mail=("hasrustykey",)))["has_rusty_key"])

    def test_skull_flag_from_mail_still_extends_the_depth(self):
        # deepestMineLevel=155 в тестовом сейве; с ключом глубина не меньше 120
        raw = self.parse(xml=xml_1_6())
        self.assertGreaterEqual(raw["deepest_mine"], 120)

    def test_1_6_save_opens_the_places_behind_the_keys(self):
        write_test_save(self.tmp, xml=xml_1_6())
        milestones = {m["key"]: m["met"] for m in build_state(None, self.tmp)["unlocks"]["milestones"]}
        self.assertIs(milestones["skull_cavern"], True)
        self.assertIs(milestones["witch_swamp"], True)
        self.assertIs(milestones["bug_lair"], True)

    def test_1_5_style_save_without_keys_keeps_places_closed(self):
        text = build_xml().replace("<hasSkullKey>true</hasSkullKey>", "<hasSkullKey>false</hasSkullKey>")
        write_test_save(self.tmp, xml=text)
        milestones = {m["key"]: m["met"] for m in build_state(None, self.tmp)["unlocks"]["milestones"]}
        self.assertIs(milestones["skull_cavern"], False)
        self.assertIs(milestones["witch_swamp"], False)


class TestRealSaveGameInfo(_SaveCase):
    def test_summary_is_read_from_real_structure_and_matches_the_full_parse(self):
        path = write_test_save(self.tmp, save_info=True)
        summary = saveparser.read_save_summary(path)
        self.assertIsNotNone(summary)
        raw = saveparser.parse_save(path)
        for key, expected in (
            ("name", raw["name"]),
            ("farm_name", raw["farm_name"]),
            ("season", raw["season"]),
            ("day", raw["day"]),
            ("year", raw["year"]),
            ("money", raw["money"]),
        ):
            self.assertEqual(summary[key], expected, key)

    def test_season_index_maps_to_all_four_seasons(self):
        path = write_test_save(self.tmp, save_info=True)
        info = os.path.join(os.path.dirname(path), "SaveGameInfo")
        for index, season in enumerate(("spring", "summer", "fall", "winter")):
            with open(info, "w", encoding="utf-8") as handle:
                handle.write(build_save_game_info().replace("<seasonForSaveGame>2<", f"<seasonForSaveGame>{index}<"))
            self.assertEqual(saveparser.read_save_summary(path)["season"], season)

    def test_out_of_range_season_index_is_rejected(self):
        path = write_test_save(self.tmp, save_info=True)
        info = os.path.join(os.path.dirname(path), "SaveGameInfo")
        with open(info, "w", encoding="utf-8") as handle:
            handle.write(build_save_game_info().replace("<seasonForSaveGame>2<", "<seasonForSaveGame>9<"))
        self.assertIsNone(saveparser.read_save_summary(path))

    def test_save_list_uses_the_summary_without_a_full_parse(self):
        write_test_save(self.tmp, save_info=True)
        from unittest import mock

        with mock.patch.object(saveparser, "_parse_uncached", side_effect=AssertionError("full parse")):
            saves = list_saves_info(saves_dir=self.tmp)
        self.assertEqual(len(saves), 1)
        self.assertEqual((saves[0]["season"], saves[0]["day"], saves[0]["year"]), ("fall", 12, 3))
        self.assertEqual(saves[0]["farm"], "Тестовая")
        self.assertEqual(saves[0]["money"], 54230)


class TestCaughtFishAreNeverLocked(unittest.TestCase):
    FISH = load_json("fish.json")
    ITEMS = load_json("items.json")

    def rows(self, caught: int, uid: str = "798"):  # 798 — Полуночный кальмар, только Ночной рынок
        raw = {"fishCaught": {uid: caught}, "season": "spring", "day": 3, "year": 1, "mail_received": []}
        return build_fish_rows({uid: self.FISH[uid]}, self.ITEMS, raw, "spring", 600, "sunny", UnlockContext(raw))

    def test_unseen_night_market_fish_is_locked_outside_its_dates(self):
        row = self.rows(0)[0]
        self.assertEqual(row["lock"], "locked")
        self.assertTrue(row["req"])

    def test_the_same_fish_once_caught_is_open(self):
        row = self.rows(1)[0]
        self.assertTrue(row["done"])
        self.assertEqual((row["lock"], row["req"]), ("open", []))

    def test_caught_fish_in_a_gated_location_is_open_too(self):
        # 795 — Лосось Пустоты (Болото ведьмы): без флагов трекер считал бы его закрытым
        row = self.rows(2, uid="795")[0]
        self.assertEqual(row["lock"], "open")


class TestMailMatchingIgnoresCase(unittest.TestCase):
    """В игре письмо называется ``JojaMember``, но ``jojaVault``: регистр нельзя угадывать."""

    @staticmethod
    def ctx(mail, **raw):
        data = {"mail_received": mail, "areasComplete": [False] * 6, "season": "fall", "day": 5, "year": 2}
        data.update(raw)
        return UnlockContext(data)

    def test_has_mail_is_case_insensitive(self):
        ctx = self.ctx(["JojaMember", "ccVault"])
        self.assertTrue(ctx.has_mail("jojamember"))
        self.assertTrue(ctx.has_mail("CCVAULT"))
        self.assertFalse(ctx.has_mail("ccIsComplete"))
        self.assertFalse(self.ctx([]).has_mail("JojaMember"))

    def test_joja_route_counts_as_a_finished_community_for_the_bug_lair(self):
        # реальный сейв на пути Joja: ключ есть, письмо JojaMember есть, ccIsComplete нет
        self.assertIs(self.ctx(["JojaMember"], has_rusty_key=True).status("bug_lair"), True)

    def test_bug_lair_still_needs_the_key_and_a_finished_community(self):
        self.assertIs(self.ctx(["JojaMember"], has_rusty_key=False).status("bug_lair"), False)
        self.assertIs(self.ctx([], has_rusty_key=True).status("bug_lair"), False)
        self.assertIs(self.ctx(["ccIsComplete"], has_rusty_key=True).status("bug_lair"), True)

    def test_other_mail_gates_work_in_any_case(self):
        self.assertTrue(self.ctx(["JOJAVAULT"]).status("desert"))
        self.assertTrue(self.ctx(["JojaPantry"]).status("greenhouse"))
        self.assertTrue(self.ctx(["willyboatfixed"]).status("island"))


if __name__ == "__main__":
    unittest.main()

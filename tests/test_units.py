"""Модульные тесты утилит трекера: время, XML, поиск, цели, рендер."""

from __future__ import annotations

import contextlib
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from langpin import pin_english, unpin  # noqa: E402
from make_test_save import write_test_save  # noqa: E402

from stardew_tracker import (  # noqa: E402
    SaveError,
    gamedata,
    goals,
    savefinder,
    timeutil,
    xmlutil,
)
from stardew_tracker.catalog import item_info, item_row  # noqa: E402
from stardew_tracker.cli import build_parser, main  # noqa: E402
from stardew_tracker.perfection import build_perfection, compute_counts  # noqa: E402
from stardew_tracker.report import _inline_sprites_css, render  # noqa: E402
from stardew_tracker.saveparser import parse_save  # noqa: E402
from stardew_tracker.state import build_state  # noqa: E402


def setUpModule():
    pin_english()


def tearDownModule():
    unpin()


class TestTimeUtil(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(timeutil.game_clock(1350), (13, 50))
        self.assertEqual(timeutil.game_clock(600), (6, 0))
        self.assertEqual(timeutil.game_clock(2600), (26, 0))
        self.assertEqual(timeutil.game_clock(None), (6, 0))
        self.assertEqual(timeutil.game_clock("bad"), (6, 0))
        self.assertEqual(timeutil.fmt_clock(1855), "18:55")
        self.assertEqual(timeutil.minutes_of_day(1350), 830)

    def test_abs_day_and_birthdays(self):
        self.assertEqual(timeutil.abs_day("spring", 1, 1), 0)
        self.assertEqual(timeutil.abs_day("summer", 1, 1), 28)
        self.assertEqual(timeutil.abs_day("spring", 1, 2), 112)
        self.assertEqual(timeutil.abs_day("nonsense", "x", "y"), 0)
        current = timeutil.abs_day("winter", 28, 1)
        self.assertEqual(timeutil.days_until_birthday(current, "spring", 1), 1)
        self.assertIsNone(timeutil.days_until_birthday(current, "nope", 1))
        self.assertIsNone(timeutil.days_until_birthday(current, "spring", 99))

    def test_time_windows(self):
        self.assertEqual(timeutil.time_matches("", 700), (True, False))
        self.assertEqual(timeutil.time_matches("600", 700), (True, False))
        self.assertEqual(timeutil.time_matches("600 1200", 700), (True, False))
        self.assertEqual(timeutil.time_matches("600 1200", 300), (False, True))
        self.assertEqual(timeutil.time_matches("600 1200", 1300), (False, False))
        # окно через полночь: 22:00–02:00
        self.assertEqual(timeutil.time_matches("2200 0200", 1380), (True, False))
        self.assertEqual(timeutil.time_matches("2200 0200", 60), (True, False))
        self.assertEqual(timeutil.time_matches("2200 0200", 180), (False, True))
        # два окна: 6:00–9:00 и 18:00–21:00
        self.assertEqual(timeutil.time_matches("600 900 1800 2100", 420), (True, False))
        self.assertEqual(timeutil.time_matches("600 900 1800 2100", 600), (False, True))
        self.assertEqual(timeutil.time_matches("600 900 1800 2100", 1140), (True, False))

    def test_weather(self):
        self.assertTrue(timeutil.weather_matches("both", "sunny"))
        self.assertTrue(timeutil.weather_matches("rainy", "storm"))
        self.assertTrue(timeutil.weather_matches("rainy", "green_rain"))
        self.assertFalse(timeutil.weather_matches("rainy", "sunny"))
        self.assertTrue(timeutil.weather_matches("sunny", "sunny"))
        self.assertFalse(timeutil.weather_matches("sunny", "rainy"))
        self.assertTrue(timeutil.weather_matches("sunny", "sunny"))


class TestRegressions(unittest.TestCase):
    """Баги, найденные в ревью ноября 2026."""

    def test_norm_id_unclosed_paren_does_not_crash(self):
        self.assertEqual(xmlutil.norm_id("(O"), "(O")
        self.assertEqual(xmlutil.norm_id("(O)SeaJelly"), "SeaJelly")

    def test_empty_player_stats_is_not_replaced_by_root_stats(self):
        from stardew_tracker.saveparser import _parse_stats

        root = ET.fromstring(
            "<SaveGame><player><stats/></player>"
            "<stats><specificMonstersKilled><item><key><string>Bat</string></key>"
            "<value><int>9</int></value></item></specificMonstersKilled></stats></SaveGame>"
        )
        host = xmlutil.kid(root, "player")
        monsters, _values, _total = _parse_stats(host, root)
        self.assertEqual(monsters, {})

    def test_allowed_save_paths_survives_save_error(self):
        from stardew_tracker.errors import SaveError
        from stardew_tracker.server import TrackerApp

        app = TrackerApp(saves_dir="/definitely/missing")
        error = SaveError("no_saves", "t", "d", [])
        with mock.patch("stardew_tracker.server.find_saves", side_effect=error):
            self.assertEqual(app.allowed_save_paths(), set())


class TestXmlUtil(unittest.TestCase):
    def test_namespace_helpers(self):
        root = ET.fromstring(
            '<a xmlns:x="urn:test"><x:name>N</x:name>'
            "<item><key><string>(O)128</string></key><value><int>2</int></value></item>"
            "<item><key><string>96</string></key><value><ArrayOfInt><int>4</int></ArrayOfInt></value></item>"
            "<flags><boolean>true</boolean><boolean>false</boolean></flags>"
            '<x:GameLocation xsi:type="Farm" xmlns:xsi="urn:xsi"/></a>'
        )
        self.assertEqual(xmlutil.ln(root), "a")
        self.assertEqual(xmlutil.txt(xmlutil.kid(root, "name")), "N")
        self.assertEqual(xmlutil.kid_all(root, "item").__len__(), 2)
        pairs = xmlutil.dict_pairs(root)
        self.assertEqual(pairs[0][0], "(O)128")
        self.assertEqual(xmlutil.first_int(pairs[1][1]), 4)
        self.assertEqual(xmlutil.bools(xmlutil.kid(root, "flags")), [True, False])
        location = xmlutil.deep(root, "GameLocation")
        self.assertEqual(xmlutil.lattr(location, "type"), "Farm")
        self.assertEqual(xmlutil.deep_text(root, "name"), "N")
        self.assertEqual(xmlutil.norm_id("(O)128"), "128")
        self.assertEqual(xmlutil.first_text(root, ["missing", "name"]), "N")
        self.assertEqual(xmlutil.first_text(root, ["missing"]), "")
        self.assertTrue(xmlutil.bool_value(xmlutil.kid(xmlutil.kid(root, "flags"), "boolean")))
        self.assertFalse(xmlutil.bool_value(None))
        self.assertEqual(list(xmlutil.iter_texts(root))[:1], [""])
        self.assertTrue(list(xmlutil.flatten([root])))
        self.assertEqual(xmlutil.ln(None), "")
        self.assertIsNone(xmlutil.kid(None, "x"))
        self.assertIsNone(xmlutil.first_int(None))
        self.assertEqual(xmlutil.bools(None), [])
        self.assertEqual(xmlutil.dict_pairs(None), [])

    def test_deep_limit(self):
        root = ET.fromstring("<a><b><c><target>1</target></c></b></a>")
        self.assertIsNotNone(xmlutil.deep(root, "target", limit=100))
        self.assertIsNone(xmlutil.deep(root, "target", limit=1))

    def test_rejects_xml_bombs(self):
        self.assertTrue(xmlutil.has_unsafe_xml_directives(b'<!DOCTYPE x [<!ENTITY y "z">]>'))
        self.assertTrue(xmlutil.has_unsafe_xml_directives(b"<!entity x 'y'>"))
        self.assertFalse(xmlutil.has_unsafe_xml_directives(b"<SaveGame/>"))
        with self.assertRaises(ET.ParseError):
            xmlutil.parse_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')


class TestSaveFinder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-find-")
        self.save = write_test_save(self.tmp)
        other = os.path.join(self.tmp, "Другая_2")
        os.makedirs(other)
        self.other = os.path.join(other, "Другая_2")
        shutil.copy2(self.save, self.other)
        os.utime(self.other, (1_500_000_000, 1_500_000_000))
        self.old = self.other + "_old"
        shutil.copy2(self.other, self.old)
        self.tiny = os.path.join(self.tmp, "tiny")
        with open(self.tiny, "w", encoding="utf-8") as handle:
            handle.write("<SaveGame/>")
        self.info = os.path.join(self.tmp, "SaveGameInfo")
        with open(self.info, "w", encoding="utf-8") as handle:
            handle.write("<SaveGame/>")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scans_subdirectories_and_skips_service_files(self):
        found = savefinder.find_saves(saves_dir=self.tmp)
        self.assertEqual(set(found), {self.save, self.other})
        self.assertEqual(found[0], self.save)  # свежий первым
        self.assertFalse(savefinder.looks_like_save(self.info))
        self.assertFalse(savefinder.looks_like_save(self.old))
        self.assertFalse(savefinder.looks_like_save(self.tiny))

    def test_explicit_file_and_directory(self):
        self.assertEqual(savefinder.find_saves(explicit=self.save), [self.save])
        found = savefinder.find_saves(explicit=self.tmp)
        self.assertEqual(set(found), {self.save, self.other})
        with self.assertRaises(savefinder.SaveError) as context:
            savefinder.find_saves(explicit=os.path.join(self.tmp, "missing"))
        self.assertEqual(context.exception.kind, "no_saves")

    def test_autodiscovery_uses_candidate_dirs(self):
        empty_saves = os.path.join(self.tmp, "no-such")
        with (
            mock.patch.object(savefinder, "candidate_save_dirs", return_value=[self.tmp]),
            mock.patch.object(savefinder, "SAVES_DIR", empty_saves),
            # The standard folders are only searched with the user's permission (see test_consent.py).
            mock.patch.dict(os.environ, {"STARDEW_TRACKER_ALLOW_SCAN": "1"}),
        ):
            found = savefinder.find_saves()
        self.assertEqual(set(found), {self.save, self.other})


class TestSaveFinderErrors(unittest.TestCase):
    def test_permission_and_io_errors(self):
        tmp = tempfile.mkdtemp(prefix="sdv-find-err-")
        try:
            with mock.patch("os.listdir", side_effect=PermissionError):
                with self.assertRaises(savefinder.SaveError) as context:
                    savefinder.find_saves(explicit=tmp)
            self.assertEqual(context.exception.kind, "permission_denied")
            with mock.patch("os.listdir", side_effect=OSError("boom")):
                with self.assertRaises(savefinder.SaveError) as context:
                    savefinder.find_saves(explicit=tmp)
            self.assertEqual(context.exception.kind, "io_error")
            # Автопоиск не должен падать из-за недоступной стандартной папки.
            with mock.patch("os.listdir", side_effect=PermissionError):
                self.assertEqual(savefinder.find_saves(saves_dir=tmp), [])
            with mock.patch("os.listdir", side_effect=PermissionError):
                self.assertEqual(savefinder._scan_dir(tmp, strict=False), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestSaveParserErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-parse-err-")
        self.save = write_test_save(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_sig_errors(self):
        from stardew_tracker import saveparser

        with mock.patch("os.stat", side_effect=FileNotFoundError):
            with self.assertRaises(saveparser.SaveError) as context:
                saveparser._file_sig(self.save)
        self.assertEqual(context.exception.kind, "no_saves")
        with mock.patch("os.stat", side_effect=PermissionError):
            with self.assertRaises(saveparser.SaveError) as context:
                saveparser._file_sig(self.save)
        self.assertEqual(context.exception.kind, "permission_denied")
        with mock.patch("os.stat", side_effect=OSError("boom")):
            with self.assertRaises(saveparser.SaveError) as context:
                saveparser._file_sig(self.save)
        self.assertEqual(context.exception.kind, "io_error")

    def test_read_errors(self):
        with mock.patch("builtins.open", side_effect=PermissionError):
            with self.assertRaises(SaveError) as context:
                parse_save(self.save)
        self.assertEqual(context.exception.kind, "permission_denied")
        with mock.patch("builtins.open", side_effect=OSError("boom")):
            with self.assertRaises(SaveError) as context:
                parse_save(self.save)
        self.assertEqual(context.exception.kind, "io_error")

    def test_wrong_root_tag(self):
        bad = os.path.join(self.tmp, "not-save")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("<NotSaveGame>" + (" " * 300) + "</NotSaveGame>")
        with self.assertRaises(SaveError) as context:
            parse_save(bad)
        self.assertEqual(context.exception.kind, "corrupt_save")

    def test_weather_variants(self):
        base = (
            "<SaveGame><player><name>Ф</name><farmName>П</farmName>"
            "<dayOfMonth>1</dayOfMonth><currentSeason>spring</currentSeason>"
            "<year>1</year><timeOfDay>600</timeOfDay></player>{}</SaveGame>"
        )
        cases = {
            "rain": ("<isRaining>true</isRaining>", "rainy"),
            "lightning": ("<isLightning>true</isLightning>", "storm"),
            "snow": ("<isSnowing>true</isSnowing>", "snow"),
            "wind": ("<isDebrisWeather>true</isDebrisWeather>", "wind"),
            "sun": ("<isRaining>false</isRaining>", "sunny"),
        }
        for name, (extra, expected) in cases.items():
            path = os.path.join(self.tmp, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(base.format(extra) + (" " * 250))
            self.assertEqual(parse_save(path)["weather"], expected, name)

        location_weather = (
            "<SaveGame><player><name>Ф</name><farmName>П</farmName>"
            "<dayOfMonth>1</dayOfMonth><currentSeason>spring</currentSeason>"
            "<year>1</year><timeOfDay>600</timeOfDay></player>"
            "<locationWeather>"
            "<item><key><string>Default</string></key><value><LocationWeather>"
            "<Weather>Rain</Weather><WeatherForTomorrow>Storm</WeatherForTomorrow>"
            "<IsRaining>true</IsRaining><IsLightning>true</IsLightning>"
            "</LocationWeather></value></item>"
            "<item><key><string>Island</string></key><value><LocationWeather>"
            "<IsGreenRain>true</IsGreenRain></LocationWeather></value></item>"
            "</locationWeather></SaveGame>"
        )
        path = os.path.join(self.tmp, "location-weather")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(location_weather)
        parsed = parse_save(path)
        self.assertEqual(parsed["weather"], "storm")
        self.assertEqual(parsed["weather_tomorrow"], "storm")
        self.assertEqual(parsed["island_weather"], "green_rain")


class TestGoals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-goals-unit-")
        self.target = os.path.join(self.tmp, "nested", "goals.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_normalize(self):
        result = goals.normalize_goals(
            {
                "goals": [{"id": "a"}, "bad", 3],
                "tasks": None,
                "annotations": {
                    "x": {"marked": 0, "note": "  hi  "},
                    "y": {"marked": False, "note": ""},
                    "z": "bad",
                    "w": {"marked": True, "note": "n" * 400},
                },
            }
        )
        self.assertEqual(result["goals"], [{"id": "a"}])
        self.assertEqual(result["tasks"], [])
        self.assertEqual(result["annotations"]["x"], {"marked": False, "note": "hi"})
        self.assertNotIn("y", result["annotations"])
        self.assertNotIn("z", result["annotations"])
        self.assertEqual(len(result["annotations"]["w"]["note"]), goals.NOTE_LIMIT)
        self.assertEqual(goals.normalize_goals(None), {"goals": [], "tasks": []})

    def test_atomic_roundtrip_and_backup(self):
        first = {"goals": [{"id": "a"}], "tasks": [], "annotations": {"k": {"marked": True, "note": "n"}}}
        goals.save_goals(first, path=self.target)
        self.assertEqual(goals.load_goals(path=self.target), first)
        self.assertFalse(glob.glob(os.path.join(self.tmp, "nested", "*.tmp")))
        second = {"goals": [], "tasks": [{"id": "t", "done": True}]}
        goals.save_goals(second, path=self.target)
        self.assertEqual(goals.load_goals(path=self.target), second)
        with open(self.target + ".bak", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), first)

    def test_corrupt_file_falls_back_to_backup(self):
        data = {"goals": [{"id": "a"}], "tasks": []}
        goals.save_goals(data, path=self.target)
        goals.save_goals({"goals": [], "tasks": []}, path=self.target)
        with open(self.target, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.assertEqual(goals.load_goals(path=self.target), data)
        with open(self.target, "w", encoding="utf-8") as handle:
            handle.write("[]")
        self.assertEqual(goals.load_goals(path=self.target), data)

    def test_concurrent_saves_are_serialized(self):
        def worker(index: int) -> None:
            goals.save_goals(
                {"goals": [{"id": str(index)}], "tasks": []},
                path=self.target,
            )

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        result = goals.load_goals(path=self.target)
        self.assertEqual(len(result["goals"]), 1)
        self.assertFalse(glob.glob(os.path.join(self.tmp, "nested", "*.tmp")))


class TestGameData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-data-")
        self.valid = os.path.join(self.tmp, "valid.json")
        with open(self.valid, "w", encoding="utf-8") as handle:
            json.dump({"ok": [1, 2]}, handle)
        self.broken = os.path.join(self.tmp, "broken.json")
        with open(self.broken, "w", encoding="utf-8") as handle:
            handle.write("{nope")

    def tearDown(self):
        gamedata.clear_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cache_identity_and_missing(self):
        first = gamedata.load_json("valid.json", data_dir=self.tmp)
        second = gamedata.load_json("valid.json", data_dir=self.tmp)
        self.assertIs(first, second)
        self.assertEqual(first, {"ok": [1, 2]})
        self.assertEqual(gamedata.load_json("missing.json", data_dir=self.tmp), {})
        gamedata.clear_cache()
        third = gamedata.load_json("valid.json", data_dir=self.tmp)
        self.assertIsNot(first, third)

    def test_corrupt_json_is_a_data_error(self):
        with self.assertRaises(gamedata.DataError) as context:
            gamedata.load_json("broken.json", data_dir=self.tmp)
        self.assertEqual(context.exception.kind, "data_error")
        self.assertTrue(context.exception.steps)


class TestCatalog(unittest.TestCase):
    def test_item_info_and_row_fallback(self):
        items = {"128": {"en": "Pufferfish", "ru": "", "sp": [0, 128], "p": 200, "t": "Fish"}}
        info = item_info(items, "128")
        self.assertEqual(info["ru"], "Pufferfish")
        self.assertEqual(info["price"], 200)
        missing = item_info(items, "999")
        self.assertEqual((missing["ru"], missing["en"]), ("#999", "#999"))
        self.assertEqual(missing["grp"], "other")
        row = item_row(items, "128", True, {"count": 4})
        self.assertTrue(row["done"])
        self.assertEqual(row["count"], 4)
        self.assertEqual(row["type"], "Fish")
        self.assertEqual(item_row(items, "128", False)["seasons"], [])


class TestPerfection(unittest.TestCase):
    def _inputs(self, *, craft_rows=None, people=None, raw=None):
        craft_rows = craft_rows or [{"done": False, "rec_en": "Craft"}]
        people = people or [{"hearts": 0, "perf_done": False}]
        raw = raw or {"money": 0, "walnuts": 0, "player_count": 1, "perfection_waivers": 0}
        fish_rows = [{"done": False}]
        museum_rows = [{"donated": False, "found": False}]
        ship_rows = [{"done": False}]
        cook_rows = [{"done": False}]
        monster_rows = [{"done": False}]
        counts = compute_counts(
            fish_rows=fish_rows,
            museum_rows=museum_rows,
            ship_rows=ship_rows,
            cook_rows=cook_rows,
            craft_rows=craft_rows,
            monster_rows=monster_rows,
            people=people,
            raw=raw,
        )
        state = build_perfection(
            counts,
            craft_rows=craft_rows,
            people=people,
            farmer_level=0,
            monster_rows=monster_rows,
            monsters_state={"slayer_hero": False},
            obelisk_rows=[{"done": False}] * 4,
            has_gold_clock=False,
            stardrop_rows=[{"done": False}],
            all_stardrops=False,
            raw=raw,
        )
        return counts, state

    def test_weights_and_zero_state(self):
        counts, state = self._inputs()
        self.assertEqual(len(state["categories"]), 11)
        self.assertEqual(sum(row["weight"] for row in state["categories"]), 100)
        self.assertEqual(state["pct"], 0.0)
        self.assertEqual(counts["perfection"], [0.0, 100])
        self.assertEqual(counts["hearts"], [0, 10])

    def test_waivers_are_added_and_clamped(self):
        raw = {"money": 0, "walnuts": 0, "player_count": 1, "perfection_waivers": 5}
        _counts, state = self._inputs(raw=raw)
        self.assertEqual(state["pct"], 5.0)
        raw["perfection_waivers"] = 150
        _counts, state = self._inputs(raw=raw)
        self.assertEqual(state["pct"], 100.0)

    def test_wedding_ring_only_required_in_multiplayer(self):
        craft_rows = [
            {"done": True, "rec_en": "Wedding Ring"},
            {"done": False, "rec_en": "Craft"},
        ]
        single_raw = {"money": 0, "walnuts": 0, "player_count": 1, "perfection_waivers": 0}
        _counts, single = self._inputs(craft_rows=craft_rows, raw=single_raw)
        crafting = next(row for row in single["categories"] if row["key"] == "crafting")
        self.assertEqual((crafting["have"], crafting["total"]), (0, 1))
        multi_raw = dict(single_raw, player_count=2)
        _counts, multi = self._inputs(craft_rows=craft_rows, raw=multi_raw)
        crafting = next(row for row in multi["categories"] if row["key"] == "crafting")
        self.assertEqual((crafting["have"], crafting["total"]), (1, 2))


class TestMultiplayerAndSecurity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-mp-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, body: str) -> str:
        folder = os.path.join(self.tmp, name)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def test_farmhands_found_after_long_player_node(self):
        filler = "".join(f"<junk><n>{index}</n></junk>" for index in range(4500))
        path = self._write(
            "Ферма_1",
            '<?xml version="1.0" encoding="utf-8"?>'
            "<SaveGame>"
            "<player><name>Хозяин</name><farmName>Общая</farmName>"
            "<dayOfMonth>1</dayOfMonth><currentSeason>spring</currentSeason>"
            "<year>1</year><timeOfDay>600</timeOfDay>"
            f"{filler}"
            "</player>"
            "<farmhands><Farmer><name>Гость</name><farmName>Общая</farmName></Farmer></farmhands>"
            "</SaveGame>",
        )
        state = build_state(save_path=path)
        self.assertEqual(state["meta"]["farm"], "Общая")
        self.assertEqual(state["meta"]["players"], 2)

    def test_doctype_and_entity_are_rejected(self):
        for name, body in {
            "bomb": (
                '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]>'
                "<SaveGame><player><name>&a;</name></player></SaveGame>"
            ),
            "entity": '<SaveGame><!ENTITY x "y"><player/></SaveGame>',
        }.items():
            path = self._write(name, body * 20)
            with self.assertRaises(SaveError) as context:
                parse_save(path)
            self.assertEqual(context.exception.kind, "corrupt_save")

    def test_weather_flags_fallback(self):
        path = self._write(
            "Погода_1",
            "<SaveGame><player><name>Ф</name><farmName>П</farmName>"
            "<dayOfMonth>1</dayOfMonth><currentSeason>spring</currentSeason>"
            "<year>1</year><timeOfDay>600</timeOfDay></player>"
            "<isGreenRain>true</isGreenRain></SaveGame>",
        )
        state = build_state(save_path=path)
        self.assertEqual(state["meta"]["weather"], "green_rain")


class TestRenderHelpers(unittest.TestCase):
    def test_inline_sprites_css(self):
        tmp = tempfile.mkdtemp(prefix="sdv-sprites-")
        try:
            with open(os.path.join(tmp, "objects.png"), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n")
            css = _inline_sprites_css(tmp)
            self.assertIn("--spr-obj0:url('data:image/png;base64,", css)
            self.assertNotIn("--spr-ui", css)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_render_custom_template(self):
        tmp = tempfile.mkdtemp(prefix="sdv-tpl-")
        try:
            template = os.path.join(tmp, "tpl.html")
            with open(template, "w", encoding="utf-8") as handle:
                handle.write(
                    "<script>window.__STATE__ = /*__STATE__*/ null;"
                    "window.__ERROR__ = /*__ERROR__*/ null;"
                    'window.__MODE__ = /*__MODE_VALUE__*/ "live";</script>'
                    "/*__INLINE_SPRITES__*/"
                )
            html = render({"x": 1}, "live", template_path=template)
            self.assertIn('window.__STATE__ = {"x": 1};', html)
            self.assertIn('window.__MODE__ = "live";', html)
            with self.assertRaises(FileNotFoundError):
                render(None, "live", template_path=os.path.join(tmp, "missing.html"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCli(unittest.TestCase):
    def test_build_command_and_version(self):
        tmp = tempfile.mkdtemp(prefix="sdv-cli-")
        try:
            write_test_save(tmp)
            target = os.path.join(tmp, "report.html")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["build", "--saves-dir", tmp, "--out", target])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(target))
            self.assertIn("Done", output.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as context:
                    build_parser().parse_args(["--version"])
            self.assertEqual(context.exception.code, 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_info_command(self):
        tmp = tempfile.mkdtemp(prefix="sdv-cli-info-")
        try:
            write_test_save(tmp)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["info", "--saves-dir", tmp])
            self.assertEqual(code, 0)
            text = output.getvalue()
            self.assertIn("Тестовая", text)
            self.assertIn("perfection", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestConcurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sdv-concurrency-")
        cls.save = write_test_save(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_parallel_parse_and_state(self):
        parsed: list[dict] = []
        states: list[dict] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                item = parse_save(self.save)
                state = build_state(save_path=self.save)
                with lock:
                    parsed.append(item)
                    states.append(state)
            except BaseException as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(errors, [])
        self.assertTrue(all(item is parsed[0] for item in parsed))
        self.assertTrue(all(state["meta"]["farm"] == "Тестовая" for state in states))
        self.assertEqual(len(states), 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)

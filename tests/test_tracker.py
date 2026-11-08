#!/usr/bin/env python3
"""Тесты трекера. Запуск:  python -m unittest discover -s tests -v

Зависимостей нет — только стандартная библиотека.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from make_test_save import write_test_save

import tracker


class TestData(unittest.TestCase):
    """Целостность справочников в data/."""

    def test_items(self):
        items = tracker.load_json("items.json")
        self.assertGreater(len(items), 700)
        for uid in ("128", "194", "749"):
            self.assertIn(uid, items)
        self.assertEqual(items["128"]["en"], "Pufferfish")
        self.assertEqual(items["128"]["ru"], "Иглобрюх")
        for row in items.values():
            self.assertTrue(row["ru"] and row["en"], row)

    def test_fish(self):
        fish = tracker.load_json("fish.json")
        items = tracker.load_json("items.json")
        self.assertEqual(len(fish), 74)
        for uid, info in fish.items():
            self.assertIn(uid, items, f"рыба {uid} отсутствует в items.json")
            self.assertIn("season", info)
            self.assertIsInstance(info.get("loc"), list)

    def test_museum(self):
        m = tracker.load_json("museum.json")
        self.assertEqual(len(m["artifacts"]), 42)
        self.assertEqual(len(m["minerals"]), 53)
        self.assertFalse(set(m["artifacts"]) & set(m["minerals"]))
        locations = tracker.load_json("artifact_locations.json")
        self.assertEqual(set(locations), set(m["artifacts"]))
        for sources in locations.values():
            self.assertTrue(sources["en"] and sources["ru"])
            self.assertEqual(len(sources["en"]), len(sources["ru"]))

    def test_recipes(self):
        r = tracker.load_json("recipes.json")
        self.assertEqual(len(r["cooking"]), 81)
        self.assertEqual(len(r["crafting"]), 150)
        self.assertEqual(r["cooking"]["Fried Egg"]["item"], "194")
        self.assertEqual(len(r["cooking"]["Fried Egg"]["ing"]), 1)

    def test_npcs(self):
        n = tracker.load_json("npcs.json")["npcs"]
        self.assertEqual(len(n), 34)
        abi = n["Abigail"]
        self.assertEqual([s.lower() for s in [abi["birth"][0]]], ["fall"])
        self.assertEqual(abi["birth"][1], 13)
        self.assertTrue(abi["love"])
        self.assertTrue(abi["ru"])

    def test_shipping_and_bundles(self):
        ship = tracker.load_json("shipping.json")
        items = tracker.load_json("items.json")
        self.assertEqual(len(ship), 155)
        for uid in ship:
            self.assertIn(str(uid), items)
        rooms = tracker.load_json("bundles.json")["rooms"]
        total = sum(len(r["list"]) for r in rooms)
        self.assertEqual(total, 31)
        self.assertTrue(all(b["name_ru"] for r in rooms for b in r["list"]))

    def test_sprite_and_guild_data(self):
        monsters = tracker.load_json("monsters.json")["goals"]
        self.assertEqual(len(monsters), 12)
        self.assertEqual(sum(m["target"] for m in monsters), 2620)
        for name in (
            "objects.png",
            "objects2.png",
            "craftables.png",
            "bundles.png",
            "npcs.png",
            "monsters.png",
            "ui.png",
        ):
            self.assertTrue(
                os.path.isfile(os.path.join(tracker.SPRITES_DIR, name)), name
            )

    def test_data_localization_and_sprite_refs(self):
        items = tracker.load_json("items.json")
        self.assertTrue(all(i.get("ru") and i.get("en") for i in items.values()))
        self.assertTrue(all(i.get("sp") for i in items.values()))


class TestSaveParsing(unittest.TestCase):
    """Полный проход: синтетический сейв -> состояние."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sdv-test-")
        cls.save = write_test_save(cls.tmp)
        cls.state = tracker.build_state(save_path=cls.save)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_meta(self):
        m = self.state["meta"]
        self.assertEqual(m["farm"], "Тестовая")
        self.assertEqual(m["farmer"], "Фермер")
        self.assertEqual(m["season"], "fall")
        self.assertEqual(m["day"], 12)
        self.assertEqual(m["year"], 3)
        self.assertEqual(m["clock"], "13:50")
        self.assertEqual(m["money"], 54230)
        self.assertEqual(m["walnuts"], 74)

    def test_counts(self):
        c = self.state["counts"]
        self.assertEqual(c["fish"], [8, 74])  # 701 поймана 0 раз — не считается
        self.assertEqual(c["museum"], [4, 95])  # сдано
        self.assertEqual(c["museum_found"], [8, 95])  # найдено (археология + минералы)
        self.assertEqual(c["shipped"], [5, 155])
        self.assertEqual(c["cooking"], [3, 81])
        self.assertEqual(c["crafting"], [6, 150])

    def test_found_but_not_donated(self):
        alert = self.state["alerts"]["museum_found_not_donated"]
        self.assertEqual(len(alert), 4)  # 96/100/114/561 найдены, 96/100 сданы
        names = {a["en"] for a in alert}
        self.assertIn("Frozen Tear", names)
        dwarf_scroll = next(r for r in self.state["museum"] if r["id"] == "96")
        self.assertEqual(
            dwarf_scroll["locations"], tracker.load_json("artifact_locations.json")["96"]
        )

    def test_bundles(self):
        rooms = {r["key"]: r for r in self.state["bundles"]}
        pantry = rooms["Pantry"]
        spring = next(b for b in pantry["list"] if b["slot"] == 0)
        self.assertTrue(spring["complete"])
        self.assertEqual((spring["have"], spring["need"]), (4, 4))
        summer = next(b for b in pantry["list"] if b["slot"] == 1)
        self.assertFalse(summer["complete"])
        self.assertEqual((summer["have"], summer["need"]), (2, 4))

    def test_people(self):
        people = {p["key"]: p for p in self.state["people"]}
        abi = people["Abigail"]
        self.assertEqual(abi["hearts"], 7)  # 1875 очков
        self.assertEqual(abi["birth"], ["fall", 13])
        self.assertEqual(abi["until"], 1)  # 12 осени -> 13 осени
        self.assertTrue(abi["loved"])
        self.assertEqual(abi["gifts_week"], 1)
        # сортировка: ближайший день рождения первым
        self.assertEqual(self.state["people"][0]["key"], "Abigail")

    def test_fish_extra_fields(self):
        fish = {f["id"]: f for f in self.state["fish"]}
        puffer = fish["128"]
        self.assertTrue(puffer["done"])
        self.assertEqual(puffer["count"], 4)
        self.assertEqual(puffer["seasons"], ["summer"])
        self.assertTrue(puffer["locs"])
        # осень 13:50, лето — значит "ловится сейчас" быть не должно
        self.assertFalse(puffer["now"])

    def test_warnings_empty(self):
        self.assertEqual(self.state["meta"]["warnings"], [])

    def test_perfection_and_today_panels(self):
        p = self.state["perfection"]
        self.assertEqual(sum(row["weight"] for row in p["categories"]), 100)
        self.assertEqual(len(p["categories"]), 11)
        self.assertEqual(len(p["obelisks"]), 4)
        self.assertEqual(self.state["skills"]["farmer_level"], 22)
        self.assertEqual(self.state["monsters"]["completed"], [5, 12])
        self.assertEqual(self.state["monsters"]["deepest_mine"], 120)
        self.assertEqual(self.state["monsters"]["skull_cavern"], 35)
        self.assertEqual(self.state["meta"]["weather"], "sunny")
        self.assertEqual(self.state["meta"]["weather_tomorrow"], "rainy")
        self.assertIn("fish_now", self.state["today"])
        self.assertIn("bundles_close", self.state["today"])

    def test_save_parse_cache_signature(self):
        first = tracker.parse_save(self.save)
        second = tracker.parse_save(self.save)
        self.assertIs(first, second)
        before = os.stat(self.save)
        with open(self.save, "a", encoding="utf-8") as fh:
            fh.write(" ")
        os.utime(self.save, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000000))
        third = tracker.parse_save(self.save)
        self.assertIsNot(first, third)


class TestEdgeCases(unittest.TestCase):
    def test_minimal_save(self):
        """Сейв без коллекций не должен ломать сборку состояния."""
        tmp = tempfile.mkdtemp(prefix="sdv-min-")
        try:
            folder = os.path.join(tmp, "Новая_111")
            os.makedirs(folder)
            path = os.path.join(folder, "Новая_111")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    '<?xml version="1.0" encoding="utf-8"?>\n'
                    '<SaveGame xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                    "<player><name>Новичок</name><farmName>Новая</farmName>"
                    "<money>500</money><dayOfMonth>1</dayOfMonth>"
                    "<currentSeason>spring</currentSeason><year>1</year>"
                    "<timeOfDay>610</timeOfDay></player>"
                    "<locations></locations></SaveGame>"
                )
            st = tracker.build_state(save_path=path)
            self.assertEqual(st["counts"]["fish"][0], 0)
            self.assertEqual(st["counts"]["museum"][0], 0)
            self.assertEqual(st["meta"]["farm"], "Новая")
            self.assertTrue(st["meta"]["warnings"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_goals_shape_is_safely_normalized(self):
        self.assertEqual(
            tracker.normalize_goals(
                {"goals": "bad", "tasks": None, "annotations": ["bad"]}
            ),
            {"goals": [], "tasks": []},
        )

    def test_goals_annotations_roundtrip(self):
        tmp = tempfile.mkdtemp(prefix="sdv-notes-")
        old = tracker.GOALS_FILE
        try:
            tracker.GOALS_FILE = os.path.join(tmp, "goals.json")
            data = {
                "goals": [],
                "tasks": [],
                "annotations": {"fish:128": {"marked": True, "note": "Try in summer"}},
            }
            tracker.save_goals(data)
            self.assertEqual(tracker.load_goals(), data)
            tracker.save_goals(
                {
                    "goals": [],
                    "tasks": [],
                    "annotations": {
                        "fish:128": {"marked": False, "note": "Later"},
                    },
                }
            )
            with open(tracker.GOALS_FILE + ".bak", encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), data)
            with open(tracker.GOALS_FILE, "w", encoding="utf-8") as fh:
                fh.write("{broken json")
            self.assertEqual(tracker.load_goals(), data)
        finally:
            tracker.GOALS_FILE = old
            shutil.rmtree(tmp, ignore_errors=True)

    def test_friendly_corrupt_save_error(self):
        tmp = tempfile.mkdtemp(prefix="sdv-corrupt-")
        try:
            path = os.path.join(tmp, "BrokenSave")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("<SaveGame><player>")
            with self.assertRaises(tracker.SaveError) as ctx:
                tracker.parse_save(path)
            self.assertEqual(ctx.exception.kind, "corrupt_save")
            self.assertTrue(ctx.exception.steps)
            with self.assertRaises(tracker.SaveError) as missing:
                tracker.parse_save(os.path.join(tmp, "missing"))
            self.assertEqual(missing.exception.kind, "no_saves")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_norm_id(self):
        self.assertEqual(tracker.norm_id("(O)128"), "128")
        self.assertEqual(tracker.norm_id("128"), "128")
        self.assertEqual(tracker.norm_id(128), "128")
        self.assertEqual(tracker.norm_id("Moss"), "Moss")

    def test_clock_and_birthdays(self):
        self.assertEqual(tracker.fmt_clock(1350), "13:50")
        self.assertEqual(tracker.fmt_clock(600), "06:00")
        self.assertEqual(tracker.fmt_clock(2600), "26:00")  # 2:00 ночи в терминах игры
        cur = tracker.abs_day("fall", 12, 3)
        self.assertEqual(tracker.days_until_birthday(cur, "fall", 13), 1)
        self.assertEqual(tracker.days_until_birthday(cur, "fall", 12), 0)
        # прошедший день рождения — считается до следующего года
        self.assertEqual(tracker.days_until_birthday(cur, "fall", 11), 4 * 28 - 1)

    def test_goals_roundtrip(self):
        tmp = tempfile.mkdtemp(prefix="sdv-goals-")
        old = tracker.GOALS_FILE
        try:
            tracker.GOALS_FILE = os.path.join(tmp, "goals.json")
            g = {
                "goals": [
                    {"id": "a", "title": "тест", "metric": "museum", "target": 60}
                ],
                "tasks": [{"id": "b", "title": "таск", "done": False}],
            }
            tracker.save_goals(g)
            self.assertEqual(tracker.load_goals(), g)
            with open(tracker.GOALS_FILE, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), g)
            next_goals = {"goals": [], "tasks": []}
            tracker.save_goals(next_goals)
            self.assertEqual(tracker.load_goals(), next_goals)
            with open(tracker.GOALS_FILE + ".bak", encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), g)
        finally:
            tracker.GOALS_FILE = old
            shutil.rmtree(tmp, ignore_errors=True)


class TestRender(unittest.TestCase):
    def test_injection_placeholders_and_mode(self):
        live = tracker.render(None, "live")
        self.assertIn('window.__MODE__ = "live";', live)
        self.assertIn("window.__STATE__ = null;", live)
        self.assertIn("window.__ERROR__ = null;", live)
        self.assertNotIn("window.live =", live)
        static = tracker.render(None, "static")
        self.assertIn('window.__MODE__ = "static";', static)
        self.assertEqual(static.count("data:image/png;base64,"), 7)


class TestHTTPAPI(unittest.TestCase):
    """HTTP contract, request validation, and local-only save selection."""

    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer

        self.tmp = tempfile.mkdtemp(prefix="sdv-http-")
        self.old_goals = tracker.GOALS_FILE
        self.old_state = tracker.Handler.state
        self.old_error = tracker.Handler.error
        self.old_save = tracker.Handler.save
        self.old_saves_dir = tracker.Handler.saves_dir
        tracker.GOALS_FILE = os.path.join(self.tmp, "goals.json")
        tracker.Handler.saves_dir = self.tmp
        tracker.Handler.save = write_test_save(self.tmp)
        tracker.Handler.state = tracker.build_state(save_path=tracker.Handler.save)
        tracker.Handler.error = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), tracker.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        tracker.GOALS_FILE = self.old_goals
        tracker.Handler.state = self.old_state
        tracker.Handler.error = self.old_error
        tracker.Handler.save = self.old_save
        tracker.Handler.saves_dir = self.old_saves_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, path, payload=None):
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method="POST" if data is not None else "GET",
        )
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as exc:
            response = exc
        return response, response.read()

    def test_goals_and_state_roundtrip(self):
        payload = {
            "goals": [],
            "tasks": [],
            "annotations": {"fish:128": {"marked": True, "note": "Summer afternoons"}},
        }
        response, body = self.request("/api/goals", payload)
        self.assertEqual(response.status, 200)
        self.assertTrue(json.loads(body)["ok"])
        response, body = self.request("/api/state")
        self.assertEqual(response.status, 200)
        self.assertEqual(
            json.loads(body)["goals"]["annotations"], payload["annotations"]
        )
        response, body = self.request("/api/goals/export")
        self.assertEqual(json.loads(body), payload)
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_rejects_invalid_payload_and_unlisted_save(self):
        response, _body = self.request("/api/saves/select", [])
        self.assertEqual(response.status, 400)
        response, _body = self.request("/api/goals", {"goals": "not-an-array"})
        self.assertEqual(response.status, 400)
        from http.client import HTTPConnection

        host, port = self.server.server_address
        connection = HTTPConnection(host, port, timeout=3)
        connection.putrequest("POST", "/api/goals")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", "1000001")
        connection.putheader("Connection", "close")
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 413)
        response.read()
        connection.close()
        outside = tempfile.mkdtemp(prefix="sdv-unlisted-")
        try:
            fake = os.path.join(outside, "NotMine")
            with open(fake, "w", encoding="utf-8") as fh:
                fh.write("<SaveGame><player>" + (" " * 300) + "</player></SaveGame>")
            response, body = self.request("/api/saves/select", {"path": fake})
            self.assertEqual(response.status, 403)
            self.assertIn("Недопустимый файл", json.loads(body)["error"])
        finally:
            shutil.rmtree(outside, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

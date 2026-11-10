#!/usr/bin/env python3
"""Интеграционные тесты трекера.

Запуск:  python -m unittest discover -s tests -v
Зависимостей нет — только стандартная библиотека.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from make_test_save import write_test_save  # noqa: E402

import tracker  # noqa: E402
from stardew_tracker import (  # noqa: E402
    TrackerApp,
    TrackerHTTPServer,
    build_state,
    load_json,
    parse_save,
    paths,
)
from stardew_tracker import goals as goals_module  # noqa: E402


class TestData(unittest.TestCase):
    """Целостность справочников в data/."""

    def test_items(self):
        items = load_json("items.json")
        self.assertGreater(len(items), 700)
        for uid in ("128", "194", "749"):
            self.assertIn(uid, items)
        self.assertEqual(items["128"]["en"], "Pufferfish")
        self.assertEqual(items["128"]["ru"], "Иглобрюх")
        for row in items.values():
            self.assertTrue(row["ru"] and row["en"], row)

    def test_fish(self):
        fish = load_json("fish.json")
        items = load_json("items.json")
        self.assertEqual(len(fish), 74)
        for uid, info in fish.items():
            self.assertIn(uid, items, f"рыба {uid} отсутствует в items.json")
            self.assertIn("season", info)
            self.assertIsInstance(info.get("loc"), list)

    def test_museum(self):
        museum = load_json("museum.json")
        self.assertEqual(len(museum["artifacts"]), 42)
        self.assertEqual(len(museum["minerals"]), 53)
        self.assertFalse(set(museum["artifacts"]) & set(museum["minerals"]))
        locations = load_json("artifact_locations.json")
        self.assertEqual(set(locations), set(museum["artifacts"]))
        for sources in locations.values():
            self.assertTrue(sources["en"] and sources["ru"])
            self.assertEqual(len(sources["en"]), len(sources["ru"]))

    def test_recipes(self):
        recipes = load_json("recipes.json")
        self.assertEqual(len(recipes["cooking"]), 81)
        self.assertEqual(len(recipes["crafting"]), 150)
        self.assertEqual(recipes["cooking"]["Fried Egg"]["item"], "194")
        self.assertEqual(len(recipes["cooking"]["Fried Egg"]["ing"]), 1)

    def test_npcs(self):
        npcs = load_json("npcs.json")["npcs"]
        self.assertEqual(len(npcs), 34)
        abigail = npcs["Abigail"]
        self.assertEqual([season.lower() for season in [abigail["birth"][0]]], ["fall"])
        self.assertEqual(abigail["birth"][1], 13)
        self.assertTrue(abigail["love"])
        self.assertTrue(abigail["ru"])
        self.assertEqual(sorted(npc["p_idx"] for npc in npcs.values()), list(range(34)))

    def test_shipping_and_bundles(self):
        shipping = load_json("shipping.json")
        items = load_json("items.json")
        self.assertEqual(len(shipping), 155)
        for uid in shipping:
            self.assertIn(str(uid), items)
        rooms = load_json("bundles.json")["rooms"]
        total = sum(len(room["list"]) for room in rooms)
        self.assertEqual(total, 31)
        self.assertTrue(all(bundle["name_ru"] for room in rooms for bundle in room["list"]))

    def test_sprite_and_guild_data(self):
        monsters = load_json("monsters.json")["goals"]
        self.assertEqual(len(monsters), 12)
        self.assertEqual(sum(goal["target"] for goal in monsters), 2620)
        for name in (
            "objects.png",
            "objects2.png",
            "craftables.png",
            "bundles.png",
            "npcs.png",
            "monsters.png",
            "ui.png",
        ):
            self.assertTrue(os.path.isfile(os.path.join(paths.SPRITES_DIR, name)), name)

    def test_data_localization_and_sprite_refs(self):
        items = load_json("items.json")
        self.assertTrue(all(item.get("ru") and item.get("en") for item in items.values()))
        self.assertTrue(all(item.get("sp") for item in items.values()))

    def test_referential_integrity(self):
        """Все ссылки между справочниками разрешаются."""

        items = load_json("items.json")
        recipes = load_json("recipes.json")
        bundles = load_json("bundles.json")
        for group in ("cooking", "crafting"):
            for name, recipe in recipes[group].items():
                self.assertTrue(recipe["ru"] and recipe["en"], name)
                for ingredient in recipe.get("ing") or []:
                    self.assertGreaterEqual(len(ingredient), 3, name)
        for room in bundles["rooms"]:
            for bundle in room["list"]:
                self.assertLessEqual(bundle["need_count"], len(bundle["items"]), bundle["name_en"])
                for item in bundle["items"]:
                    if item["id"] != "-1":
                        self.assertIn(str(item["id"]), items, bundle["name_en"])
        for uid, fish in load_json("fish.json").items():
            for location in fish.get("loc") or []:
                self.assertTrue(location["ru"] and location["en"], uid)


class TestSaveParsing(unittest.TestCase):
    """Полный проход: синтетический сейв -> состояние."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sdv-test-")
        cls.save = write_test_save(cls.tmp)
        cls.state = build_state(save_path=cls.save)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_meta(self):
        meta = self.state["meta"]
        self.assertEqual(meta["farm"], "Тестовая")
        self.assertEqual(meta["farmer"], "Фермер")
        self.assertEqual(meta["season"], "fall")
        self.assertEqual(meta["day"], 12)
        self.assertEqual(meta["year"], 3)
        self.assertEqual(meta["clock"], "13:50")
        self.assertEqual(meta["money"], 54230)
        self.assertEqual(meta["walnuts"], 74)

    def test_counts(self):
        counts = self.state["counts"]
        self.assertEqual(counts["fish"], [8, 74])  # 701 поймана 0 раз — не считается
        self.assertEqual(counts["museum"], [4, 95])  # сдано
        self.assertEqual(counts["museum_found"], [8, 95])  # найдено (археология + минералы)
        self.assertEqual(counts["shipped"], [5, 155])
        self.assertEqual(counts["cooking"], [3, 81])
        self.assertEqual(counts["crafting"], [6, 150])

    def test_found_but_not_donated(self):
        alert = self.state["alerts"]["museum_found_not_donated"]
        self.assertEqual(len(alert), 4)  # 96/100/114/561 найдены, 96/100 сданы
        names = {item["en"] for item in alert}
        self.assertIn("Frozen Tear", names)
        dwarf_scroll = next(row for row in self.state["museum"] if row["id"] == "96")
        self.assertEqual(
            dwarf_scroll["locations"],
            load_json("artifact_locations.json")["96"],
        )

    def test_bundles(self):
        rooms = {room["key"]: room for room in self.state["bundles"]}
        pantry = rooms["Pantry"]
        spring = next(bundle for bundle in pantry["list"] if bundle["slot"] == 0)
        self.assertTrue(spring["complete"])
        self.assertEqual((spring["have"], spring["need"]), (4, 4))
        summer = next(bundle for bundle in pantry["list"] if bundle["slot"] == 1)
        self.assertFalse(summer["complete"])
        self.assertEqual((summer["have"], summer["need"]), (2, 4))

    def test_people(self):
        people = {person["key"]: person for person in self.state["people"]}
        abigail = people["Abigail"]
        self.assertEqual(abigail["hearts"], 7)  # 1875 очков
        self.assertEqual(abigail["birth"], ["fall", 13])
        self.assertEqual(abigail["until"], 1)  # 12 осени -> 13 осени
        self.assertTrue(abigail["loved"])
        self.assertEqual(abigail["gifts_week"], 1)
        # сортировка: ближайший день рождения первым
        self.assertEqual(self.state["people"][0]["key"], "Abigail")

    def test_fish_extra_fields(self):
        fish = {item["id"]: item for item in self.state["fish"]}
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
        perfection = self.state["perfection"]
        self.assertEqual(sum(row["weight"] for row in perfection["categories"]), 100)
        self.assertEqual(len(perfection["categories"]), 11)
        self.assertEqual(len(perfection["obelisks"]), 4)
        # Удача (+4) не должна раздувать Farmer Level: (10+9+9+8+8)//2 = 22.
        self.assertEqual(self.state["skills"]["farmer_level"], 22)
        self.assertEqual(self.state["monsters"]["completed"], [5, 12])
        self.assertEqual(self.state["monsters"]["deepest_mine"], 120)
        self.assertEqual(self.state["monsters"]["skull_cavern"], 35)
        self.assertEqual(self.state["meta"]["weather"], "sunny")
        self.assertEqual(self.state["meta"]["weather_tomorrow"], "rainy")
        self.assertIn("fish_now", self.state["today"])
        self.assertIn("bundles_close", self.state["today"])
        self.assertEqual(self.state["meta"]["players"], 1)

    def test_save_parse_cache_signature(self):
        first = parse_save(self.save)
        second = parse_save(self.save)
        self.assertIs(first, second)
        before = os.stat(self.save)
        with open(self.save, "a", encoding="utf-8") as handle:
            handle.write(" ")
        os.utime(self.save, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        third = parse_save(self.save)
        self.assertIsNot(first, third)

    def test_state_cache_does_not_leak_mutations(self):
        first = build_state(save_path=self.save)
        first["meta"]["farm"] = "Изменено"
        first["counts"]["fish"][0] = -1
        second = build_state(save_path=self.save)
        self.assertEqual(second["meta"]["farm"], "Тестовая")
        self.assertEqual(second["counts"]["fish"][0], 8)


class TestEdgeCases(unittest.TestCase):
    def test_minimal_save(self):
        """Сейв без коллекций не должен ломать сборку состояния."""

        tmp = tempfile.mkdtemp(prefix="sdv-min-")
        try:
            folder = os.path.join(tmp, "Новая_111")
            os.makedirs(folder)
            path = os.path.join(folder, "Новая_111")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    '<?xml version="1.0" encoding="utf-8"?>\n'
                    '<SaveGame xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                    "<player><name>Новичок</name><farmName>Новая</farmName>"
                    "<money>500</money><dayOfMonth>1</dayOfMonth>"
                    "<currentSeason>spring</currentSeason><year>1</year>"
                    "<timeOfDay>610</timeOfDay></player>"
                    "<locations></locations></SaveGame>"
                )
            state = build_state(save_path=path)
            self.assertEqual(state["counts"]["fish"][0], 0)
            self.assertEqual(state["counts"]["museum"][0], 0)
            self.assertEqual(state["meta"]["farm"], "Новая")
            self.assertTrue(state["meta"]["warnings"])
            self.assertEqual(state["skills"]["farmer_level"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_goals_shape_is_safely_normalized(self):
        self.assertEqual(
            tracker.normalize_goals({"goals": "bad", "tasks": None, "annotations": ["bad"]}),
            {"goals": [], "tasks": []},
        )

    def test_goals_annotations_roundtrip(self):
        tmp = tempfile.mkdtemp(prefix="sdv-notes-")
        try:
            target = os.path.join(tmp, "goals.json")
            data = {
                "goals": [],
                "tasks": [],
                "annotations": {"fish:128": {"marked": True, "note": "Try in summer"}},
            }
            goals_module.save_goals(data, path=target)
            self.assertEqual(goals_module.load_goals(path=target), data)
            goals_module.save_goals(
                {
                    "goals": [],
                    "tasks": [],
                    "annotations": {"fish:128": {"marked": False, "note": "Later"}},
                },
                path=target,
            )
            with open(target + ".bak", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), data)
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("{broken json")
            self.assertEqual(goals_module.load_goals(path=target), data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_friendly_corrupt_save_error(self):
        tmp = tempfile.mkdtemp(prefix="sdv-corrupt-")
        try:
            path = os.path.join(tmp, "BrokenSave")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("<SaveGame><player>")
            with self.assertRaises(tracker.SaveError) as context:
                parse_save(path)
            self.assertEqual(context.exception.kind, "corrupt_save")
            self.assertTrue(context.exception.steps)
            with self.assertRaises(tracker.SaveError) as missing:
                parse_save(os.path.join(tmp, "missing"))
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
        current = tracker.abs_day("fall", 12, 3)
        self.assertEqual(tracker.days_until_birthday(current, "fall", 13), 1)
        self.assertEqual(tracker.days_until_birthday(current, "fall", 12), 0)
        # прошедший день рождения — считается до следующего года
        self.assertEqual(tracker.days_until_birthday(current, "fall", 11), 4 * 28 - 1)


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

    def test_state_is_script_safe(self):
        html = tracker.render({"farm": "</script><script>alert(1)</script>"}, "live")
        self.assertNotIn("</script><script>alert(1)", html)
        self.assertIn("<\\/script>", html)

    def test_build_report_is_atomic(self):
        tmp = tempfile.mkdtemp(prefix="sdv-report-")
        try:
            save = write_test_save(tmp)
            target = os.path.join(tmp, "nested", "report.html")
            _state, path = tracker.build_report(save, out_path=target)
            self.assertEqual(path, target)
            self.assertTrue(os.path.getsize(target) > 500_000)
            self.assertFalse(os.path.exists(target + ".tmp"))
            with open(target, encoding="utf-8") as handle:
                self.assertIn('window.__MODE__ = "static";', handle.read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestHTTPAPI(unittest.TestCase):
    """HTTP-контракт, валидация запросов и локальный выбор сейва."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-http-")
        self._old_goals_file = paths.GOALS_FILE
        paths.GOALS_FILE = os.path.join(self.tmp, "goals.json")
        self.addCleanup(setattr, paths, "GOALS_FILE", self._old_goals_file)
        self.app = TrackerApp(saves_dir=self.tmp, save=write_test_save(self.tmp))
        self.app.load()
        self.server = TrackerHTTPServer(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, path, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = dict(headers or {})
        if data is not None:
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(
            self.base + path,
            data=data,
            headers=request_headers,
            method="POST" if data is not None else "GET",
        )
        try:
            response = urlopen(request, timeout=3)
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
        self.assertEqual(json.loads(body)["goals"]["annotations"], payload["annotations"])
        response, body = self.request("/api/goals/export")
        self.assertEqual(json.loads(body), payload)
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_security_headers_and_server_banner(self):
        response, body = self.request("/")
        self.assertEqual(response.status, 200)
        self.assertIn(b'window.__MODE__ = "live";', body)
        self.assertIn("default-src 'self'", response.headers.get("Content-Security-Policy", ""))
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("Referrer-Policy"), "no-referrer")
        self.assertEqual(response.headers.get("Server"), "StardewTracker")
        self.assertNotIn("Python", response.headers.get("Server", ""))

    def test_saves_and_sprite_routes(self):
        response, body = self.request("/api/saves")
        payload = json.loads(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(len(payload["saves"]), 1)
        self.assertEqual(payload["active"], self.app.state["meta"]["save_path"])
        response, body = self.request("/assets/sprites/ui.png")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("Content-Type"), "image/png")
        self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")
        response, _body = self.request("/assets/sprites/../../tracker.py")
        self.assertEqual(response.status, 404)

    def test_refresh_and_unknown_route(self):
        response, body = self.request("/api/refresh")
        self.assertEqual(response.status, 200)
        self.assertIn("meta", json.loads(body))
        response, body = self.request("/nope")
        self.assertEqual(response.status, 404)
        self.assertEqual(json.loads(body)["error"], "not found")

    def test_options_does_not_grant_cors(self):
        connection = HTTPConnection(*self.server.server_address, timeout=3)
        connection.request("OPTIONS", "/api/goals")
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 204)
        self.assertIn("GET", response.headers.get("Allow", ""))
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
        connection.close()

    def test_rejects_invalid_payload_and_unlisted_save(self):
        response, _body = self.request("/api/saves/select", [])
        self.assertEqual(response.status, 400)
        response, _body = self.request("/api/goals", {"goals": "not-an-array"})
        self.assertEqual(response.status, 400)
        response, _body = self.request("/api/goals", {"annotations": []})
        self.assertEqual(response.status, 400)

        connection = HTTPConnection(*self.server.server_address, timeout=3)
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
            with open(fake, "w", encoding="utf-8") as handle:
                handle.write("<SaveGame><player>" + (" " * 300) + "</player></SaveGame>")
            response, body = self.request("/api/saves/select", {"path": fake})
            self.assertEqual(response.status, 403)
            self.assertIn("Недопустимый файл", json.loads(body)["error"])
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_refresh_failure_returns_structured_error(self):
        os.unlink(self.app.save)
        response, body = self.request("/api/refresh")
        self.assertEqual(response.status, 500)
        self.assertEqual(json.loads(body)["error"]["kind"], "no_saves")

    def test_saves_listing_error_is_reported(self):
        with mock.patch(
            "stardew_tracker.server.list_saves_info",
            side_effect=tracker.SaveError("io_error", "Ошибка", "Нет доступа", ["Проверьте диск"]),
        ):
            response, body = self.request("/api/saves")
        self.assertEqual(response.status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["saves"], [])
        self.assertEqual(payload["error"]["kind"], "io_error")

    def test_goals_disk_error_returns_400(self):
        payload = {"goals": [], "tasks": []}
        with mock.patch("stardew_tracker.server.save_goals", side_effect=OSError("disk full")):
            response, body = self.request("/api/goals", payload)
        self.assertEqual(response.status, 400)
        self.assertIn("disk full", json.loads(body)["error"])

    def test_missing_template_returns_500(self):
        with mock.patch("stardew_tracker.server.render", side_effect=FileNotFoundError):
            response, body = self.request("/")
        self.assertEqual(response.status, 500)
        self.assertIn("dashboard.html", body.decode("utf-8"))

    def test_content_type_and_json_validation(self):
        connection = HTTPConnection(*self.server.server_address, timeout=3)
        connection.request(
            "POST",
            "/api/goals",
            body=b"{}",
            headers={"Content-Type": "text/plain"},
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 415)
        connection.close()

        connection = HTTPConnection(*self.server.server_address, timeout=3)
        connection.request(
            "POST",
            "/api/goals",
            body=b"{broken",
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 400)
        connection.close()


class TestHTTPNoSave(unittest.TestCase):
    def test_state_404_until_save_appears(self):
        tmp = tempfile.mkdtemp(prefix="sdv-empty-")
        app = TrackerApp(saves_dir=tmp)
        try:
            app.load()
        except tracker.SaveError as exc:
            app.set_error(exc)
        server = TrackerHTTPServer(("127.0.0.1", 0), app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/state", timeout=3) as response:
                payload = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertIn("error", payload)
        except HTTPError as exc:
            self.assertEqual(exc.code, 404)
            payload = json.loads(exc.read())
            self.assertEqual(payload["error"]["kind"], "no_saves")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            shutil.rmtree(tmp, ignore_errors=True)


class TestCompatibility(unittest.TestCase):
    def test_tracker_shim_exports(self):
        for name in (
            "build_state",
            "build_report",
            "find_saves",
            "parse_save",
            "render",
            "serve",
            "load_json",
            "normalize_goals",
            "SaveError",
            "__version__",
        ):
            self.assertTrue(hasattr(tracker, name), name)

    def test_cli_accepts_legacy_commands(self):
        from stardew_tracker.cli import build_parser

        parser = build_parser()
        for command in ("serve", "build", "info", "open"):
            self.assertEqual(parser.parse_args([command]).cmd, command)
        self.assertEqual(parser.parse_args([]).cmd, "serve")
        self.assertEqual(parser.parse_args([]).host, "127.0.0.1")


if __name__ == "__main__":
    unittest.main(verbosity=2)

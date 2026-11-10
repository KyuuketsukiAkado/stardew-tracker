"""Тесты сборщика справочников и собственного PNG-кодека."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build_data  # noqa: E402


class TestPngCodec(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-png-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def roundtrip(self, rows, width, height):
        path = os.path.join(self.tmp, "nested", "image.png")
        build_data.write_png(path, width, height, rows)
        self.assertTrue(os.path.isfile(path))
        read_w, read_h, read_rows = build_data.read_png(path)
        self.assertEqual((read_w, read_h), (width, height))
        self.assertEqual([bytes(row) for row in read_rows], [bytes(row) for row in rows])

    def test_rgba_roundtrip_with_transparency(self):
        rows = [
            bytearray(b"\xff\x00\x00\xff\x00\x00\x00\x00\x00\x00\xff\xff"),
            bytearray(b"\x00\x00\x00\x00\x10\x20\x30\x40\x50\x60\x70\x80"),
        ]
        self.roundtrip(rows, 3, 2)

    def test_indexed_roundtrip(self):
        rows = [
            bytearray(b"\xff\x00\x00\xff\x00\xff\x00\xff"),
            bytearray(b"\xff\x00\x00\xff\x00\xff\x00\xff"),
        ]
        self.roundtrip(rows, 2, 2)

    def test_more_than_256_colors_uses_rgba(self):
        width = 350
        row = bytearray()
        for index in range(width):
            row.extend((index % 256, (index * 3) % 256, (index * 7) % 256, 255))
        self.roundtrip([row], width, 1)

    def test_repo_sprites_decode(self):
        expected = {
            "bundles.png": (640, 96),
            "craftables.png": (128, 1472),
            "monsters.png": (192, 64),
            "npcs.png": (384, 384),
            "objects.png": (384, 624),
            "objects2.png": (128, 320),
            "ui.png": (256, 32),
        }
        for name, size in expected.items():
            path = os.path.join(ROOT, "assets", "sprites", name)
            width, height, rows = build_data.read_png(path)
            self.assertEqual((width, height), size, name)
            self.assertEqual(len(rows), height, name)
            self.assertTrue(any(any(row) for row in rows), name)

    def test_rejects_non_png(self):
        path = os.path.join(self.tmp, "bad.png")
        with open(path, "wb") as handle:
            handle.write(b"not a png")
        with self.assertRaises(ValueError):
            build_data.read_png(path)

    def test_canvas_and_blit_clipping(self):
        canvas = build_data.make_canvas(2, 2)
        self.assertEqual(len(canvas), 2)
        self.assertEqual(len(canvas[0]), 8)
        source = [bytearray(b"\x01\x02\x03\x04" * 2) for _ in range(2)]
        build_data.blit(canvas, source, 0, 0, 2, 2, 1, 1)
        self.assertEqual(bytes(canvas[1][4:8]), b"\x01\x02\x03\x04")
        # полностью за пределами — ничего не меняется и нет исключения
        build_data.blit(canvas, source, 0, 0, 2, 2, 10, 10)
        build_data.blit(canvas, source, 10, 10, 2, 2, 0, 0)


class TestBuildHelpers(unittest.TestCase):
    def test_parse_int_map(self):
        self.assertEqual(build_data.parse_int_map(" 1 2,3/4  "), ["1", "2", "3", "4"])
        self.assertEqual(build_data.parse_int_map(""), [])

    def test_item_group(self):
        cases = {
            ("Arch", 0, "96"): "artifact",
            ("Minerals", 0, "72"): "mineral",
            ("Fish", 0, "128"): "fish",
            ("Cooking", 0, "194"): "cooking",
            ("Basic", -75, "24"): "vegetable",
            ("Basic", -79, "400"): "fruit",
            ("Basic", -80, "591"): "flower",
            ("Basic", -23, "715"): "forage",
            ("Basic", -18, "440"): "animal",
            ("Basic", -26, "348"): "artisan",
            ("Basic", -15, "335"): "metal",
            ("Basic", -28, "766"): "monster",
            ("Basic", -16, "388"): "resource",
            ("Basic", -74, "472"): "seed",
            ("Basic", 0, "1"): "other",
        }
        for args, expected in cases.items():
            self.assertEqual(build_data.item_group(*args), expected, args)

    def test_format_unlock(self):
        npcs = {"Abigail": {"ru": "Абигейл", "en": "Abigail"}}
        self.assertEqual(build_data.format_unlock("", npcs)["ru"], "Магазин / событие")
        self.assertEqual(build_data.format_unlock("default", npcs)["en"], "Starter recipe")
        self.assertEqual(build_data.format_unlock("s Farming 5", npcs)["ru"], "Фермерство ур. 5")
        self.assertEqual(build_data.format_unlock("f Abigail 2", npcs)["ru"], "Абигейл (2♥)")
        self.assertIn("Королева соуса", build_data.format_unlock("l 100", npcs)["ru"])
        self.assertEqual(build_data.format_unlock("custom", npcs), {"ru": "custom", "en": "custom"})

    def test_find_file_by_exact_and_basename(self):
        tmp = tempfile.mkdtemp(prefix="sdv-content-")
        try:
            nested = os.path.join(tmp, "Data")
            os.makedirs(nested)
            target = os.path.join(nested, "Objects.json")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("{}")
            self.assertEqual(build_data.find_file(tmp, "Data/Objects.json"), target)
            self.assertEqual(build_data.find_file(tmp, "wrong/path/Objects.json"), target)
            self.assertIsNone(build_data.find_file(tmp, "missing.json"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_resolver_localization(self):
        tmp = tempfile.mkdtemp(prefix="sdv-resolver-")
        try:
            strings = os.path.join(tmp, "Strings")
            os.makedirs(strings)
            with open(os.path.join(strings, "Objects.json"), "w", encoding="utf-8") as handle:
                json.dump({"Oak_Name": "Oak"}, handle)
            with open(os.path.join(strings, "Objects.ru-RU.json"), "w", encoding="utf-8") as handle:
                json.dump({"Oak_Name": "Дуб"}, handle)
            resolver = build_data.Resolver(tmp)
            token = "[LocalizedText Strings\\Objects:Oak_Name]"
            self.assertEqual(resolver.text(token, "en"), "Oak")
            self.assertEqual(resolver.text(token, "ru"), "Дуб")
            self.assertEqual(resolver.text("plain", "ru"), "plain")
            self.assertEqual(
                build_data.Resolver(os.path.join(tmp, "empty")).text("[LocalizedText Strings\\Objects:Missing_Name]"),
                "Missing",
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

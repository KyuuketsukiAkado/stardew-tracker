"""Парсер на «раздутых» сейвах: теги корня после огромных <locations>.

Эти тесты защищают от двух проблем, найденных в архитектурном аудите:

* значения, которые игра хранит прямыми потомками ``<SaveGame>`` ПОСЛЕ
  ``<locations>`` (``perfectionWaivers``), не находились: поиск шёл по первым
  5000 узлам документа, а один только ``<locations>`` в тысячи раз больше;
* каждый такой тег стоил отдельного полного обхода дерева (~5 из 7 секунд
  разбора сейва в 25 МБ).
"""

from __future__ import annotations

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

from make_test_save import build_xml, write_test_save  # noqa: E402

from stardew_tracker import saveparser, xmlutil  # noqa: E402
from stardew_tracker.state import list_saves_info  # noqa: E402

# Всё, что парсер ищет по всему документу, если тега нет среди детей корня.
ROOT_TAILS = "<perfectionWaivers>5</perfectionWaivers><farmhands/><completedSpecialOrders/><whichFarm>2</whichFarm>"


def _save_info_xml(**fields: object) -> str:
    values = {
        "name": "Анна",
        "farmName": "Лунная",
        "currentSeason": "winter",
        "dayOfMonth": 9,
        "year": 4,
        "money": 12345,
    }
    values.update(fields)
    body = "".join(f"<{key}>{value}</{key}>" for key, value in values.items() if value is not None)
    return f'<?xml version="1.0"?><Farmer xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">{body}</Farmer>'


class TestRootTagsAfterHugeLocations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-scale-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        saveparser.clear_cache()
        self.addCleanup(saveparser.clear_cache)

    def _parse(self, **kwargs):
        path = write_test_save(self.tmp, **kwargs)
        return path, saveparser.parse_save(path)

    def test_padding_really_exceeds_the_old_node_limit(self):
        root = ET.fromstring(build_xml(pad_objects=300))
        self.assertGreater(sum(1 for _ in root.iter()), 5000)

    def test_perfection_waivers_found_after_huge_locations(self):
        _path, raw = self._parse(pad_objects=300, root_tail="<perfectionWaivers>5</perfectionWaivers>")
        self.assertEqual(raw["perfection_waivers"], 5)
        self.assertEqual(raw["walnuts"], 74)

    def test_missing_waivers_default_to_zero(self):
        _path, raw = self._parse(pad_objects=300)
        self.assertEqual(raw["perfection_waivers"], 0)

    def test_padding_does_not_change_parsed_progress(self):
        _path, plain = self._parse()
        saveparser.clear_cache()
        _path, padded = self._parse(pad_objects=300)
        self.assertEqual(plain, padded)

    def test_direct_root_children_never_trigger_a_full_scan(self):
        with mock.patch.object(xmlutil, "index_descendants", side_effect=AssertionError("full scan")):
            _path, raw = self._parse(pad_objects=300, root_tail=ROOT_TAILS)
        self.assertEqual(raw["perfection_waivers"], 5)
        self.assertEqual(raw["farm_type"], 2)

    def test_descendant_index_is_built_once_for_many_missing_tags(self):
        root = ET.fromstring("<SaveGame><player><a><year>3</year><deep>7</deep></a></player></SaveGame>")
        lookup = saveparser._TagLookup(root)
        with mock.patch.object(xmlutil, "index_descendants", wraps=xmlutil.index_descendants) as spy:
            self.assertEqual(xmlutil.txt(lookup.get("year")), "3")
            self.assertEqual(xmlutil.txt(lookup.get("deep")), "7")
            self.assertIsNone(lookup.get("absent"))
            self.assertIsNone(lookup.get("another"))
        self.assertEqual(spy.call_count, 1)

    def test_direct_child_wins_over_earlier_nested_tag(self):
        root = ET.fromstring("<SaveGame><player><year>1</year></player><year>9</year></SaveGame>")
        self.assertEqual(xmlutil.txt(saveparser._TagLookup(root).get("year")), "9")


class TestXmlIndexes(unittest.TestCase):
    def test_index_descendants_keeps_document_order_and_strips_namespaces(self):
        root = ET.fromstring(
            '<r xmlns:p="urn:x"><a><p:t>1</p:t></a><t>2</t><b><t>3</t></b></r>',
        )
        index = xmlutil.index_descendants(root)
        self.assertEqual(xmlutil.txt(index["t"]), "1")
        self.assertIn("a", index)
        self.assertIn("b", index)

    def test_index_children_ignores_deeper_levels(self):
        root = ET.fromstring("<r><a><x>1</x></a><x>2</x><x>3</x></r>")
        index = xmlutil.index_children(root)
        self.assertEqual(xmlutil.txt(index["x"]), "2")
        self.assertEqual(xmlutil.index_children(None), {})

    def test_ln_handles_namespaces_and_non_elements(self):
        root = ET.fromstring('<r xmlns:p="urn:x"><p:t/></r>')
        self.assertEqual(xmlutil.ln(root[0]), "t")
        self.assertEqual(xmlutil.ln(root), "r")
        self.assertEqual(xmlutil.ln(None), "")
        self.assertEqual(xmlutil.ln(ET.Comment("c")), "")


class TestSaveSummary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdv-summary-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        saveparser.clear_cache()
        self.addCleanup(saveparser.clear_cache)
        self.path = write_test_save(self.tmp)
        self.info = os.path.join(os.path.dirname(self.path), "SaveGameInfo")

    def _write_info(self, text: str) -> None:
        with open(self.info, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_summary_is_read_from_save_game_info(self):
        self._write_info(_save_info_xml())
        summary = saveparser.read_save_summary(self.path)
        self.assertEqual(
            summary,
            {"name": "Анна", "farm_name": "Лунная", "season": "winter", "day": 9, "year": 4, "money": 12345},
        )

    def test_incomplete_or_foreign_info_is_rejected(self):
        for broken in (
            "<SaveGame/>",  # как в синтетическом сейве
            _save_info_xml(farmName=None),
            _save_info_xml(currentSeason="monsoon"),
            _save_info_xml(dayOfMonth=None),
            "<Farmer><broken",
        ):
            self._write_info(broken)
            self.assertIsNone(saveparser.read_save_summary(self.path), broken)

    def test_missing_info_file_is_none(self):
        os.unlink(self.info)
        self.assertIsNone(saveparser.read_save_summary(self.path))

    def test_stale_info_is_not_trusted(self):
        self._write_info(_save_info_xml())
        old = os.path.getmtime(self.path) - 10_000
        os.utime(self.info, (old, old))
        self.assertIsNone(saveparser.read_save_summary(self.path))

    def test_save_list_uses_summary_without_parsing_the_save(self):
        self._write_info(_save_info_xml())
        with mock.patch.object(saveparser, "_parse_uncached", side_effect=AssertionError("full parse")):
            saves = list_saves_info(saves_dir=self.tmp)
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0]["farm"], "Лунная")
        self.assertEqual(saves[0]["farmer"], "Анна")
        self.assertEqual(saves[0]["season"], "winter")
        self.assertEqual((saves[0]["day"], saves[0]["year"], saves[0]["money"]), (9, 4, 12345))

    def test_save_list_falls_back_to_full_parse(self):
        saves = list_saves_info(saves_dir=self.tmp)  # SaveGameInfo = <SaveGame/>
        self.assertEqual(saves[0]["farm"], "Тестовая")
        self.assertEqual(saves[0]["day"], 12)

    def test_parsed_save_has_priority_over_summary(self):
        saveparser.parse_save(self.path)
        self._write_info(_save_info_xml())
        saves = list_saves_info(saves_dir=self.tmp)
        self.assertEqual(saves[0]["farm"], "Тестовая")


class TestParseLocks(unittest.TestCase):
    def test_lock_is_per_file(self):
        first = saveparser._parse_lock("a")
        self.assertIs(first, saveparser._parse_lock("a"))
        self.assertIsNot(first, saveparser._parse_lock("b"))

    def test_slow_parse_of_one_save_does_not_block_another(self):
        started = threading.Event()
        release = threading.Event()
        order: list[str] = []

        def slow(signature):
            order.append("slow-start")
            started.set()
            release.wait(5)
            return {"slow": True}

        def fast(signature):
            order.append("fast")
            return {"fast": True}

        sigs = {"slow": ("slow", 1, 1), "fast": ("fast", 1, 1)}
        parse = mock.patch.object(
            saveparser, "_parse_uncached", side_effect=lambda s: slow(s) if s[0] == "slow" else fast(s)
        )
        with mock.patch.object(saveparser, "_file_sig", side_effect=lambda p: sigs[p]):
            with parse:
                worker = threading.Thread(target=saveparser.parse_save, args=("slow",), daemon=True)
                worker.start()
                self.assertTrue(started.wait(5))
                self.assertEqual(saveparser.parse_save("fast"), {"fast": True})
                release.set()
                worker.join(5)
        self.assertEqual(order, ["slow-start", "fast"])


if __name__ == "__main__":
    unittest.main()

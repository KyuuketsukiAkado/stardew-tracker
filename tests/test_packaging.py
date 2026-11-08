"""Пути standalone-сборки и состав PyInstaller-спеки."""

from __future__ import annotations

import unittest
from pathlib import Path

from stardew_tracker import paths

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "stardew-tracker.spec"


class ResourceRootTests(unittest.TestCase):
    def test_source_tree_ignores_meipass(self) -> None:
        self.assertEqual(
            paths.resource_root(frozen=False, meipass="/tmp/bundle"),
            ROOT,
        )

    def test_frozen_bundle_uses_meipass(self) -> None:
        self.assertEqual(
            paths.resource_root(frozen=True, meipass="/tmp/bundle"),
            Path("/tmp/bundle").resolve(),
        )

    def test_frozen_without_meipass_falls_back_to_source(self) -> None:
        self.assertEqual(paths.resource_root(frozen=True, meipass=None), ROOT)


class UserDataDirTests(unittest.TestCase):
    def test_windows_appdata(self) -> None:
        result = paths.user_data_dir(
            platform="win32",
            env={"APPDATA": r"C:\Users\farmer\AppData\Roaming"},
            home=r"C:\Users\farmer",
        )
        self.assertEqual(result, Path(r"C:\Users\farmer\AppData\Roaming") / "StardewTracker")

    def test_windows_without_appdata(self) -> None:
        result = paths.user_data_dir(platform="win32", env={}, home="/home/farmer")
        self.assertEqual(result, Path("/home/farmer/AppData/Roaming/StardewTracker"))

    def test_macos(self) -> None:
        result = paths.user_data_dir(platform="darwin", env={}, home="/Users/farmer")
        self.assertEqual(result, Path("/Users/farmer/Library/Application Support/StardewTracker"))

    def test_linux_respects_xdg(self) -> None:
        result = paths.user_data_dir(platform="linux", env={"XDG_DATA_HOME": "/data"}, home="/home/farmer")
        self.assertEqual(result, Path("/data/StardewTracker"))

    def test_linux_default(self) -> None:
        result = paths.user_data_dir(platform="linux", env={}, home="/home/farmer")
        self.assertEqual(result, Path("/home/farmer/.local/share/StardewTracker"))

    def test_home_override_wins(self) -> None:
        result = paths.user_data_dir(
            platform="win32",
            env={"STARDEW_TRACKER_HOME": "~/portable"},
            home="/home/farmer",
        )
        self.assertEqual(result, Path("~/portable").expanduser())


class SpecTests(unittest.TestCase):
    def test_spec_bundles_resources_and_entry_point(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn("tracker.py", text)
        self.assertIn('"data"', text)
        self.assertIn('"assets"', text)

    def test_build_script_and_requirements_exist(self) -> None:
        self.assertTrue((ROOT / "packaging" / "build_app.py").is_file())
        self.assertIn("pyinstaller", (ROOT / "requirements-build.txt").read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()

"""Пути standalone-сборки и состав PyInstaller-спеки."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from stardew_tracker import cli, paths

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "stardew-tracker.spec"


class VersionTests(unittest.TestCase):
    """Версия в программе, в метаданных и в теге релиза не должна расходиться."""

    def test_pyproject_matches_the_runtime_version(self) -> None:
        import re

        from stardew_tracker.version import __version__

        match = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(match)
        # pyproject — PEP 440 (0.4.0b1), в программе и теге — читаемая запись (0.4.0-beta.1)
        pep440 = re.sub(
            r"-(alpha|beta|rc)\.(\d+)$", lambda m: {"alpha": "a", "beta": "b", "rc": "rc"}[m[1]] + m[2], __version__
        )
        self.assertEqual(match.group(1), pep440)

    def test_version_has_a_release_tag_shape(self) -> None:

        from stardew_tracker.version import __version__

        self.assertRegex(__version__, r"^\d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?$")
        self.assertTrue(f"v{__version__}".startswith("v"))  # тег релиза = «v» + версия

    def test_cli_reports_the_version(self) -> None:
        import contextlib
        import io

        from stardew_tracker.version import __version__

        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--version"])
        self.assertIn(__version__, out.getvalue())


class ReleaseWorkflowTests(unittest.TestCase):
    """Job Release ни разу не запускался до первого тега: защищаем то, что сломало бы его."""

    text = (ROOT / ".github" / "workflows" / "build-app.yml").read_text(encoding="utf-8")

    def test_build_logs_are_not_packed_into_the_release(self) -> None:
        # без этого цикл по скачанным артефактам доходил до каталога *-log и падал на chmod
        self.assertIn("*-log) continue", self.text)
        self.assertIn('pattern: "StardewTracker-*"', self.text)

    def test_release_has_checksums_and_versioned_names(self) -> None:
        self.assertIn("sha256sum", self.text)
        self.assertIn("${name}-${GITHUB_REF_NAME}.zip", self.text)

    def test_hyphenated_tags_are_prereleases_and_the_tag_must_exist(self) -> None:
        self.assertIn("--prerelease", self.text)
        self.assertIn("--verify-tag", self.text)

    def test_release_job_checks_the_repository_out_for_the_notes(self) -> None:
        release_job = self.text.split("  release:", 1)[1]
        self.assertIn("actions/checkout", release_job)
        self.assertIn(".github/release-notes/", release_job)


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


class _RecordingStream:
    def __init__(self) -> None:
        self.options: dict[str, str] = {}

    def reconfigure(self, **kwargs: str) -> None:
        self.options.update(kwargs)


class _FailingStream:
    def reconfigure(self, **kwargs: str) -> None:
        raise ValueError("closed")


class StdioTests(unittest.TestCase):
    def test_configure_stdio_replaces_encoding_errors(self) -> None:
        out, err = _RecordingStream(), _RecordingStream()
        with mock.patch.object(cli.sys, "stdout", out), mock.patch.object(cli.sys, "stderr", err):
            cli.configure_stdio()
        self.assertEqual(out.options, {"errors": "replace"})
        self.assertEqual(err.options, {"errors": "replace"})

    def test_configure_stdio_tolerates_broken_and_plain_streams(self) -> None:
        with (
            mock.patch.object(cli.sys, "stdout", _FailingStream()),
            mock.patch.object(cli.sys, "stderr", object()),
        ):
            cli.configure_stdio()


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

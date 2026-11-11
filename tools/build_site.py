#!/usr/bin/env python3
"""Build the GitHub Pages landing page into ``_site/`` (or ``--out``).

    python tools/build_site.py                 # writes _site/
    python tools/build_site.py --out /tmp/site

The page is ``site/index.template.html`` with the download links filled in from the
app version, so the buttons always point at the files of the current release
(``releases/download/v<version>/StardewTracker-<os>-v<version>.zip``). Nothing is
fetched at run time and nothing is committed that could go stale: the
``Pages`` workflow runs this script on every push to ``master``.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from stardew_tracker.version import __version__  # noqa: E402

OWNER = "KyuuketsukiAkado"
REPO = "stardew-tracker"
EMAIL = "repro4chful@gmail.com"
TEMPLATE = os.path.join(ROOT, "site", "index.template.html")
SCREENSHOTS = os.path.join(ROOT, "docs", "screenshots")
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def values(version: str = __version__) -> dict[str, str]:
    repo_url = f"https://github.com/{OWNER}/{REPO}"
    tag = f"v{version}"

    def asset(system: str) -> str:
        return f"{repo_url}/releases/download/{tag}/StardewTracker-{system}-{tag}.zip"

    prerelease = "-" in version
    return {
        "VERSION": version,
        "TAG": tag,
        "REPO_URL": repo_url,
        "RELEASES_URL": f"{repo_url}/releases",
        "ISSUES_URL": f"{repo_url}/issues/new/choose",
        "SITE_URL": f"https://{OWNER.lower()}.github.io/{REPO}/",
        "WINDOWS_URL": asset("windows"),
        "MACOS_URL": asset("macos"),
        "LINUX_URL": asset("linux"),
        "EMAIL": EMAIL,
        "CHANNEL_EN": "Public beta" if prerelease else "Release",
        "CHANNEL_RU": "Публичная бета" if prerelease else "Релиз",
    }


def render_page(version: str = __version__) -> str:
    with open(TEMPLATE, encoding="utf-8") as handle:
        template = handle.read()
    filled = values(version)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in filled:
            raise KeyError(f"unknown placeholder {{{{{name}}}}} in {TEMPLATE}")
        return filled[name]

    return PLACEHOLDER.sub(replace, template)


def build(out: str, version: str = __version__) -> list[str]:
    """Write the site and return the relative paths of the files created."""

    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    written = []

    with open(os.path.join(out, "index.html"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_page(version))
    written.append("index.html")

    # Plain static files: Pages must not run Jekyll over them.
    with open(os.path.join(out, ".nojekyll"), "w", encoding="utf-8") as handle:
        handle.write("")
    written.append(".nojekyll")

    target = os.path.join(out, "screenshots")
    os.makedirs(target)
    for name in sorted(os.listdir(SCREENSHOTS)):
        if name.lower().endswith(".png"):
            shutil.copyfile(os.path.join(SCREENSHOTS, name), os.path.join(target, name))
            written.append(f"screenshots/{name}")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the GitHub Pages landing page")
    parser.add_argument("--out", default=os.path.join(ROOT, "_site"), help="output folder (default: _site)")
    args = parser.parse_args(argv)
    files = build(args.out)
    print(f"Built {len(files)} files into {os.path.relpath(args.out, ROOT)} (version {__version__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

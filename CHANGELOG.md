# Changelog

🇷🇺 [Русская версия (подробная)](CHANGELOG.ru.md) — the Russian changelog is the detailed one.

## Unreleased

- **Landing page UX:** current beta.3 screenshots from a fictional farm appear before the feature list, with phone-sized images on narrow screens. Phone visitors preview the interface instead of getting a Windows download button; Mac visitors see the Apple Silicon limitation, and unsigned-app guidance remains available in a keyboard-friendly disclosure. CI now checks the rendered site at phone and desktop widths.

## v0.4.0-beta.4 — security patch (2026-11-12)

- Refuse cross-origin HTTP writes to local goals, consent and save-selection endpoints. POST requests now require the exact JSON MIME type rather than a JSON-looking substring in another content type. Same-origin browser actions and CLI requests still work.
- Escape the metric label of imported goals when rendering HTML, without discarding unknown or older goal metrics. Add regression checks for both issues.

## v0.4.0-beta.3 — phone usability and safer save discovery (2026-11-12)

- **Permission before scanning for saves.** On first launch the app lists the standard save folders and asks for consent before looking in them. You can choose another folder instead or withdraw permission later from Folders; nothing is uploaded.
- **40×40 px item controls.** ☆, ✎ and information hints in the museum, fish, shipping, cooking, crafting, Today and Saved items are easier to tap. Bundle items now open their 40×40 px actions when selected; Enter/Space, Tab and Escape work with visible focus. The saved annotation keys and progress calculations are unchanged.
- **Browser checks in CI.** The existing jsdom UI smoke and real-Chrome visual/keyboard smoke now run automatically on the synthetic demo. The first Linux CI run exposed a 23 px overflow in the bundle grid at 320 px; narrow cards and grid tracks are fixed without weakening the test.
- **Fixed wrong item pictures on phones.** At 450 px and narrower, item icons shrank to 28 px while their sprite offsets stayed at 32 px, so lists showed parts of neighbouring sprites (every fish and shipping icon, almost the whole museum). Icons now pass only the sprite column and row, and the CSS works out size, sheet scale and offset from one cell size, so any resize stays aligned. `tools/visual_smoke.js` checks every icon on every route.
- **Overview leads with one thing you can do today.** A "You can do today" card sits right under the greeting: a villager's birthday without a gift yet, items already found but not donated to the museum, or a fish biting now in a place the save shows as unlocked (in that order). Close bundles are never offered there, because "2 left" does not mean you own the items. When nothing qualifies the card says so plainly. The choice is made in Python (`today.next_action`); fish rows gain `open_locs`.
- **Calmer metrics:** perfection, museum and fish are three neutral tiles instead of a bright hero and a coloured museum tile; status colour appears only on the progress bar (gold in progress, green complete), always next to the number. Shipping, cooking and crafting tiles follow the same style. Links to museum, fish and perfection stay.
- **Phone first screen:** the beta notice keeps its full text and contacts but takes about 90 px instead of about 160 px, the greeting stops repeating the date from the header, and the three main metrics share one row, so the action fits on a 390×844 screen without scrolling or dismissing anything.
- **Overview metric readability:** large values and their `%`/`/total` units have separate spacing and upright digits in both themes; the old italic inline suffix could overlap. A [first-screen UX audit](docs/UX-AUDIT.md) records hierarchy, status-color and touch-target follow-ups.
- **Landing page on GitHub Pages** (`site/`, built by `tools/build_site.py`, published by the new **Pages** workflow): a short "what and why", screenshots, a download button that picks Windows / macOS / Linux for the visitor, and the feedback address. The page is plain HTML with no external requests, always in the light Frost look, in English with a Russian switch (own title, description and screenshots), and its download links follow the app version automatically. A styled 404 page is included.
- Packaged-app messages name the right command: error hints say `StardewTracker info` instead of `python tracker.py info`, and the permission hint points at the real saves folder.

## v0.4.0-beta.2 — English by default, language chooser (2026-11-11)

A beta for collecting feedback from English-speaking players.

### Language

- The interface is **English by default**. On first launch a small dialog asks which language you want (your browser's language is suggested and "Remember my choice" is ticked); afterwards the **EN / RU** button switches it. An earlier saved choice is kept.
- The console, `--help` and error messages follow the **system language** (Windows display language; `LC_ALL` / `LANG` elsewhere; anything but Russian falls back to English). Override with `--lang en|ru` or `STARDEW_TRACKER_LANG`.
- Save-reading errors, parser warnings and HTTP API errors are bilingual: the page shows an error in the language chosen in the interface, not the console language.
- The English interface shows English item names only; the Russian one shows the Russian name with the English one beside it.
- `run.bat`, `report.bat` and `build_app.bat` print their messages in both languages.

### Feedback

- Beta builds show a small dismissible banner inside the app: *questions, bugs and suggestions — repro4chful@gmail.com or GitHub issues* (dismissal is remembered per version).
- README is now in English (`README.md`, Russian in `README.ru.md`), this changelog is in English, and the repository has issue templates.

### Wording

- Texts no longer assume the reader's gender: the Russian spoiler warning says «догадаться самому», and when a save has no player name the greeting is simply «Привет!».

### Fixed

- `tools/build_demo.py` crashed with `UnicodeEncodeError` on a Windows console (cp1252) while printing Cyrillic. Its messages are now English, and the demo shows a fictional farm, *Sunny Acres*, with English names.
- State is deep-copied by the cache; bilingual texts are now immutable and copy correctly.
- `meta.app_version` was added to the state (the page uses it to decide whether to show the beta banner).

## v0.4.0-beta.1 — first beta (2026-11-11)

Everything since v0.3.0. The redesign is only partly done (stage 1 of 4), and the macOS and Linux builds are verified by an automatic smoke test only.

- **Secrets on demand.** The solutions of the *Secrets · danger zone* section (~30 KB) are no longer in every `/api/state` response or in the page source; the live server returns them from `GET /api/secrets` only after you agree, and the page forgets them when you leave. `GET /?save=…` no longer switches the active save.
- **Fixes found on real 1.6 saves.** Access flags (`hasSkullKey`, `hasRustyKey`, `hasDarkTalisman`, `hasMagicInk`, `hasClubCard`) are empty in 1.6 saves and live in the mail instead, so the Skull Cavern, Witch's Swamp and Mutant Bug Lair were shown as locked for players who had long been there. The Joja mail name is `JojaMember`, matched now without case. Fish you have already caught are no longer shown as locked. The farm list now reads `SaveGameInfo` in its real format (4 farms: 2367 → 85 ms).
- **Faster.** Parsing a 23 MB save: 7.3 → ~3.0 s (one tree walk instead of six). A browser tab polls a ~60-byte `/api/version` instead of ~450 KB every 3 seconds; `/api/state` supports `ETag` and gzip.
- **More robust.** The save watcher retries after a transient failure; parallel goal saves no longer lose marks; `perfectionWaivers` is now found in real saves; the `Host` header is checked on loopback (DNS-rebinding protection); state inserted into the page escapes `<!--`, U+2028 and U+2029.
- **Refactoring.** `SaveError` no longer inherits `SystemExit` (`TrackerError` → `SaveError` → `DataError`); modules renamed (`collections` → `rows`, `requirements` → `unlocks`, `render` → `report`).
- **Redesign "Cold Bento", stage 1 of 4.** Light theme *Frost* (default) and dark theme *Night*; DIN-style typography and a 12-column bento grid; a top bar with five groups of sections; the overview and *Today* pages rebuilt as tiles.
- **Demo and CI.** `docs/index.html` is generated deterministically by `tools/build_demo.py`; CI checks that it is up to date.

## v0.3.0 — unlock requirements, filters, light theme and danger zone (2026-11-10)

- **Requirements.** The tracker reads what you have unlocked (island, Qi's room, desert, Skull Cavern, sewers, mutant bug lair, witch's swamp, Secret Woods, mine floors, mastery, greenhouse, cellar, skills, hearts, the Night Market schedule) from the save and marks what is still locked with 🔒 and a *How to unlock* hint.
- **Filters.** Fish by place, time of day or "in game now", season, weather and gear; museum by where to find; shipping by season and category; recipes by source; "available to me / needs unlocking" everywhere. Filters are remembered.
- **Danger zone.** Solutions for Mr. Qi's special orders, *Mysterious Qi*, secret notes and journal scraps behind a mandatory consent screen; hints and solutions open separately; item icons and 13 self-drawn diagrams.
- **Exact recipe sources**, checked against the 1.6 wiki.
- **Fixes.** Perfection counts for 1.6 (72 fish, 154 shipped items), the Night Market fish schedule, parser edge cases, and several interface bugs.

## v0.2.0 — audit, QA and modular refactoring (2026-11-08)

- The 2114-line `tracker.py` became the `stardew_tracker/` package of 20 modules; `tracker.py` stays as a compatibility facade.
- Security: XML with `DOCTYPE` / `ENTITY` is rejected; the server listens on `127.0.0.1` by default; CSP, `Referrer-Policy`, `nosniff`; no CORS.
- Standalone builds with PyInstaller (Windows, macOS, Linux) and a GitHub Actions workflow.
- QA: coverage 90 %, strict `ruff`, `mypy` and `bandit` gates in CI; details in [`docs/AUDIT.md`](docs/AUDIT.md) (Russian).

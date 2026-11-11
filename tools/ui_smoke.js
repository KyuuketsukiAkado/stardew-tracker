#!/usr/bin/env node
// Optional browser-less UI check: renders the page in jsdom and walks through it.
//
//   npm install --no-save jsdom            # once, in the repository root
//   node tools/ui_smoke.js [page.html]     # default: docs/index.html (the English demo)
//
// It is NOT part of CI (the project has no npm dependencies). Use it after changing
// assets/dashboard.html to catch script errors, untranslated text and broken
// language / banner behaviour without opening a browser.
//
// Checks: every section renders in English and Russian, light and dark, without script
// errors; the English UI contains no Russian text outside the bilingual item-name spans;
// the secrets section works after consent; first-run language chooser, "remember my
// choice", Escape, system-language suggestion, legacy theme migration, beta banner.

"use strict";

const fs = require("fs");
const path = require("path");

let JSDOM, VirtualConsole;
try {
  ({ JSDOM, VirtualConsole } = require("jsdom"));
} catch (error) {
  console.error("jsdom is not installed. Run: npm install --no-save jsdom");
  process.exit(2);
}

const file = path.resolve(process.argv[2] || path.join(__dirname, "..", "docs", "index.html"));
const html = fs.readFileSync(file, "utf8");
const CYRILLIC = /[А-Яа-яЁё]/;
const results = [];
const allErrors = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const check = (name, ok, detail = "") => results.push({ name, ok: !!ok, detail });
const visible = (el) => !!el && !el.classList.contains("hidden");

async function boot({ storage = {}, languages = ["en-US", "en"] } = {}) {
  const errors = [];
  allErrors.push(errors);
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => errors.push(String(e.message).slice(0, 200)));
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "http://localhost:8777/",
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(w) {
      w.scrollTo = () => {};
      w.HTMLElement.prototype.scrollIntoView = () => {};
      Object.defineProperty(w.navigator, "languages", { value: languages, configurable: true });
      Object.defineProperty(w.navigator, "language", { value: languages[0], configurable: true });
      for (const [key, value] of Object.entries(storage)) w.localStorage.setItem(key, value);
    },
  });
  await sleep(250);
  return { w: dom.window, d: dom.window.document, errors };
}

const stored = (w) => Object.fromEntries(Object.keys(w.localStorage).map((k) => [k, w.localStorage.getItem(k)]));
const prefs = (lang, theme = "light") => ({ "sdt.lang": JSON.stringify(lang), "sdt.theme": JSON.stringify(theme) });

function cyrillicOutsideBilingual(root) {
  const found = [];
  const walker = root.ownerDocument.createTreeWalker(root, 4 /* SHOW_TEXT */);
  let node;
  while ((node = walker.nextNode())) {
    if (!CYRILLIC.test(node.nodeValue)) continue;
    if (node.parentElement && node.parentElement.closest(".en")) continue; // second item name
    found.push(node.nodeValue.trim().slice(0, 80));
  }
  return found;
}

async function sectionsWalk() {
  for (const lang of ["en", "ru"]) {
    for (const theme of ["light", "dark"]) {
      const s = await boot({ storage: prefs(lang, theme) });
      const routes = [...new Set([...s.d.querySelectorAll("#mobileNav option")].map((o) => o.value))];
      let bad = [];
      for (const route of routes) {
        s.w.location.hash = route;
        await sleep(110);
        if (lang === "en") bad = bad.concat(cyrillicOutsideBilingual(s.d.getElementById("view")).map((t) => `${route}: ${t}`));
      }
      check(`${lang}/${theme}: ${routes.length} sections render`, routes.length >= 14 && s.d.documentElement.lang === lang);
      if (lang === "en") check(`${lang}/${theme}: no Russian text in the English UI`, bad.length === 0, bad.slice(0, 3).join(" | "));
      s.w.close();
    }
  }
}

async function secrets() {
  const s = await boot({ storage: prefs("en") });
  s.w.location.hash = "secrets";
  await sleep(150);
  s.w.eval("dangerConsent = true; render();");
  await sleep(150);
  s.w.eval('document.querySelectorAll("[data-reveal-key]").forEach((b) => b.click());');
  await sleep(150);
  const view = s.d.getElementById("view");
  check("secrets: entries render after consent", view.querySelectorAll("[data-reveal-key]").length > 20);
  check("secrets: English only", cyrillicOutsideBilingual(view).length === 0);
  s.w.close();
}

async function languageFlow() {
  let s = await boot();
  const modal = s.d.getElementById("langModal");
  check("first run shows the language chooser", visible(modal));
  check("English is suggested for an English browser", s.d.querySelector('[data-lang="en"]').classList.contains("active"));
  check("remember checkbox is ticked by default", s.d.getElementById("langRemember").checked);
  s.d.querySelector('[data-lang="ru"]').click();
  await sleep(150);
  check("choosing Russian switches the page and closes the dialog", s.d.documentElement.lang === "ru" && !visible(modal));
  check("the choice is remembered", stored(s.w)["sdt.lang"] === '"ru"');
  const saved = stored(s.w);
  s.w.close();

  s = await boot({ storage: saved, languages: ["en-US"] });
  check("reload keeps the choice and skips the chooser", s.d.documentElement.lang === "ru" && !visible(s.d.getElementById("langModal")));
  s.d.getElementById("language").click();
  await sleep(100);
  check("EN / RU button toggles and saves", s.d.documentElement.lang === "en" && stored(s.w)["sdt.lang"] === '"en"');
  s.w.close();

  s = await boot();
  s.d.getElementById("langRemember").checked = false;
  s.d.querySelector('[data-lang="ru"]').click();
  await sleep(100);
  check("without 'remember' nothing is stored", stored(s.w)["sdt.lang"] === undefined);
  s.w.close();

  s = await boot({ languages: ["ru-RU", "ru", "en"] });
  check("a Russian browser gets Russian suggested", s.d.querySelector('[data-lang="ru"]').classList.contains("active"));
  s.d.dispatchEvent(new s.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await sleep(100);
  check("Escape accepts the suggestion", !visible(s.d.getElementById("langModal")) && stored(s.w)["sdt.lang"] === '"ru"');
  s.w.close();

  s = await boot({ storage: { "sdt.lang": '"en"', "sdt.theme": '"frost"' } });
  check("legacy 'frost' theme migrates to light", s.d.documentElement.dataset.theme === "light");
  s.w.close();
}

async function betaBanner() {
  let s = await boot({ storage: prefs("en") });
  const banner = s.d.getElementById("betaBanner");
  const version = s.w.eval("S.meta.app_version");
  if (!/alpha|beta|rc|dev/i.test(version)) {
    check("beta banner is skipped for a stable build", !visible(banner), version);
    s.w.close();
    return;
  }
  check("beta banner is visible for a pre-release", visible(banner), version);
  check("banner shows the feedback e-mail", /mailto:repro4chful@gmail\.com/.test(banner.innerHTML));
  const link = banner.querySelector('a[href^="https"]');
  check("banner links to GitHub issues safely", link && /\/issues$/.test(link.href) && /noopener/.test(link.rel) && link.target === "_blank");
  s.d.getElementById("betaClose").click();
  const after = stored(s.w);
  check("banner can be dismissed", !visible(banner) && after["sdt.betaDismissed"] === JSON.stringify(version));
  s.w.close();
  s = await boot({ storage: after });
  check("a dismissed banner stays hidden", !visible(s.d.getElementById("betaBanner")));
  s.w.close();
  s = await boot({ storage: prefs("ru") });
  check("banner text follows the language", /бета-версия/.test(s.d.getElementById("betaBanner").textContent));
  s.w.close();
}

(async () => {
  await sectionsWalk();
  await secrets();
  await languageFlow();
  await betaBanner();
  const errors = allErrors.flat();
  check("no script errors in any run", errors.length === 0, errors.slice(0, 2).join(" | "));
  for (const r of results) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.detail ? "  -> " + r.detail : ""}`);
  const failed = results.filter((r) => !r.ok).length;
  console.log(failed ? `\n${failed} of ${results.length} FAILED` : `\nall ${results.length} checks passed (${path.basename(file)})`);
  process.exit(failed ? 1 : 0);
})();

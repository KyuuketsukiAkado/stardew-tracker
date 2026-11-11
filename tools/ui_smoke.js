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
// the secrets section works after consent; the permission screen to look for saves and the Folders dialog;
// errors in the interface language; first-run language chooser, "remember my
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


// ---------------------------------------------------------------------------------------------
// Live mode with a fake server: the permission screen, the "Folders" dialog and error language.
// The raw template (placeholders intact) is a live page without a save; the state comes from the demo.
// ---------------------------------------------------------------------------------------------
const TEMPLATE = fs.readFileSync(path.join(__dirname, "..", "assets", "dashboard.html"), "utf8");
const DEMO = fs.readFileSync(path.join(__dirname, "..", "docs", "index.html"), "utf8");
const DEMO_STATE = (() => {
  const marker = "window.__STATE__ = ";
  const start = DEMO.indexOf(marker) + marker.length;
  return JSON.parse(DEMO.slice(start, DEMO.indexOf(";\n", start)));
})();

function fakeBackend({ allowed = false, error = null } = {}) {
  const b = { allowed, extra: [], folders: ["C:/Games/Stardew/Saves", "C:/App/saves"], calls: [], posted: [], error };
  const consentError = () => ({
    kind: "consent_required",
    title: "console language title",
    detail: "console language detail",
    steps: [],
    data: { folders: b.folders },
    i18n: { en: { title: "Allow?", detail: "d", steps: [] }, ru: { title: "Разрешить?", detail: "д", steps: [] } },
  });
  const reply = (status, body) => ({ ok: status < 400, status, json: async () => body });
  b.fetch = async (url, options = {}) => {
    const route = String(url);
    b.calls.push(route);
    const method = (options.method || "GET").toUpperCase();
    const hasState = b.allowed || b.extra.length > 0;
    if (route === "/api/refresh" || route === "/api/state") {
      if (b.error) return reply(route === "/api/refresh" ? 500 : 404, { error: b.error });
      return hasState ? reply(200, DEMO_STATE) : reply(route === "/api/refresh" ? 500 : 404, { error: consentError() });
    }
    if (route === "/api/version") return reply(200, { rev: "r" + b.posted.length, ready: hasState });
    if (route === "/api/saves") {
      const m = DEMO_STATE.meta;
      return reply(200, { saves: hasState ? [{ path: m.save_path, farm: m.farm, farmer: m.farmer, season: m.season, day: m.day, year: m.year }] : [], active: hasState ? m.save_path : "" });
    }
    if (route === "/api/consent" && method === "GET")
      return reply(200, { standard: b.folders, standard_allowed: b.allowed, by_environment: false, extra: b.extra });
    if (route === "/api/consent" && method === "POST") {
      const body = JSON.parse(options.body);
      b.posted.push(body);
      if (body.folder !== undefined) {
        if (!body.folder.startsWith("D:/")) return reply(400, { error: "Not a folder: " + body.folder });
        b.extra.push(body.folder);
      }
      if (body.allow !== undefined) b.allowed = !!body.allow;
      if (body.forget) { b.allowed = false; b.extra = []; }
      return reply(200, { ok: true, consent: { standard: b.folders, standard_allowed: b.allowed, by_environment: false, extra: b.extra } });
    }
    return reply(404, { error: "not found" });
  };
  return b;
}

async function bootLive(backend, storage = prefs("en")) {
  const errors = [];
  allErrors.push(errors);
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => errors.push(String(e.message).slice(0, 200)));
  const dom = new JSDOM(TEMPLATE, {
    runScripts: "dangerously",
    url: "http://localhost:8777/",
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(w) {
      w.scrollTo = () => {};
      w.HTMLElement.prototype.scrollIntoView = () => {};
      w.fetch = backend.fetch;
      for (const [key, value] of Object.entries(storage)) w.localStorage.setItem(key, value);
    },
  });
  await sleep(500);
  return { w: dom.window, d: dom.window.document };
}

async function consentFlow() {
  let backend = fakeBackend();
  let s = await bootLive(backend);
  let view = s.d.getElementById("view");
  check("permission: the screen asks before anything is read", /May Stardew Tracker look for your saves\?/.test(view.textContent));
  const listed = [...view.querySelectorAll(".folder-list code")].map((c) => c.textContent);
  check("permission: it lists exactly the folders it would look in", listed.join("|") === backend.folders.join("|"), listed.join("|"));
  check("permission: Allow and Use-another-folder are offered", !!s.d.getElementById("consentAllow") && !!s.d.getElementById("consentOther"));
  check("permission: no save list is requested before the answer", !backend.calls.includes("/api/saves") && backend.posted.length === 0);
  check("folders: settings remain available without a loaded save", !!s.d.getElementById("foldersBtn"));
  s.d.getElementById("consentLater").click();
  check("permission: Not now keeps the search off", /Save search is off/.test(s.d.getElementById("view").textContent) && backend.posted.length === 0);
  s.d.getElementById("consentResume").click();
  check("permission: a declined choice can be reconsidered", !!s.d.getElementById("consentAllow"));

  s.d.getElementById("language").click();
  await sleep(150);
  check("permission: the screen follows the interface language (RU)", /Разрешить Stardew Tracker искать ваши сохранения\?/.test(s.d.getElementById("view").textContent));
  s.d.getElementById("language").click();
  await sleep(150);

  s.d.getElementById("consentOther").click();
  check("permission: another folder can be typed in", !s.d.getElementById("consentForm").classList.contains("hidden"));
  s.d.getElementById("consentPath").value = "Z:/nope";
  s.d.getElementById("consentForm").dispatchEvent(new s.w.Event("submit", { cancelable: true }));
  await sleep(200);
  check("permission: a wrong folder shows the server's message", /Not a folder: Z:\/nope/.test(s.d.getElementById("consentError").textContent));

  s.d.getElementById("consentAllow").click();
  await sleep(500);
  check("permission: Allow sends allow=true and the app opens", JSON.stringify(backend.posted.at(-1)) === '{"allow":true}' && /Hello/.test(s.d.getElementById("view").textContent));

  // the Folders dialog
  const folders = s.d.getElementById("foldersBtn");
  check("folders: the button is in the top bar", !!folders);
  folders.click();
  await sleep(300);
  const dialog = s.d.getElementById("foldersModal");
  check("folders: the dialog opens and shows the permission", visible(dialog) && /Allowed: the tracker looks for saves/.test(dialog.textContent));
  check("folders: it lists the standard folders", backend.folders.every((f) => dialog.textContent.includes(f)));
  s.d.dispatchEvent(new s.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  check("folders: Escape closes it", !visible(dialog));
  folders.click();
  await sleep(300);
  s.d.getElementById("foldersStop").click();
  await sleep(600);
  check("folders: withdrawing sends forget=true", JSON.stringify(backend.posted.at(-1)) === '{"forget":true}');
  check("folders: after withdrawing the app asks again", /May Stardew Tracker look for your saves\?/.test(s.d.getElementById("view").textContent));
  s.w.close();

  // a folder chosen by hand
  backend = fakeBackend();
  s = await bootLive(backend);
  s.d.getElementById("consentOther").click();
  s.d.getElementById("consentPath").value = "D:/Backups/StardewSaves";
  s.d.getElementById("consentForm").dispatchEvent(new s.w.Event("submit", { cancelable: true }));
  await sleep(500);
  check("permission: a folder of your own opens the app without the standard permission", backend.posted.at(-1).folder === "D:/Backups/StardewSaves" && backend.allowed === false && /Hello/.test(s.d.getElementById("view").textContent));
  s.w.close();
}

async function errorLanguage() {
  const error = { kind: "io_error", title: "console title", detail: "console detail", steps: ["console step"], i18n: { en: { title: "English title", detail: "English detail", steps: ["English step"] }, ru: { title: "Русский заголовок", detail: "Русские подробности", steps: ["Русский шаг"] } } };
  for (const [lang, expected] of [["en", "English title"], ["ru", "Русский заголовок"]]) {
    const backend = fakeBackend({ error });
    const s = await bootLive(backend, prefs(lang));
    const text = s.d.getElementById("view").textContent;
    check(`errors: shown in the interface language (${lang})`, text.includes(expected) && !text.includes("console title"), text.slice(0, 60));
    check(`errors: details and steps follow the language (${lang})`, lang === "en" ? /English detail/.test(text) && /English step/.test(text) : /Русские подробности/.test(text) && /Русский шаг/.test(text));
    s.w.close();
  }
  const backend = fakeBackend({ error: { kind: "x", title: "Only plain", detail: "plain detail", steps: [] } });
  const s = await bootLive(backend);
  check("errors: an error without translations still shows its own text", /Only plain/.test(s.d.getElementById("view").textContent));
  s.w.close();
}

(async () => {
  await sectionsWalk();
  await secrets();
  await languageFlow();
  await betaBanner();
  await consentFlow();
  await errorLanguage();
  const errors = allErrors.flat();
  check("no script errors in any run", errors.length === 0, errors.slice(0, 2).join(" | "));
  for (const r of results) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.detail ? "  -> " + r.detail : ""}`);
  const failed = results.filter((r) => !r.ok).length;
  console.log(failed ? `\n${failed} of ${results.length} FAILED` : `\nall ${results.length} checks passed (${path.basename(file)})`);
  process.exit(failed ? 1 : 0);
})();

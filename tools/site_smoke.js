#!/usr/bin/env node
// Optional browser-less check of the GitHub Pages landing page (site/index.template.html).
//
//   npm install --no-save jsdom                 # once, in the repository root
//   python tools/build_site.py --out _site      # build the page
//   node tools/site_smoke.js _site/index.html
//
// Also runs in CI with optional tools installed outside the app. It checks that the download
// button follows the visitor's system (Windows / macOS / Linux, phones preview the app),
// that the language follows the browser and can be switched, and that every download
// stays a plain link when JavaScript is off.

"use strict";

const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const html = fs.readFileSync(process.argv[2] || "_site/index.html", "utf8");
const results = [];
const check = (name, ok, extra = "") => results.push(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? "  -> " + extra : ""}`);
const errors = [];

function open({ ua, platform, languages = ["en-US"], storage = {}, runScripts = "dangerously" }) {
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e.message).slice(0, 160)));
  return new JSDOM(html, {
    runScripts,
    url: "https://kyuuketsukiakado.github.io/stardew-tracker/",
    pretendToBeVisual: true,
    userAgent: ua,
    virtualConsole: vc,
    beforeParse(w) {
      Object.defineProperty(w.navigator, "platform", { value: platform, configurable: true });
      Object.defineProperty(w.navigator, "userAgent", { value: ua, configurable: true });
      Object.defineProperty(w.navigator, "languages", { value: languages, configurable: true });
      Object.defineProperty(w.navigator, "language", { value: languages[0], configurable: true });
      for (const [k, v] of Object.entries(storage)) w.localStorage.setItem(k, v);
    },
  }).window;
}
const btn = (w) => w.document.getElementById("download");
const visibleText = (w) => [...btn(w).querySelectorAll("span")].find((s) => w.getComputedStyle(s).display !== "none")?.textContent;

const UA = {
  win: ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36", "Win32"],
  mac: ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15", "MacIntel"],
  linux: ["Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36", "Linux x86_64"],
  iphone: ["Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148", "iPhone"],
  android: ["Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36", "Linux armv8l"],
  chromeos: ["Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 Chrome/126 Safari/537.36", "Linux x86_64"],
};

(async () => {
  for (const [name, expect] of [["win", "windows"], ["mac", "macos"], ["linux", "linux"], ["chromeos", "linux"]]) {
    const w = open({ ua: UA[name][0], platform: UA[name][1] });
    const href = btn(w).href;
    check(`${name}: button points at the ${expect} zip`, href.includes(`StardewTracker-${expect}-v`) && btn(w).dataset.os === expect, href.split("/").pop());
    check(`${name}: label names the system`, new RegExp(expect === "macos" ? "macOS" : expect, "i").test(btn(w).textContent));
    if (name === "mac") {
      check("mac: Apple Silicon limitation and source fallback are visible", w.document.documentElement.classList.contains("is-macos") && w.getComputedStyle(w.document.querySelector(".mac-note")).display !== "none" && /Intel Macs/.test(w.document.querySelector(".mac-note").textContent));
      check("mac: Russian fallback points to Russian instructions", w.document.querySelector('.mac-note [lang="ru"] a').href.includes("README.ru.md#"));
    }
    w.close();
  }
  for (const name of ["iphone", "android"]) {
    const w = open({ ua: UA[name][0], platform: UA[name][1] });
    check(`${name}: shows the "open on your PC" hint`, w.document.documentElement.classList.contains("is-mobile") && w.getComputedStyle(w.document.querySelector(".mobile-note")).display !== "none");
    check(`${name}: primary action previews the app instead of downloading Windows`, btn(w).getAttribute("href") === "#look" && /See the tracker/.test(btn(w).textContent) && !btn(w).hasAttribute("data-os") && !!w.document.getElementById("look"));
    check(`${name}: desktop downloads remain available`, [...w.document.querySelectorAll("#others a")].map((a) => a.dataset.os).join(",") === "windows,macos,linux");
    w.close();
  }
  let w = open({ ua: UA.win[0], platform: "Win32" });
  check("English by default", w.document.documentElement.lang === "en" && /Download for Windows/.test(visibleText(w)));
  w.document.getElementById("langToggle").click();
  check("toggle switches to Russian and remembers it", w.document.documentElement.lang === "ru" && /Скачать/.test(visibleText(w)) && w.localStorage.getItem("lang") === "ru");
  const stored = { lang: w.localStorage.getItem("lang") };
  w.close();
  w = open({ ua: UA.win[0], platform: "Win32", languages: ["en-US"], storage: stored });
  check("stored language wins over the browser language", w.document.documentElement.lang === "ru");
  w.close();
  w = open({ ua: UA.win[0], platform: "Win32", languages: ["ru-RU", "ru"] });
  check("Russian browser gets Russian first", w.document.documentElement.lang === "ru");
  w.close();
  w = open({ ua: UA.win[0], platform: "Win32", languages: ["de-DE"] });
  check("other languages fall back to English", w.document.documentElement.lang === "en");
  w.close();

  // without JavaScript: all three downloads are plain links
  w = open({ ua: UA.win[0], platform: "Win32", runScripts: "outside-only" });
  const links = [...w.document.querySelectorAll("#others a")].map((a) => a.dataset.os);
  check("without JavaScript all three systems stay downloadable", links.join(",") === "windows,macos,linux" && /releases\/download\//.test(btn(w).href));
  w.close();

  check("no script errors", errors.length === 0, errors.slice(0, 2).join(" | "));
  console.log(results.join("\n"));
  const failed = results.filter((r) => r.startsWith("FAIL")).length;
  console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();

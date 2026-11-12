#!/usr/bin/env node
// Real-Chrome layout and interaction check for the generated GitHub Pages site.
// Uses only the fictional farm screenshots. No browser downloads or app dependencies.
// node tools/site_visual_smoke.js [path/to/site/index.html]
"use strict";

const path = require("path");
const { pathToFileURL } = require("url");
let chromium;
try {
  ({ chromium } = require("playwright-core"));
} catch (_) {
  console.error("Install optional playwright-core to run this check");
  process.exit(2);
}

const site = pathToFileURL(path.resolve(process.argv[2] || "_site/index.html")).href;
const cases = [
  { width: 320, lang: "ru", mobile: true },
  { width: 390, lang: "en", mobile: true },
  { width: 390, lang: "ru", mobile: true },
  { width: 768, lang: "en", mobile: false },
  { width: 1440, lang: "en", mobile: false },
  { width: 1440, lang: "ru", mobile: false },
];
const phoneUA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148";

(async () => {
  const browser = await chromium.launch({
    ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: "chrome" }),
    headless: true,
  });
  const failures = [];
  try {
    for (const { width, lang, mobile } of cases) {
      const context = await browser.newContext({
        viewport: { width, height: 900 },
        ...(mobile ? { userAgent: phoneUA, isMobile: true } : {}),
      });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.addInitScript((lang) => localStorage.setItem("lang", lang), lang);
      try {
        await page.goto(site);
        const picture = page.locator(`.proof picture[lang="${lang}"] img`).first();
        await picture.scrollIntoViewIfNeeded();
        await picture.evaluate((img) => img.decode());
        const result = await page.evaluate(() => {
          const image = document.querySelector(`.proof picture[lang="${document.documentElement.lang}"] img`);
          const proof = document.querySelector(".proof");
          const cta = document.querySelector("#download");
          return {
            overflow: document.documentElement.scrollWidth - innerWidth,
            proofTop: proof.getBoundingClientRect().top + scrollY,
            imageWidth: image.naturalWidth,
            imageLoaded: image.complete,
            primary: cta.getAttribute("href"),
            language: document.documentElement.lang,
            mobile: document.documentElement.classList.contains("is-mobile"),
            artHidden: getComputedStyle(document.querySelector(".hero-art")).display === "none",
            headerAlignment: Math.abs(document.querySelector(".brand").getBoundingClientRect().top - document.querySelector("#langToggle").getBoundingClientRect().top),
          };
        });
        if (result.overflow > 1) failures.push(`${width}/${lang}: ${result.overflow}px horizontal overflow`);
        if (result.language !== lang || !result.imageLoaded || result.imageWidth !== (mobile ? 390 : 1440)) {
          failures.push(`${width}/${lang}: wrong language or screenshot ${JSON.stringify(result)}`);
        }
        if (mobile && (result.primary !== "#look" || !result.mobile || !result.artHidden || result.proofTop > 900 || result.headerAlignment > 15)) {
          failures.push(`${width}/${lang}: phone did not lead to a nearby app preview ${JSON.stringify(result)}`);
        }
        if (!mobile && (!result.primary.includes("StardewTracker-windows-v") || result.artHidden)) {
          failures.push(`${width}/${lang}: desktop download or illustration missing`);
        }
        if (mobile) {
          await page.locator("#download").click();
          if (!(await page.evaluate(() => location.hash === "#look"))) failures.push(`${width}/${lang}: preview CTA missed the screenshots`);
        }
        const summary = page.locator("details.note summary");
        await summary.focus();
        await page.keyboard.press("Enter");
        if (!(await page.locator("details.note").evaluate((details) => details.open))) failures.push(`${width}/${lang}: safety disclosure failed`);
        if (errors.length) failures.push(`${width}/${lang}: ${errors.join("; ")}`);
        console.log(`${failures.length ? "CHECK" : "PASS"} ${width}/${lang}: screenshot at ${Math.round(result.proofTop)}px, image ${result.imageWidth}px`);
      } finally {
        await context.close();
      }
    }
    // Macs report MacIntel even on Apple Silicon. The site must explicitly warn about Intel support.
    const mac = await browser.newContext({ viewport: { width: 1440, height: 900 }, userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15" });
    const page = await mac.newPage();
    await page.addInitScript(() => Object.defineProperty(navigator, "platform", { value: "MacIntel" }));
    await page.goto(site);
    const macResult = await page.evaluate(() => ({ download: document.querySelector("#download").href, warning: getComputedStyle(document.querySelector(".mac-note")).display, text: document.querySelector(".mac-note").textContent }));
    if (!macResult.download.includes("StardewTracker-macos-v") || macResult.warning === "none" || !macResult.text.includes("Intel Macs")) failures.push(`mac: missing architecture warning ${JSON.stringify(macResult)}`);
    await mac.close();
  } finally {
    await browser.close();
  }
  if (failures.length) {
    for (const failure of failures) console.error("FAIL", failure);
    process.exitCode = 1;
  } else console.log("PASS site layouts, language screenshots, mobile preview, download paths, and safety disclosure");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

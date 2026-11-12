#!/usr/bin/env node
// Optional real-browser layout regression check for the synthetic demo (never reads user saves).
// npm install --no-save playwright-core
// node tools/visual_smoke.js              # Chrome stable must be installed
// CHROME_PATH=/path/to/chrome node tools/visual_smoke.js
// Nothing is downloaded by this script or required by the app/CI.

"use strict";

const path = require("path");
const { pathToFileURL } = require("url");
let chromium;
try {
  ({ chromium } = require("playwright-core"));
} catch (_) {
  console.error("Install the optional browser test dependency: npm install --no-save playwright-core");
  process.exit(2);
}

const demo = pathToFileURL(path.join(__dirname, "..", "docs", "index.html")).href;
function collectionTargets() {
  let tooSmall = 0;
  let split = 0;
  let outside = 0;
  const groups = document.querySelectorAll("#view .collection-controls");
  for (const group of groups) {
    const card = group.closest(".row, .grid-item").getBoundingClientRect();
    const controls = group.querySelectorAll("[data-mark], [data-note], .acq-tip > summary");
    const top = controls[0].getBoundingClientRect().top;
    for (const control of controls) {
      const rect = control.getBoundingClientRect();
      if (rect.width < 40 || rect.height < 40) tooSmall++;
      if (Math.abs(rect.top - top) > 1) split++;
      if (rect.left < card.left - 1 || rect.right > card.right + 1) outside++;
    }
  }
  return { groups: groups.length, tooSmall, split, outside };
}
function bundleTargets() {
  const toggles = [...document.querySelectorAll("#view .bundle-item-trigger")];
  const headers = [...document.querySelectorAll("#view .bundle-tooltip > summary")];
  const actions = [...document.querySelectorAll("#view .bundle-item-actions:not([hidden]) button, #view .bundle-item-actions:not([hidden]) summary")];
  const tooSmall = [...headers, ...actions].filter((el) => {
    const rect = el.getBoundingClientRect();
    return rect.width < 40 || rect.height < 40;
  }).length;
  const shortToggle = toggles.filter((el) => el.getBoundingClientRect().height < 40).length;
  const outside = actions.filter((el) => {
    const card = el.closest(".bundle-item").getBoundingClientRect();
    const rect = el.getBoundingClientRect();
    return rect.left < card.left - 1 || rect.right > card.right + 1;
  }).length;
  return { toggles: toggles.length, headers: headers.length, actions: actions.length, tooSmall, shortToggle, outside };
}
const cases = [
  ["ru", "dark", 320],
  ["ru", "light", 390],
  ["en", "dark", 768],
  ["en", "light", 900],
  ["ru", "dark", 1440],
  ["en", "light", 2000],
];

(async () => {
  const browser = await chromium.launch({
    ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: "chrome" }),
    headless: true,
  });
  const failures = [];
  let routesChecked = 0;
  let smallControls = 0;
  try {
    for (const [lang, theme, width] of cases) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.addInitScript(
        ({ lang, theme }) => {
          localStorage.setItem("sdt.lang", JSON.stringify(lang));
          localStorage.setItem("sdt.theme", JSON.stringify(theme));
        },
        { lang, theme },
      );
      try {
        const failuresBefore = failures.length;
        await page.goto(demo);
        if (await page.locator("#langModal:not(.hidden)").count()) {
          await page.locator(`[data-lang="${lang}"]`).first().click();
        }
        const routes = await page.locator("#mobileNav option").evaluateAll((options) => options.map((option) => option.value));
        for (const route of routes) {
          await page.evaluate((next) => { location.hash = next; }, route);
          await page.waitForTimeout(40);
          const result = await page.evaluate(() => {
            const overflow = Math.max(0, document.documentElement.scrollWidth - innerWidth);
            const controls = [...document.querySelectorAll("#view button, #view summary, #view a[href]")];
            const small = controls.filter((el) => {
              const rect = el.getBoundingClientRect();
              return rect.width > 0 && rect.height > 0 && (rect.width < 32 || rect.height < 32);
            }).length;
            // Each item icon must show its own sprite cell at its rendered size
            // (on phones icons once shrank while sprite offsets did not).
            let wrongIcons = 0;
            for (const el of document.querySelectorAll("#view .item-icon")) {
              const cs = getComputedStyle(el);
              const w = parseFloat(cs.width);
              const cell = /--ix:(\d+);--iy:(\d+)/.exec(el.getAttribute("style") || "");
              if (!w || !cell) continue;
              const tall = el.classList.contains("sheet2") ? 2 : 1;
              const cols = el.classList.contains("sheet1") || tall === 2 ? 8 : 24;
              const [sx] = cs.backgroundSize.split(" ").map(parseFloat);
              const [px, py] = cs.backgroundPosition.split(" ").map(parseFloat);
              const off = (a, b) => Math.abs(a - b) > 0.6;
              if (off(sx, cols * w) || off(px, -cell[1] * w) || off(py, -cell[2] * w * tall) || off(parseFloat(cs.height), w * tall)) wrongIcons++;
            }
            const smallUnlocks = [...document.querySelectorAll("#view .unlock-item summary")].filter((el) => {
              const rect = el.getBoundingClientRect();
              return rect.width < 40 || rect.height < 40;
            }).length;
            const overflowElements = overflow > 1 ? [...document.querySelectorAll("body *")]
              .filter((el) => {
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.right > innerWidth + 1 && rect.left < innerWidth;
              })
              .slice(0, 8)
              .map((el) => ({ element: el.tagName.toLowerCase(), className: String(el.className).slice(0, 80), right: Math.round(el.getBoundingClientRect().right), text: (el.textContent || "").trim().slice(0, 45) })) : [];
            return { overflow, small, wrongIcons, smallUnlocks, overflowElements };
          });
          routesChecked++;
          smallControls += result.small;
          if (result.overflow > 1) failures.push(`${lang}/${theme}/${width}/${route}: ${result.overflow}px horizontal overflow ${JSON.stringify(result.overflowElements)}`);
          if (result.wrongIcons) failures.push(`${lang}/${theme}/${width}/${route}: ${result.wrongIcons} icons show the wrong sprite cell`);
          if (result.smallUnlocks) failures.push(`${lang}/${theme}/${width}/${route}: ${result.smallUnlocks} undersized unlock tips`);
          const touch = await page.evaluate(collectionTargets);
          if (touch.tooSmall || touch.split || touch.outside) failures.push(`${lang}/${theme}/${width}/${route}: collection controls ${JSON.stringify(touch)}`);
          const bundle = await page.evaluate(bundleTargets);
          if (bundle.tooSmall || bundle.shortToggle || bundle.outside || (route === "bundles" && !bundle.toggles)) {
            failures.push(`${lang}/${theme}/${width}/${route}: bundle controls ${JSON.stringify(bundle)}`);
          }
        }
        await page.evaluate(() => { location.hash = "museum"; });
        await page.locator("#viewToggle").click();
        const gridTouch = await page.evaluate(collectionTargets);
        if (!gridTouch.groups || gridTouch.tooSmall || gridTouch.split || gridTouch.outside) {
          failures.push(`${lang}/${theme}/${width}/museum grid: collection controls ${JSON.stringify(gridTouch)}`);
        }
        const info = page.locator("#view .grid-item .collection-controls summary").first();
        await info.focus();
        await page.keyboard.press("Enter");
        if (!(await info.evaluate((el) => el.parentElement.open && el.matches(":focus-visible") && !!el.getAttribute("title") && !!el.getAttribute("aria-label")))) {
          failures.push(`${lang}/${theme}/${width}: keyboard info disclosure, focus ring, or labels failed`);
        }
        await page.keyboard.press("Enter");
        // The demo uses a synthetic farm and an isolated browser profile; no personal saves.
        const star = page.locator("#view .grid-item [data-mark]").first();
        const key = await star.getAttribute("data-mark");
        await star.focus();
        await page.keyboard.press("Space");
        if (!(await page.evaluate((key) => document.activeElement?.getAttribute("data-mark") === key && document.activeElement?.getAttribute("aria-pressed") === "true", key))) {
          failures.push(`${lang}/${theme}/${width}: keyboard marking or focus restoration failed`);
        }
        const pencil = page.locator("#view .grid-item [data-note]").first();
        await pencil.focus();
        await page.keyboard.press("Enter");
        if (!(await page.evaluate(() => document.activeElement?.id === "noteText" && !document.querySelector("#noteModal").classList.contains("hidden")))) {
          failures.push(`${lang}/${theme}/${width}: keyboard note dialog failed`);
        }
        await page.keyboard.press("Escape");
        if (!(await page.evaluate((key) => document.querySelector("#noteModal").classList.contains("hidden") && document.activeElement?.getAttribute("data-note") === key, key))) {
          failures.push(`${lang}/${theme}/${width}: Escape did not restore note focus`);
        }
        await page.keyboard.press("Enter");
        await page.locator("#noteText").fill("Synthetic test note");
        await page.locator("#noteSave").click();
        await page.evaluate(() => { location.hash = "saved"; });
        await page.locator("#view .collection-controls").first().waitFor();
        const savedTouch = await page.evaluate(collectionTargets);
        if (!savedTouch.groups || savedTouch.tooSmall || savedTouch.split || savedTouch.outside || !(await page.locator("#view .note-preview").count())) {
          failures.push(`${lang}/${theme}/${width}/saved: controls or note missing ${JSON.stringify(savedTouch)}`);
        }
        await page.evaluate(() => { location.hash = "bundles"; });
        const bundleToggle = page.locator("#view .bundle-item-trigger").first();
        await bundleToggle.focus();
        await page.keyboard.press("Enter");
        const opened = await page.evaluate(bundleTargets);
        if (opened.actions !== 3 || opened.tooSmall || opened.outside || !(await bundleToggle.getAttribute("aria-expanded") === "true")) {
          failures.push(`${lang}/${theme}/${width}/bundles: expanded controls ${JSON.stringify(opened)}`);
        }
        await page.keyboard.press("Tab");
        if (!(await page.evaluate(() => document.activeElement?.matches(".bundle-item.expanded [data-mark]")))) {
          failures.push(`${lang}/${theme}/${width}/bundles: Tab did not enter the expanded controls`);
        }
        await page.keyboard.press("Space");
        if (!(await page.evaluate(() => document.activeElement?.matches(".bundle-item.expanded [data-mark][aria-pressed='true']")))) {
          failures.push(`${lang}/${theme}/${width}/bundles: marking lost expansion or focus`);
        }
        await page.keyboard.press("Tab");
        await page.keyboard.press("Enter");
        if (!(await page.evaluate(() => document.activeElement?.id === "noteText"))) {
          failures.push(`${lang}/${theme}/${width}/bundles: keyboard note dialog did not open`);
        }
        await page.keyboard.press("Escape");
        if (!(await page.evaluate(() => document.activeElement?.matches(".bundle-item.expanded [data-note]")))) {
          failures.push(`${lang}/${theme}/${width}/bundles: note Escape did not restore focus`);
        }
        await page.keyboard.press("Enter");
        await page.locator("#noteText").fill("Synthetic bundle note");
        await page.locator("#noteSave").click();
        const bundleInfo = page.locator("#view .bundle-item.expanded .acq-tip summary").first();
        await bundleInfo.focus();
        await page.keyboard.press("Enter");
        if (!(await bundleInfo.evaluate((el) => el.parentElement.open && el.matches(":focus-visible")))) {
          failures.push(`${lang}/${theme}/${width}/bundles: info disclosure or focus ring failed`);
        }
        await page.waitForFunction(() => {
          const popup = document.querySelector("#view .bundle-item.expanded .acq-tip[open] .tip-pop"),
            rect = popup?.getBoundingClientRect();
          return rect && rect.left >= 7 && rect.right <= innerWidth - 7;
        });
        await page.keyboard.press("Escape");
        if (!(await page.evaluate(() => document.activeElement?.matches(".bundle-item-trigger[aria-expanded='false']")))) {
          failures.push(`${lang}/${theme}/${width}/bundles: Escape did not close expansion and restore focus`);
        }
        // Two Wood requirements share the same annotation key; their disclosure controls must not share state.
        const duplicateTriggers = page.locator("#bundle-17 .bundle-item:has([data-mark='bundle:17:388']) .bundle-item-trigger");
        if ((await duplicateTriggers.count()) !== 2) {
          failures.push(`${lang}/${theme}/${width}/bundles: duplicate Wood test items missing`);
        } else {
          const labels = await duplicateTriggers.evaluateAll((controls) => controls.map((control) => control.getAttribute("aria-label")));
          if (labels[0] === labels[1]) failures.push(`${lang}/${theme}/${width}/bundles: duplicate items have the same accessible name`);
          const second = duplicateTriggers.nth(1), secondKey = await second.getAttribute("data-bundle-item");
          await second.focus();
          await page.keyboard.press("Enter");
          const expandedDuplicates = await page.locator("#bundle-17 .bundle-item:has([data-mark='bundle:17:388']) .bundle-item-trigger[aria-expanded='true']").count();
          const secondFocused = await page.evaluate((key) => document.activeElement?.getAttribute("data-bundle-item") === key, secondKey);
          if (expandedDuplicates !== 1 || !secondFocused) failures.push(`${lang}/${theme}/${width}/bundles: duplicate items opened or focused together`);
          await page.keyboard.press("Tab");
          await page.keyboard.press("Space");
          if (!(await page.evaluate((key) => document.activeElement?.closest(".bundle-item")?.querySelector(".bundle-item-trigger")?.getAttribute("data-bundle-item") === key && document.activeElement?.getAttribute("aria-pressed") === "true", secondKey))) {
            failures.push(`${lang}/${theme}/${width}/bundles: marking second duplicate lost focus`);
          }
          await page.keyboard.press("Tab");
          await page.keyboard.press("Enter");
          await page.locator("#noteText").fill("Synthetic duplicate note");
          await page.locator("#noteSave").click();
          if (!(await page.evaluate((key) => document.activeElement?.closest(".bundle-item")?.querySelector(".bundle-item-trigger")?.getAttribute("data-bundle-item") === key && document.activeElement?.hasAttribute("data-note"), secondKey))) {
            failures.push(`${lang}/${theme}/${width}/bundles: saving second duplicate note lost focus`);
          }
          await page.keyboard.press("Escape");
          if (!(await page.evaluate((key) => document.activeElement?.getAttribute("data-bundle-item") === key && document.activeElement?.getAttribute("aria-expanded") === "false", secondKey))) {
            failures.push(`${lang}/${theme}/${width}/bundles: duplicate item Escape lost focus`);
          }
        }
        const secondTile = page.locator("#view .bundle-room .bundle-item-trigger").nth(1);
        await secondTile.focus();
        await page.keyboard.press("Enter");
        await page.locator("#view .bundle-item.expanded .acq-tip summary").first().focus();
        await page.keyboard.press("Enter");
        await page.waitForFunction(() => {
          const popup = document.querySelector("#view .bundle-item.expanded .acq-tip[open] .tip-pop"),
            rect = popup?.getBoundingClientRect();
          return rect && rect.left >= 7 && rect.right <= innerWidth - 7;
        });
        await page.keyboard.press("Escape");
        await page.evaluate(() => { location.hash = "saved"; });
        await page.locator("#view [data-mark^='bundle:']").first().waitFor();
        if (!(await page.locator("#view .note-preview").allTextContents()).some((note) => note.includes("Synthetic bundle note"))) {
          failures.push(`${lang}/${theme}/${width}: bundle note was lost from Saved items`);
        }
        // Home and Today must still deep-link to their bundle room / individual bundle.
        for (const [route, selector] of [["overview", ".overview-bundle-link"], ["today", ".today-bundle-link"]]) {
          await page.evaluate((route) => { location.hash = route; }, route);
          const link = page.locator(`#view ${selector}`).first();
          await link.waitFor();
          const href = await link.getAttribute("href");
          await link.click();
          await page.waitForFunction((href) => {
            const id = href.split("/").at(-1);
            return location.hash === href && document.activeElement?.id === id;
          }, href);
        }
        // Reproduce the reported values without opening a real save; test the visible text geometry.
        await page.evaluate(() => {
          location.hash = "overview";
          S.perfection.pct = 44.7;
          S.counts.museum = [93, 95];
          S.counts.fish = [59, 72];
          render();
        });
        const metrics = await page.locator("#view .big").evaluateAll((elements) => elements.map((el) => {
          const number = el.querySelector(".big-value");
          const unit = el.querySelector(".big-unit");
          if (!number || !unit) return { text: el.textContent, gap: -1, style: "missing spans" };
          return {
            text: el.textContent,
            gap: unit.getBoundingClientRect().left - number.getBoundingClientRect().right,
            style: getComputedStyle(number).fontStyle,
          };
        }));
        for (const metric of metrics) {
          if (metric.gap < 10 || metric.style !== "normal") {
            failures.push(`${lang}/${theme}/${width}: ${metric.text}: gap ${metric.gap}px, style ${metric.style}`);
          }
        }
        if (errors.length) failures.push(`${lang}/${theme}/${width}: ${errors.join("; ")}`);
        console.log(`${failures.length > failuresBefore ? "FAIL" : "PASS"} ${lang}/${theme}/${width}: ${routes.length} routes, ${metrics.length} metrics`);
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  console.log(`Checked ${routesChecked} route renders. Counted ${smallControls} undersized controls across repeated cases (not unique controls; known UX follow-up in docs/UX-AUDIT.md).`);
  if (failures.length) {
    for (const failure of failures) console.error("FAIL", failure);
    process.exitCode = 1;
  } else {
    console.log("PASS no horizontal overflow, JS errors, metric collisions, or misaligned item sprites in the tested scenarios");
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

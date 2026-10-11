// One-off diagnostics: Church Center popup behaviour and Radiant's site fonts.
import { chromium } from "playwright";

console.log("##### 1. Church Center modal script");
const modal = await (await fetch("https://js.churchcenter.com/modal/v1")).text();
console.log("length:", modal.length);
for (const needle of ["data-open-in-church-center-modal", "addEventListener", "DOMContentLoaded", "readyState",
                      "querySelectorAll", "iframe", "postMessage", "churchcenter.com", "MutationObserver", "click"]) {
  let i = -1, n = 0;
  while ((i = modal.indexOf(needle, i + 1)) !== -1 && n < 3) {
    console.log(`[${needle}] …${modal.slice(Math.max(0, i - 160), i + 200).replace(/\s+/g, " ")}…`);
    n++;
  }
}

console.log("\n##### 2. Can Church Center pages be framed?");
for (const u of ["https://radiantcentralcoast.churchcenter.com/registrations/events/3919181",
                 "https://radiantcentralcoast.churchcenter.com/calendar/event/200190659"]) {
  const r = await fetch(u, { redirect: "manual" });
  console.log(u, "->", r.status, "| x-frame-options:", r.headers.get("x-frame-options"),
              "| csp:", (r.headers.get("content-security-policy") || "").match(/frame-ancestors[^;]*/)?.[0]);
}

const browser = await chromium.launch();

console.log("\n##### 3. Clicking Register / Details on the preview page");
for (const which of ["Register", "Details"]) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto("https://legacyco.github.io/radiant-events/preview.html", { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);
  const modalLoaded = await page.evaluate(() => [...document.scripts].some((s) => s.src.includes("js.churchcenter.com")));
  const link = page.locator(`.cc-event__btn:text-is("${which}")`).first();
  const href = await link.getAttribute("href").catch(() => null);
  const attr = await link.getAttribute("data-open-in-church-center-modal").catch(() => null);
  const popupPromise = page.context().waitForEvent("page", { timeout: 4000 }).catch(() => null);
  await link.click().catch((e) => errors.push("click: " + e.message));
  const popup = await popupPromise;
  await page.waitForTimeout(3000);
  const frames = await page.$$eval("iframe", (fs) => fs.map((f) => (f.src || "").slice(0, 120) + ` [${f.offsetWidth}x${f.offsetHeight}]`));
  console.log(`${which}: href=${href} modalAttr=${attr} modalScriptLoaded=${modalLoaded}`);
  console.log(`   after click -> url=${page.url()} newTab=${popup ? popup.url() : "none"} iframes=${JSON.stringify(frames)}`);
  console.log("   errors:", JSON.stringify(errors.slice(0, 6)));
  await page.close();
}

console.log("\n##### 4. Radiant site fonts (radiantcentralcoast.com/events)");
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto("https://radiantcentralcoast.com/events", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
const fonts = await page.evaluate(() => {
  const root = getComputedStyle(document.documentElement);
  const vars = {};
  for (const sheet of [...document.styleSheets]) {
    let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const r of rules || []) {
      if (!r.style) continue;
      for (const p of r.style) if (p.startsWith("--") && /font|letter|line-height|text-transform/.test(p)) vars[p] = root.getPropertyValue(p).trim();
    }
  }
  const pick = (sel) => { const el = document.querySelector(sel); if (!el) return null;
    const s = getComputedStyle(el); return `${s.fontFamily} | ${s.fontWeight} | ${s.fontSize} | ls ${s.letterSpacing} | ${s.textTransform}`; };
  return {
    vars: Object.fromEntries(Object.entries(vars).filter(([k, v]) => v).slice(0, 60)),
    body: pick("body"), p: pick(".sqs-html-content p"), h1: pick("h1"), h2: pick("h2"), h3: pick("h3"), h4: pick("h4"),
    button: pick(".sqs-button-element--primary, .sqs-block-button-element"), nav: pick(".header-nav-item a"),
    small: pick(".sqsrte-small"), embedTab: pick(".cc-events__tab"),
    fontFaces: [...document.fonts].map((f) => f.family).filter((v, i, a) => a.indexOf(v) === i),
  };
});
console.log(JSON.stringify(fonts, null, 1));
await browser.close();

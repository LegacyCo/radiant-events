// Renders the live preview page and reports what the embeds show. Text only, no screenshots.
import { chromium } from "playwright";
const url = process.argv[2] || "https://legacyco.github.io/radiant-events/preview.html";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForSelector(".cc-event__line", { timeout: 30000 });
const facts = await page.evaluate(() => ({
  embeds: document.querySelectorAll(".cc-events[data-cc-ready]").length,
  cards: document.querySelectorAll(".cc-event, .cc-carousel__item, .cc-slider__item:not([aria-hidden])").length,
  pillLines: document.querySelectorAll(".cc-event__line").length,
  detailsPills: document.querySelectorAll(".cc-pill--solid").length,
  calendarPills: document.querySelectorAll(".cc-event__line .cc-cal").length,
  windowLinks: document.querySelectorAll("a[data-cc-window]").length,
  descriptions: document.querySelectorAll(".cc-event__summary, .cc-carousel__excerpt, .cc-carousel__more").length,
  locations: document.querySelectorAll(".cc-event__meta").length,
  registerLinks: [...document.querySelectorAll("a")].filter((a) => /^(Register|Inscribirse)/.test(a.textContent.trim())).length,
  firstCards: [...document.querySelectorAll(".cc-event, .cc-carousel__item, .cc-slider__item:not([aria-hidden])")].slice(0, 4).map((c) => c.innerText.replace(/\s*\n\s*/g, " | ")),
}));
console.log(JSON.stringify(facts, null, 2));
const slider = await page.evaluate(() => {
  const r = document.querySelector(".cc-events--slider");
  if (!r) return null;
  const vis = () => [...r.querySelectorAll(".cc-slider__item")].filter((i) => !i.inert).map((i) => i.querySelector("h3").textContent);
  return { left: Math.round(r.getBoundingClientRect().left), width: Math.round(r.getBoundingClientRect().width), page: document.documentElement.clientWidth,
    hScroll: document.documentElement.scrollWidth > innerWidth, visible: vis() };
});
console.log("slider:", JSON.stringify(slider));
if (slider) {
  for (let k = 0; k < 10; k++) { await page.click(".cc-slider__arrow--next"); await page.waitForTimeout(700); }
  console.log("slider after 10 next:", JSON.stringify(await page.evaluate(() => [...document.querySelectorAll(".cc-slider__item")].filter((i) => !i.inert).map((i) => i.querySelector("h3").textContent))));
}
const pill = page.locator(".cc-events--editorial .cc-pill--solid").first();
const href = await pill.getAttribute("href");
const [win] = await Promise.all([ctx.waitForEvent("page", { timeout: 10000 }).catch(() => null), pill.click()]);
console.log("Details click:", win ? `separate window ${await win.evaluate(() => outerWidth + "x" + outerHeight).catch(() => "?")} -> ${href}` : "no window");
console.log("page stayed put:", page.url() === url);
console.log("errors:", errors);
await browser.close();

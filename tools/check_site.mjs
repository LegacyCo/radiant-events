// One-off: render a page in Chromium and report what each events embed shows.
import { chromium } from "playwright";
const browser = await chromium.launch();
for (const url of process.argv.slice(2)) {
  for (const width of [1280, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("requestfailed", (r) => errors.push("failed: " + r.url().slice(0, 100)));
    await page.goto(url, { waitUntil: "networkidle", timeout: 45000 });
    await page.waitForTimeout(3000);
    const info = await page.$$eval(".cc-events", (roots) => roots.map((r) => ({
      ready: r.hasAttribute("data-cc-ready"),
      cards: r.querySelectorAll(".cc-event").length,
      first: [...r.querySelectorAll(".cc-event")].slice(0, 3).map((c) => [
        c.querySelector(".cc-event__date")?.textContent,
        c.querySelector(".cc-event__title")?.textContent,
        c.querySelector(".cc-event__meta")?.textContent,
        [...c.querySelectorAll(".cc-event__btn")].map((b) => b.textContent).join("+"),
        c.querySelector(".cc-event__img") ? "img" : "",
      ].join(" | ")),
      msg: r.querySelector(".cc-events__msg")?.textContent || "",
    })));
    const hscroll = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    console.log(`\n===== ${url} @${width}px  hscroll=${hscroll}`);
    info.forEach((x, i) => console.log(`embed ${i + 1}: ready=${x.ready} cards=${x.cards} ${x.msg}\n   ` + x.first.join("\n   ")));
    console.log("errors:", JSON.stringify(errors.filter((e) => !/google|churchcenter\.com\/modal/.test(e)).slice(0, 10)));
    await page.close();
  }
}
await browser.close();

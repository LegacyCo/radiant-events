// One-off: load live Radiant pages in Chromium and report what the events embed does.
import { chromium } from "playwright";

const urls = process.argv.slice(2);
const browser = await chromium.launch();
for (const url of urls) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  const failed = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(m.type() + ": " + m.text()); });
  page.on("requestfailed", (r) => failed.push(r.url().slice(0, 120) + " " + (r.failure() || {}).errorText));
  console.log(`\n===== ${url}`);
  let resp;
  try {
    resp = await page.goto(url, { waitUntil: "networkidle", timeout: 45000 });
  } catch (e) {
    console.log("load error:", e.message);
  }
  console.log("status:", resp && resp.status(), "| final url:", page.url(), "| title:", await page.title());
  const html = await page.content();
  console.log("password page?", /sqs-slide-container|password/i.test(html) && /locked|password/i.test(await page.title() + html.slice(0, 5000)));
  console.log("raw 'cc-events' in served HTML:", resp ? (await resp.text()).split("cc-events").length - 1 : "n/a");
  await page.waitForTimeout(4000);
  const info = await page.evaluate(() => {
    const roots = [...document.querySelectorAll(".cc-events")];
    return {
      roots: roots.length,
      ready: roots.filter((r) => r.hasAttribute("data-cc-ready")).length,
      perRoot: roots.map((r) => ({
        tabs: [...r.querySelectorAll(".cc-events__tab")].map((t) => t.textContent),
        cards: r.querySelectorAll(".cc-event").length,
        msg: (r.querySelector(".cc-events__msg") || {}).textContent || "",
        visible: r.offsetHeight,
        parent: (r.closest("[class*=sqs-block]") || {}).className || "",
      })),
      codeBlocks: document.querySelectorAll(".sqs-block-code").length,
      scriptsWithCC: [...document.scripts].filter((s) => s.textContent.includes("cc-events")).length,
      ldjson: document.querySelectorAll('script[type="application/ld+json"]').length,
    };
  });
  console.log("embed:", JSON.stringify(info, null, 1));
  console.log("errors:", JSON.stringify(errors.slice(0, 15), null, 1));
  console.log("failed requests:", JSON.stringify(failed.filter((f) => !/google|facebook|analytics|doubleclick/.test(f)).slice(0, 15), null, 1));
  await page.close();
}
await browser.close();

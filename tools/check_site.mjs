// One-off: screenshot each embed section of a page (default: the live preview) with real data.
import { chromium } from "playwright";
import { mkdirSync } from "fs";
mkdirSync("shots", { recursive: true });
const url = process.argv[2] && process.argv[2] !== "unused" ? process.argv[2] : "https://legacyco.github.io/radiant-events/preview.html";
const browser = await chromium.launch();
for (const [label, width] of [["desktop", 1440], ["mobile", 390]]) {
  const page = await browser.newPage({ viewport: { width, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url, { waitUntil: "networkidle" });
  await page.waitForTimeout(3000);
  const sections = page.locator("section");
  const n = await sections.count();
  for (let i = 0; i < n; i++) {
    await sections.nth(i).screenshot({ path: `shots/preview_${label}_${i + 1}.png` });
  }
  console.log(label, "sections:", n, "cards:", await page.locator(".cc-event, .cc-carousel__item").count(), "errors:", JSON.stringify(errors));
  await page.close();
}
await browser.close();

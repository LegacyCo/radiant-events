// One-off: capture a Squarespace summary carousel (markup, styles, screenshots).
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "fs";
mkdirSync("shots", { recursive: true });
const url = process.argv[2];
const password = process.argv[3];
const browser = await chromium.launch();

for (const [label, width] of [["desktop", 1440], ["mobile", 390]]) {
  const ctx = await browser.newContext({ viewport: { width, height: 1000 } });
  const page = await ctx.newPage();
  await page.goto(url, { waitUntil: "networkidle" }).catch((e) => console.log("goto:", e.message));
  const pw = page.locator('input[type="password"]');
  if (await pw.count()) {
    console.log(label, "password page, unlocking");
    await pw.first().fill(password);
    await pw.first().press("Enter");
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2500);
    if (!page.url().includes("/home")) await page.goto(url.split("?")[0], { waitUntil: "networkidle" }).catch(() => {});
  }
  await page.waitForTimeout(2500);
  console.log(`\n===== ${label} ${page.url()} | ${await page.title()}`);
  await page.screenshot({ path: `shots/ref_${label}_full.png`, fullPage: true });

  const blocks = page.locator(".summary-block-wrapper, .sqs-block-summary-v2");
  const n = await blocks.count();
  console.log("summary blocks:", n);
  for (let i = 0; i < n; i++) {
    const blk = blocks.nth(i);
    await blk.scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(800);
    // include the section heading above it
    const section = blk.locator("xpath=ancestor::section[1]");
    await (await section.count() ? section : blk).screenshot({ path: `shots/ref_${label}_summary${i + 1}.png` }).catch(() => {});
    const info = await blk.evaluate((b) => {
      const s = (sel) => { const el = b.querySelector(sel); if (!el) return null; const c = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return `${Math.round(r.width)}x${Math.round(r.height)} | ${c.fontFamily} ${c.fontWeight} ${c.fontSize}/${c.lineHeight} ls:${c.letterSpacing} ${c.textTransform} color:${c.color} bg:${c.backgroundColor} radius:${c.borderRadius} pad:${c.padding} margin:${c.margin} gap:${c.gap} display:${c.display} ar:${c.aspectRatio}`; };
      const wrapper = b.closest(".summary-block-wrapper") || b.querySelector(".summary-block-wrapper") || b;
      return {
        classes: wrapper.className,
        items: b.querySelectorAll(".summary-item").length,
        visibleItems: [...b.querySelectorAll(".summary-item")].filter((x) => { const r = x.getBoundingClientRect(); return r.right > 0 && r.left < innerWidth; }).length,
        heading: s(".summary-heading, .summary-block-header"),
        styles: Object.fromEntries([".summary-item-list", ".summary-carousel-pager", ".summary-carousel-pager-prev", ".summary-carousel-pager-next",
          ".summary-item", ".summary-thumbnail-outer-container", ".summary-thumbnail-container", ".summary-thumbnail", ".summary-thumbnail-image",
          ".summary-thumbnail-event-date", ".summary-thumbnail-event-date-month", ".summary-thumbnail-event-date-day",
          ".summary-content", ".summary-title", ".summary-title-link", ".summary-metadata-container", ".summary-metadata", ".summary-metadata-item",
          ".summary-metadata-item--date", ".summary-metadata-item--event-time", ".summary-metadata-item--location",
          ".summary-excerpt", ".summary-read-more-link", ".summary-header-text"].map((k) => [k, s(k)])),
        firstItem: (b.querySelector(".summary-item") || {}).outerHTML?.slice(0, 5000),
        header: (b.querySelector(".summary-heading, .summary-block-header") || {}).outerHTML?.slice(0, 1500),
        pager: (b.querySelector(".summary-carousel-pager") || {}).outerHTML?.slice(0, 2500),
        sectionHeading: (() => { const sec = b.closest("section"); const h = sec && sec.querySelector("h1,h2,h3"); return h ? h.outerHTML.slice(0, 600) + " || " + getComputedStyle(h).fontFamily + " " + getComputedStyle(h).fontSize : null; })(),
      };
    });
    console.log(`\n--- summary ${i + 1}: ${info.items} items, ${info.visibleItems} visible | ${info.classes}`);
    console.log("section heading:", info.sectionHeading);
    console.log("heading:", info.heading);
    for (const [k, v] of Object.entries(info.styles)) if (v) console.log(`  ${k}: ${v}`);
    if (label === "desktop") {
      writeFileSync(`shots/ref_summary${i + 1}_item.html`, info.firstItem || "");
      writeFileSync(`shots/ref_summary${i + 1}_pager.html`, (info.header || "") + "\n\n" + (info.pager || ""));
    }
    // Try the next arrow to see how it moves
    const next = blk.locator(".summary-carousel-pager-next");
    if (await next.count() && label === "desktop") {
      const before = await blk.evaluate((b) => b.querySelector(".summary-item-list")?.style.transform || b.querySelector(".summary-item-list")?.scrollLeft);
      await next.first().click().catch(() => {});
      await page.waitForTimeout(900);
      const after = await blk.evaluate((b) => b.querySelector(".summary-item-list")?.style.transform || b.querySelector(".summary-item-list")?.scrollLeft);
      console.log("next arrow: before", before, "after", after);
      await (await section.count() ? section : blk).screenshot({ path: `shots/ref_${label}_summary${i + 1}_after_next.png` }).catch(() => {});
    }
  }
  await ctx.close();
}
await browser.close();

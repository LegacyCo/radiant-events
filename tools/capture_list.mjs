// One-off: capture a Squarespace List Section carousel (styles, markup, screenshots).
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "fs";
mkdirSync("shots", { recursive: true });
const url = process.argv[2], password = process.argv[3];
const browser = await chromium.launch();
for (const [label, width] of [["desktop", 1440], ["tablet", 900], ["mobile", 390]]) {
  const ctx = await browser.newContext({ viewport: { width, height: 1000 } });
  const page = await ctx.newPage();
  await page.goto(url, { waitUntil: "networkidle" }).catch((e) => console.log("goto:", e.message));
  const pw = page.locator('input[type="password"]');
  if (await pw.count()) {
    await pw.first().fill(password); await pw.first().press("Enter");
    await page.waitForLoadState("networkidle").catch(() => {}); await page.waitForTimeout(2500);
    if (!page.url().includes("/home")) await page.goto(url.split("?")[0], { waitUntil: "networkidle" }).catch(() => {});
  }
  // scroll the whole page so lazy images load
  for (let y = 0; y < 9000; y += 600) { await page.evaluate((yy) => scrollTo(0, yy), y); await page.waitForTimeout(150); }
  const sec = page.locator(".user-items-list-carousel, .user-items-list-section, [data-section-id] .user-items-list").first();
  console.log(`\n===== ${label} list sections:`, await page.locator(".user-items-list-section, .user-items-list").count());
  if (!(await sec.count())) { console.log("no list section"); await ctx.close(); continue; }
  const section = sec.locator("xpath=ancestor-or-self::section[1]");
  await section.scrollIntoViewIfNeeded(); await page.waitForTimeout(1500);
  await section.screenshot({ path: `shots/list_${label}.png` });
  const info = await section.evaluate((s) => {
    const st = (el) => { if (!el) return null; const c = getComputedStyle(el), r = el.getBoundingClientRect();
      return `${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)} | ${c.fontFamily} ${c.fontWeight} ${c.fontSize}/${c.lineHeight} ls:${c.letterSpacing} ${c.textTransform} ${c.fontStyle} align:${c.textAlign} color:${c.color} bg:${c.backgroundColor} radius:${c.borderRadius} pad:${c.padding} margin:${c.margin} gap:${c.gap} display:${c.display} ar:${c.aspectRatio} obj:${c.objectFit} border:${c.border} deco:${c.textDecorationLine} ${c.textUnderlineOffset} trans:${c.transform}`; };
    const q = (sel) => s.querySelector(sel);
    const sels = ["section", ".user-items-list", ".list-section-title", ".list-section-title p", ".user-items-list-carousel__gutter", ".user-items-list-carousel__slideshow-holder",
      ".user-items-list-carousel__slides", ".list-item", ".user-items-list-carousel__slide", ".list-item-media", ".list-item-media-inner", ".list-image", ".list-item-media img",
      ".list-item-content", ".list-item-content__title", ".list-item-content__description", ".list-item-content__description p", ".list-item-content__button-container",
      ".list-item-content__button", ".user-items-list-carousel__arrow-button", ".user-items-list-carousel__arrow-button--left", ".user-items-list-carousel__arrow-icon",
      ".user-items-list-carousel__arrow-icon path", ".user-items-list-carousel__arrow-wrapper"];
    const out = {};
    for (const k of sels) out[k] = st(k === "section" ? s : q(k));
    const vars = {}; const cs = getComputedStyle(s.querySelector(".user-items-list") || s);
    for (const v of ["--list-section-carousel-arrow-color", "--list-section-carousel-arrow-background-color", "--list-section-carousel-card-color",
      "--list-section-title-color", "--list-item-title-color", "--list-item-description-color", "--list-item-button-color"]) vars[v] = cs.getPropertyValue(v);
    const ul = s.querySelector(".user-items-list-carousel__slides, ul");
    return { out, vars, slides: s.querySelectorAll(".list-item").length,
      dataset: JSON.stringify((s.querySelector(".user-items-list") || {}).dataset || {}).slice(0, 3000),
      gridCols: ul ? getComputedStyle(ul).gridTemplateColumns + " | gap " + getComputedStyle(ul).columnGap : null,
      html: s.outerHTML.replace(/\s+/g, " ").slice(0, 9000) };
  });
  console.log("slides:", info.slides, "grid:", info.gridCols);
  for (const [k, v] of Object.entries(info.out)) if (v) console.log(`  ${k}: ${v}`);
  console.log("vars:", JSON.stringify(info.vars));
  console.log("dataset:", info.dataset);
  if (label === "desktop") {
    writeFileSync("shots/list_section.html", info.html);
    const right = section.locator(".user-items-list-carousel__arrow-button--right, .user-items-list-carousel__arrow-button").last();
    if (await right.count()) { await right.click().catch(() => {}); await page.waitForTimeout(1200); await section.screenshot({ path: "shots/list_desktop_next.png" });
      console.log("after next transform:", await section.evaluate((s) => getComputedStyle(s.querySelector(".user-items-list-carousel__slides") || s).transform)); }
    // hover state of arrow
    await section.locator(".user-items-list-carousel__arrow-button").first().hover().catch(() => {}); await page.waitForTimeout(400);
    console.log("arrow hover:", await section.evaluate((s) => { const b = s.querySelector(".user-items-list-carousel__arrow-button"); return b ? getComputedStyle(b).backgroundColor + " " + getComputedStyle(b).opacity : null; }));
  }
  await ctx.close();
}
await browser.close();

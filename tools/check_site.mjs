// One-off diagnostics: Radiant's event pages (markup, styles, screenshots) and the
// Church Center popup when the page is on radiantcentralcoast.com.
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "fs";
mkdirSync("shots", { recursive: true });
const SITE = "https://radiantcentralcoast.com";

console.log("##### 1. Pages that look like events in the sitemap");
const sitemap = await (await fetch(SITE + "/sitemap.xml")).text();
const urls = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
const eventish = urls.filter((u) => /event|calendar|past/i.test(u));
console.log(urls.length, "urls;", eventish.length, "event-ish:", eventish.slice(0, 25).join("\n  "));
// collection pages (the list pages, not each event)
const lists = [...new Set(eventish.map((u) => u.replace(/^(https:\/\/[^/]+\/[^/]+).*$/, "$1")))];
console.log("list pages:", lists);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });

console.log("\n##### 2. Event list markup and styles");
const candidates = [...new Set([...lists, ...lists.map((u) => u + "?view=past"), SITE + "/events"])].slice(0, 6);
for (const url of candidates) {
  const page = await ctx.newPage();
  const r = await page.goto(url, { waitUntil: "networkidle" }).catch(() => null);
  await page.waitForTimeout(1500);
  const slug = url.replace(SITE, "").replace(/[^a-z0-9]+/gi, "_") || "home";
  await page.screenshot({ path: `shots/${slug}.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `shots/${slug}_mobile.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  const info = await page.evaluate(() => {
    const ev = document.querySelector(".eventlist-event, article.eventlist-event, .summary-item, .user-items-list-item-container");
    const style = (sel) => { const el = document.querySelector(sel); if (!el) return null; const s = getComputedStyle(el);
      return `${s.fontFamily} ${s.fontWeight} ${s.fontSize}/${s.lineHeight} ls:${s.letterSpacing} ${s.textTransform} color:${s.color} bg:${s.backgroundColor} border:${s.borderTop} radius:${s.borderRadius} pad:${s.padding} margin:${s.margin}`; };
    return {
      count: document.querySelectorAll(".eventlist-event").length,
      classes: [...new Set([...document.querySelectorAll("[class*=eventlist]")].map((e) => e.className.split(" ")[0]))].slice(0, 40),
      outer: ev ? ev.outerHTML.slice(0, 6000) : null,
      styles: Object.fromEntries([".eventlist", ".eventlist-event", ".eventlist-column-date", ".eventlist-datetag", ".eventlist-datetag-startdate--month",
        ".eventlist-datetag-startdate--day", ".eventlist-column-info", ".eventlist-title", ".eventlist-title-link", ".eventlist-meta",
        ".eventlist-meta-item", ".eventlist-meta-time", ".eventlist-meta-address", ".eventlist-excerpt", ".eventlist-description",
        ".eventlist-button", ".eventlist-column-thumbnail", ".eventlist-filter", ".eventlist-pagination",
        "h1", "h2", "h3", "p", ".sqs-block-button-element--primary"].map((s) => [s, style(s)])),
    };
  });
  console.log(`\n=== ${url} -> ${r && r.status()} | eventlist items: ${info.count}`);
  console.log("classes:", info.classes.join(" "));
  for (const [k, v] of Object.entries(info.styles)) if (v) console.log(`  ${k}: ${v}`);
  if (info.outer) { writeFileSync(`shots/${slug}_first_event.html`, info.outer); console.log("first item markup saved"); }
  await page.close();
}

console.log("\n##### 3. Church Center popup on radiantcentralcoast.com");
const page = await ctx.newPage();
const testHtml = `<!doctype html><html><head><meta charset="utf-8"></head><body>
<a id="reg" href="https://radiantcentralcoast.churchcenter.com/registrations/events/3919181" data-open-in-church-center-modal="true">Register</a>
<a id="cal" href="https://radiantcentralcoast.churchcenter.com/calendar/event/200190659" data-open-in-church-center-modal="true">Details</a>
<script src="https://js.churchcenter.com/modal/v1"></script></body></html>`;
await page.route(SITE + "/__modal-test", (route) => route.fulfill({ status: 200, contentType: "text/html", body: testHtml }));
const chain = [];
page.on("response", (res) => { if (res.url().includes("churchcenter.com") && !res.url().includes("js.churchcenter")) chain.push(`${res.status()} ${res.url().slice(0, 110)} xfo=${res.headers()["x-frame-options"] || "-"} loc=${(res.headers()["location"] || "").slice(0, 80)}`); });
const errs = [];
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errs.push(m.text().slice(0, 200)); });
await page.goto(SITE + "/__modal-test", { waitUntil: "networkidle" });
for (const id of ["reg", "cal"]) {
  chain.length = 0; errs.length = 0;
  await page.click("#" + id);
  await page.waitForTimeout(6000);
  const shown = await page.$$eval("iframe", (fs) => fs.map((f) => `${f.src.slice(0, 100)} ${getComputedStyle(f).display} ${f.offsetWidth}x${f.offsetHeight}`));
  console.log(`${id}: iframes=${JSON.stringify(shown)}\n   responses=${JSON.stringify(chain)}\n   console=${JSON.stringify(errs)}`);
  await page.screenshot({ path: `shots/modal_${id}.png` });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(1000);
}
await browser.close();

// Finds the YouTube stream switcher on radiantcentralcoast.com and reports what it does. Text only.
import { chromium } from "playwright";
const site = "https://radiantcentralcoast.com";
const playlist = process.argv[2] || "PL-J1TyONqnHIYHcXoTiHBzU7UGX9vWNEd";

// 1. Is the playlist public and embeddable?
for (const u of [`https://www.youtube.com/oembed?format=json&url=${encodeURIComponent("https://www.youtube.com/playlist?list=" + playlist)}`]) {
  const r = await fetch(u); console.log("oembed playlist:", r.status, (await r.text()).slice(0, 300));
}
const pl = await (await fetch(`https://www.youtube.com/playlist?list=${playlist}`, { headers: { "Accept-Language": "en" } })).text();
console.log("playlist page title:", (pl.match(/<title>([^<]*)/) || [])[1], "| first videoIds:", [...new Set([...pl.matchAll(/"videoId":"([\w-]{11})"/g)].map((m) => m[1]))].slice(0, 5).join(","));

// 2. Which pages carry the switcher?
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
await page.goto(site, { waitUntil: "domcontentloaded" });
const links = [...new Set(await page.$$eval("a[href]", (as) => as.map((a) => a.href).filter((h) => h.startsWith(location.origin)).map((h) => h.split("#")[0])))].slice(0, 60);
const candidates = [];
for (const u of [site + "/", ...links]) {
  try {
    const html = await (await fetch(u)).text();
    if (html.includes("cpIframe")) candidates.push({ u, version: html.includes("LIVE_WINDOWS") ? "new (quota-safe), banner " + ((html.match(/SHOW_BANNER\s*=\s*(\w+)/) || [])[1]) : html.includes("POLL_MS") ? "old (10 s polling)" : "unknown" });
  } catch {}
}
console.log("pages with the switcher:", JSON.stringify(candidates));

// 3. Load each and report the player state after 10 s.
for (const c of candidates) {
  const p = await ctx.newPage();
  const errs = [], api = [];
  p.on("pageerror", (e) => errs.push("pageerror: " + e.message));
  p.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errs.push(m.type() + ": " + m.text().slice(0, 200)); });
  p.on("response", (r) => { if (r.url().includes("googleapis.com/youtube")) api.push(r.status() + " " + r.url().split("?")[0].split("/").pop()); });
  await p.goto(c.u, { waitUntil: "networkidle" }).catch((e) => errs.push("goto: " + e.message));
  await p.locator('#cpWrap').scrollIntoViewIfNeeded().catch(() => {});
  await p.waitForTimeout(12000);
  const st = await p.evaluate(() => {
    const f = document.getElementById("cpIframe"), ph = document.getElementById("cpPlaceholder"), b = document.getElementById("cpBtn");
    const blocks = document.querySelectorAll("#cpWrap").length;
    return { blocks, iframeSrc: f && f.src, iframeBox: f && (({ width, height }) => Math.round(width) + "x" + Math.round(height))(f.getBoundingClientRect()),
      placeholder: ph && getComputedStyle(ph).display + " '" + ph.innerText.trim() + "'", button: b && b.className + " '" + b.innerText.trim() + "' " + b.href,
      status: (document.getElementById("cpStatus") || {}).innerText, referrerPolicy: (document.querySelector('meta[name="referrer"]') || {}).content || "(none)" };
  });
  console.log(`\n== ${c.u} [${c.version}]`, JSON.stringify(st, null, 1));
  console.log("API responses:", api.join(", ") || "none");
  const yt = p.frames().find((f) => f.url().includes("youtube"));
  if (yt) {
    const txt = await yt.evaluate(() => document.body.innerText.replace(/\s+/g, " ").slice(0, 300)).catch((e) => "can't read: " + e.message);
    const title = await yt.evaluate(() => (document.querySelector(".ytp-title-link") || {}).textContent || "").catch(() => "");
    console.log("youtube frame:", yt.url().split("?")[0], "| title:", title, "| text:", txt);
  } else console.log("youtube frame: none");
  console.log("errors:", errs.slice(0, 15));
}
await browser.close();

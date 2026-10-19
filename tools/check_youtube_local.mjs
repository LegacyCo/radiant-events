// Serves the new switcher (no API key, so the API fails like an empty quota) and checks the player loads.
import { chromium } from "playwright";
import { createServer } from "http";
import { readFileSync } from "fs";
const body = '<!doctype html><html><head><meta charset="utf-8"></head><body style="max-width:1000px;margin:auto">' + readFileSync("tools/switcher-test.html", "utf8") + "</body></html>";
const server = createServer((q, r) => { r.writeHead(200, { "Content-Type": "text/html" }); r.end(body); }).listen(8080);
const browser = await chromium.launch();
const p = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errs = [];
p.on("pageerror", (e) => errs.push(e.message));
await p.goto("http://localhost:8080/", { waitUntil: "networkidle" });
await p.waitForTimeout(8000);
console.log(JSON.stringify(await p.evaluate(() => ({
  iframeSrc: document.getElementById("cpIframe").src,
  placeholder: getComputedStyle(document.getElementById("cpPlaceholder")).display,
  button: document.getElementById("cpBtn").innerText + " -> " + document.getElementById("cpBtn").href,
  status: document.getElementById("cpStatus").innerText })), null, 1));
const yt = p.frames().find((f) => f.url().includes("youtube"));
if (yt) {
  await yt.waitForSelector(".ytp-title-link, .ytp-error", { timeout: 15000 }).catch(() => {});
  console.log("youtube frame:", yt.url().split("?")[0], "| title:", await yt.evaluate(() => (document.querySelector(".ytp-title-link") || {}).textContent || "").catch(() => "?"),
    "| error:", await yt.evaluate(() => (document.querySelector(".ytp-error") || {}).innerText || "none").catch(() => "?"));
} else console.log("youtube frame: none");
console.log("errors:", errs);
await browser.close(); server.close();

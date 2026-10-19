// Which pages on radiantcentralcoast.com carry the YouTube switcher / live banner code, and how is each set up?
const site = "https://radiantcentralcoast.com";
const home = await (await fetch(site + "/")).text();
const links = [...new Set([...home.matchAll(/href="(\/[^"#?]*)"/g)].map((m) => m[1]).filter((h) => !/\.(css|js|png|jpg|svg|ico)$/.test(h)))].slice(0, 80);
for (const path of ["/", ...links]) {
  let html;
  try { html = await (await fetch(site + path)).text(); } catch { continue; }
  const hits = {
    bannerCode: (html.match(/cp-live-banner/g) || []).length,
    player: (html.match(/id="cpIframe"/g) || []).length,
    showBanner: [...html.matchAll(/SHOW_BANNER\s*=\s*(\w+)/g)].map((m) => m[1]).join(","),
    pollMs: [...html.matchAll(/POLL_MS\s*=\s*(\d+)/g)].map((m) => m[1]).join(","),
    liveWindows: html.includes("LIVE_WINDOWS"),
    scriptBlocks: (html.match(/YouTube Data API|youtube\/v3/g) || []).length,
  };
  if (hits.bannerCode || hits.player || hits.scriptBlocks) console.log(path, JSON.stringify(hits));
}
// Where in the page does it sit on the home page? (code injection lands in <head> or before </body>)
const i = home.indexOf("cp-live-banner");
if (i > -1) console.log("home: first banner code at", i, "of", home.length, "| context:", home.slice(Math.max(0, i - 300), i).replace(/\s+/g, " ").slice(-300));
const j = home.indexOf("SHOW_BANNER");
if (j > -1) console.log("home SHOW_BANNER context:", home.slice(j - 200, j + 200).replace(/\s+/g, " "));

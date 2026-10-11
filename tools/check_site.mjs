// One-off: does Church Center allow framing with ?open-in-church-center-modal=true?
const base = "https://radiantcentralcoast.churchcenter.com";
const paths = ["/registrations/events/3919181", "/calendar/event/200190659", "/registrations", "/calendar", "/giving", "/groups", "/home", "/"];
const params = ["", "?open-in-church-center-modal=true", "?embed=true"];
const headerSets = {
  plain: {},
  "iframe from radiantcentralcoast.com": {
    "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "cross-site",
    Referer: "https://radiantcentralcoast.com/events",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36",
  },
};
for (const [label, headers] of Object.entries(headerSets)) {
  console.log(`\n##### ${label}`);
  for (const p of paths) for (const q of params) {
    const r = await fetch(base + p + q, { headers, redirect: "manual" });
    const csp = (r.headers.get("content-security-policy") || "").match(/frame-ancestors[^;]*/);
    console.log(`${String(r.status).padEnd(4)} xfo=${(r.headers.get("x-frame-options") || "-").padEnd(10)} csp=${csp ? csp[0] : "-"}  ${p}${q}${r.headers.get("location") ? "  -> " + r.headers.get("location") : ""}`);
  }
}

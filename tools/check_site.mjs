// One-off: is the events embed's <script> in the served HTML, or did Squarespace strip it?
const urls = process.argv.slice(2);
for (const url of urls) {
  const html = await (await fetch(url, { headers: { "User-Agent": "Mozilla/5.0 (radiant-events check)" } })).text();
  console.log(`\n===== ${url}  (${html.length} bytes)`);
  const markers = {
    "embed markup (.cc-events div)": /class="cc-events"/.test(html),
    "embed CSS (.cc-events__tab)": html.includes(".cc-events__tab"),
    "embed script (data-cc-ready)": html.includes("data-cc-ready"),
    "embed CONFIG (FEED_URL)": html.includes("FEED_URL"),
    "feed address": html.includes("legacyco.github.io/radiant-events"),
  };
  for (const [k, v] of Object.entries(markers)) console.log(`${v ? "yes" : "NO "}  ${k}`);
  const blocks = html.split('sqs-block-code').slice(1);
  blocks.forEach((b, i) => {
    const chunk = b.slice(0, 40000);
    const end = chunk.indexOf('class="sqs-block ');
    const body = end > 0 ? chunk.slice(0, end) : chunk;
    console.log(`code block ${i + 1}: ${body.length} chars, <script> tags: ${(body.match(/<script/g) || []).length}, has cc-events: ${body.includes("cc-events")}`);
  });
  const ctx = html.match(/"(?:billingStatus|websiteType|isEnterprise|productType|planType|subscriptionType)"\s*:\s*"?[^,}"]*"?/g);
  console.log("site context hints:", ctx ? [...new Set(ctx)].slice(0, 8).join(" | ") : "none");
}

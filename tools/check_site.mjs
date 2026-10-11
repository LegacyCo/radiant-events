// One-off: show what Squarespace served around the events embed, and the block whose script survived.
const url = process.argv[2];
const html = await (await fetch(url, { headers: { "User-Agent": "Mozilla/5.0 (radiant-events check)" } })).text();
const blocks = html.split('sqs-block-code').slice(1);
blocks.forEach((b, i) => {
  const end = b.indexOf('class="sqs-block ');
  const body = end > 0 ? b.slice(0, end) : b.slice(0, 30000);
  console.log(`\n===== code block ${i + 1} (${body.length} chars)`);
  console.log("--- first 700 chars:\n" + body.slice(0, 700));
  const styleEnd = body.indexOf("</style>");
  if (styleEnd > 0) console.log("--- 900 chars after </style>:\n" + body.slice(styleEnd, styleEnd + 900));
  const sc = body.indexOf("<script");
  if (sc >= 0) console.log("--- script opens as:\n" + body.slice(sc, sc + 300));
  console.log("--- last 400 chars:\n" + body.slice(-400));
});

#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const key = a.slice(2);
    if (key === "headed") {
      out.headed = true;
      continue;
    }
    if (key === "headless") {
      out.headed = false;
      continue;
    }
    const v = argv[i + 1];
    if (v == null || v.startsWith("--")) {
      out[key] = true;
    } else {
      out[key] = v;
      i++;
    }
  }
  return out;
}

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
  return p;
}

function safeFilePart(s) {
  return String(s).replace(/[^a-zA-Z0-9._-]+/g, "_");
}

function yenToInt(s) {
  if (s == null) return null;
  const normalized = String(s).replace(/[，,]/g, "").replace(/[円\s]/g, "");
  const m = normalized.match(/-?\d+/);
  return m ? Number.parseInt(m[0], 10) : null;
}

function normalizeText(s) {
  return String(s)
    .replace(/[０-９]/g, (d) => String.fromCharCode(d.charCodeAt(0) - 0xfee0))
    .replace(/[，]/g, ",")
    .replace(/[／]/g, "/")
    .replace(/[－–—]/g, "-")
    .replace(/[（]/g, "(")
    .replace(/[）]/g, ")")
    .replace(/[\u200B-\u200D\uFEFF]/g, "");
}

function parseAnyDate(s) {
  if (!s) return null;
  const t = String(s).trim();
  const m = t.match(/(20\d{2})\D{0,4}(\d{1,2})\D{0,4}(\d{1,2})/);
  if (m) return `${m[1]}-${String(+m[2]).padStart(2, "0")}-${String(+m[3]).padStart(2, "0")}`;
  return null;
}

async function writeDebug(page, debugDir, name) {
  try {
    ensureDir(debugDir);
    await page.screenshot({ path: path.join(debugDir, `${name}.png`), fullPage: true });
    const html = await page.content();
    fs.writeFileSync(path.join(debugDir, `${name}.html`), html, "utf-8");
  } catch {
    // best-effort
  }
}

async function extractRows(page) {
  const candidates = ["table tbody tr", "[role='row']", ".table tbody tr"];
  for (const sel of candidates) {
    const rows = page.locator(sel);
    const n = await rows.count();
    if (n >= 1) return rows;
  }
  return page.locator("table tbody tr");
}

async function bestEffortRowData(row, pageUrl) {
  const text = await row.innerText().catch(() => "");
  const normalized = normalizeText(text);
  const useDate = parseAnyDate(normalized);
  const amountMatches = [...normalized.matchAll(/([0-9][0-9,]*)\D{0,3}円/g)];
  const amountYen = amountMatches.length ? yenToInt(amountMatches[amountMatches.length - 1][1]) : null;
  if (process.env.AX_DEBUG && (!useDate || amountYen == null)) {
    const sample = text.replace(/\s+/g, " ").slice(0, 160);
    const normalizedSample = normalized.replace(/\s+/g, " ").slice(0, 160);
    const dm = normalized.match(/(20\d{2})\D{0,4}(\d{1,2})\D{0,4}(\d{1,2})/);
    const am = normalized.match(/([0-9][0-9,]*)\D{0,3}円/);
    console.error(
      `[DEBUG] parse failed: useDate=${useDate} amountYen=${amountYen} dm=${dm ? dm[0] : "null"} am=${am ? am[1] : "null"} text="${sample}" normalized="${normalizedSample}"`
    );
  }

  let detailUrl = null;
  const a = row.locator("a[href]").first();
  if ((await a.count()) > 0) {
    const href = await a.getAttribute("href");
    if (href) detailUrl = href.startsWith("/") ? new URL(href, pageUrl).toString() : href;
  }

  let hasEvidence = false;
  const evidenceMarkers = ["証憑", "添付", "領収書", "ファイル", "paperclip"];
  for (const m of evidenceMarkers) {
    if (text.includes(m)) {
      hasEvidence = true;
      break;
    }
  }
  if (text.includes("未添付") || text.includes("なし")) {
    hasEvidence = false;
  }

  let expenseId = null;
  if (detailUrl) {
    const idMatch = detailUrl.match(/(\d{5,})/);
    if (idMatch) expenseId = idMatch[1];
  }
  if (!expenseId) {
    expenseId = safeFilePart(`${useDate || "nodate"}_${amountYen || "noamt"}_${text.slice(0, 20)}`);
  }

  return {
    expense_id: expenseId,
    use_date: useDate,
    amount_yen: amountYen,
    vendor: "",
    memo: text,
    has_evidence: hasEvidence,
    detail_url: detailUrl,
    raw_text: text,
  };
}

async function main() {
  const args = parseArgs(process.argv);
  const storageState = args["storage-state"];
  const expenseListUrl = args["expense-list-url"];
  const outJsonl = args["out-jsonl"];
  const debugDir = args["debug-dir"];
  const headed = args.headed !== false;
  const slowMoMs = Number.parseInt(args["slow-mo-ms"] || "0", 10);
  const year = Number.parseInt(args.year, 10);
  const month = Number.parseInt(args.month, 10);

  if (!storageState) throw new Error("Missing --storage-state");
  if (!expenseListUrl) throw new Error("Missing --expense-list-url");
  if (!outJsonl) throw new Error("Missing --out-jsonl");
  if (!year || !month) throw new Error("Missing --year/--month");

  ensureDir(path.dirname(outJsonl));
  if (debugDir) ensureDir(debugDir);

  const browser = await chromium.launch({ headless: !headed, slowMo: slowMoMs });
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  try {
    await page.goto(expenseListUrl, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});

    const rowsLoc = await extractRows(page);
    const n = await rowsLoc.count();
    const lines = [];
    let extracted = 0;

    const ymPrefix = `${year}-${String(month).padStart(2, "0")}-`;
    for (let i = 0; i < n; i++) {
      const row = rowsLoc.nth(i);
      const obj = await bestEffortRowData(row, page.url());
      if (obj.use_date && !obj.use_date.startsWith(ymPrefix)) continue;
      lines.push(JSON.stringify(obj));
      extracted += 1;
    }

    fs.writeFileSync(outJsonl, lines.join("\n") + (lines.length ? "\n" : ""), "utf-8");
    console.log(
      JSON.stringify({
        status: "success",
        data: { extracted, out_jsonl: outJsonl, note: "MF Cloud UI differs by tenant; if extraction is wrong, adjust selectors/heuristics." },
      })
    );
  } catch (e) {
    if (debugDir) await writeDebug(page, debugDir, "fatal");
    throw e;
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});

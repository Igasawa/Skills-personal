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
  const m = String(s).replace(/[,円\\s]/g, "").match(/-?\\d+/);
  return m ? Number.parseInt(m[0], 10) : null;
}

function parseJapaneseDate(s, fallbackYear) {
  if (!s) return null;
  const t = String(s).trim();
  let m = t.match(/(\\d{4})[/-](\\d{1,2})[/-](\\d{1,2})/);
  if (m) return { y: +m[1], m: +m[2], d: +m[3] };
  m = t.match(/(\\d{4})年(\\d{1,2})月(\\d{1,2})日/);
  if (m) return { y: +m[1], m: +m[2], d: +m[3] };
  m = t.match(/(\\d{1,2})月(\\d{1,2})日/);
  if (m && fallbackYear) return { y: +fallbackYear, m: +m[1], d: +m[2] };
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

async function trySelectYear(page, year) {
  const yearText = `${year}年`;
  const candidates = ["select#orderFilter", "select[name='orderFilter']", "select"];
  for (const sel of candidates) {
    const loc = page.locator(sel);
    const count = await loc.count();
    if (!count) continue;
    for (let i = 0; i < count; i++) {
      const s = loc.nth(i);
      try {
        const options = await s.locator("option").allTextContents();
        const idx = options.findIndex((t) => t.includes(yearText) || t.includes(String(year)));
        if (idx >= 0) {
          const value = await s.locator("option").nth(idx).getAttribute("value");
          if (value) {
            await s.selectOption(value);
            await page.waitForLoadState("networkidle");
            return true;
          }
        }
      } catch {
        // continue
      }
    }
  }
  return false;
}

async function extractOrdersFromPage(page, year, targetMonth) {
  const orderCards = page.locator("div").filter({ hasText: "注文番号" });
  const n = await orderCards.count();
  const orders = [];

  for (let i = 0; i < n; i++) {
    const card = orderCards.nth(i);
    const cardText = await card.innerText().catch(() => "");

    const idMatch = cardText.match(/注文番号\\s*[:：]?\\s*([0-9-]{10,})/);
    const orderId = idMatch ? idMatch[1] : null;

    const dateMatch = cardText.match(/注文日\\s*[:：]?\\s*([^\\n]+)/) || cardText.match(/注文日\\s*([^\\n]+)/);
    const dateParts = dateMatch ? parseJapaneseDate(dateMatch[1], year) : null;
    const orderDate = dateParts
      ? `${String(dateParts.y).padStart(4, "0")}-${String(dateParts.m).padStart(2, "0")}-${String(dateParts.d).padStart(2, "0")}`
      : null;

    if (!orderDate) continue;
    const m = Number.parseInt(orderDate.slice(5, 7), 10);
    if (m !== targetMonth) continue;

    const totalMatch = cardText.match(/合計\\s*[:：]?\\s*([0-9,]+)\\s*円/) || cardText.match(/合計\\s*([0-9,]+)\\s*円/);
    const totalYen = totalMatch ? yenToInt(totalMatch[1]) : null;

    let detailUrl = null;
    const detailLink = card.locator("a", { hasText: "注文の詳細" }).first();
    if ((await detailLink.count()) > 0) {
      detailUrl = await detailLink.getAttribute("href");
    }
    if (detailUrl && detailUrl.startsWith("/")) {
      detailUrl = new URL(detailUrl, page.url()).toString();
    }

    if (!orderId) continue;
    orders.push({ order_id: orderId, order_date: orderDate, total_yen: totalYen, detail_url: detailUrl });
  }

  return orders;
}

async function findReceiptLink(page) {
  const labels = ["領収書", "領収書/購入明細", "購入明細書", "領収書等", "Invoice", "Receipt"];
  for (const label of labels) {
    const a = page.locator("a", { hasText: label }).first();
    if ((await a.count()) > 0) return a;
  }
  return null;
}

async function saveReceiptPdf(page, outPdfPath) {
  await page.emulateMedia({ media: "print" });
  await page.pdf({ path: outPdfPath, format: "A4", printBackground: true });
}

async function main() {
  const args = parseArgs(process.argv);
  const storageState = args["storage-state"];
  const ordersUrl = args["orders-url"] || "https://www.amazon.co.jp/gp/your-account/order-history";
  const outJsonl = args["out-jsonl"];
  const outPdfsDir = args["out-pdfs-dir"];
  const debugDir = args["debug-dir"];
  const year = Number.parseInt(args.year, 10);
  const month = Number.parseInt(args.month, 10);
  const headed = args.headed !== false;
  const slowMoMs = Number.parseInt(args["slow-mo-ms"] || "0", 10);

  if (!storageState) throw new Error("Missing --storage-state");
  if (!outJsonl) throw new Error("Missing --out-jsonl");
  if (!outPdfsDir) throw new Error("Missing --out-pdfs-dir");
  if (!year || !month) throw new Error("Missing --year/--month");

  ensureDir(path.dirname(outJsonl));
  ensureDir(outPdfsDir);
  if (debugDir) ensureDir(debugDir);

  const browser = await chromium.launch({ headless: !headed, slowMo: slowMoMs });
  const pdfBrowser = headed ? await chromium.launch({ headless: true }) : browser;
  const context = await browser.newContext({ storageState });
  const pdfContext = pdfBrowser === browser ? context : await pdfBrowser.newContext({ storageState });
  const page = await context.newPage();

  let allOrders = [];
  try {
    await page.goto(ordersUrl, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});

    await trySelectYear(page, year);

    const seenOrderIds = new Set();
    for (let pageNo = 1; pageNo <= 50; pageNo++) {
      await page.waitForTimeout(300);
      const orders = await extractOrdersFromPage(page, year, month);
      for (const o of orders) {
        if (!seenOrderIds.has(o.order_id)) {
          seenOrderIds.add(o.order_id);
          allOrders.push(o);
        }
      }

      const next = page.locator("a", { hasText: "次へ" }).first();
      if ((await next.count()) === 0) break;
      const disabled = await next.getAttribute("aria-disabled");
      if (disabled === "true") break;
      await next.click();
      await page.waitForLoadState("networkidle").catch(() => {});
    }

    const lines = [];
    let pdfSaved = 0;
    let noReceipt = 0;

    for (const order of allOrders) {
      let status = "ok";
      let receiptUrl = null;
      let pdfPath = null;

      try {
        if (!order.detail_url) throw new Error("missing detail_url");
        await page.goto(order.detail_url, { waitUntil: "domcontentloaded" });
        await page.waitForLoadState("networkidle").catch(() => {});

        const receiptLink = await findReceiptLink(page);
        if (!receiptLink) {
          status = "no_receipt";
          noReceipt += 1;
        } else {
          const href = await receiptLink.getAttribute("href");
          receiptUrl = href ? (href.startsWith("/") ? new URL(href, page.url()).toString() : href) : null;
          if (!receiptUrl) {
            await receiptLink.click().catch(() => {});
            await page.waitForLoadState("domcontentloaded").catch(() => {});
            await page.waitForTimeout(250);
            receiptUrl = page.url();
          }

          const ymd = order.order_date || `${year}-??-??`;
          const total = order.total_yen ?? "unknown";
          const fileName = `${safeFilePart(ymd)}_amazon_${safeFilePart(order.order_id)}_${safeFilePart(total)}.pdf`;
          pdfPath = path.join(outPdfsDir, fileName);
          if (pdfContext === context) {
            await saveReceiptPdf(page, pdfPath);
          } else {
            const pdfPage = await pdfContext.newPage();
            try {
              await pdfPage.goto(receiptUrl, { waitUntil: "domcontentloaded" });
              await pdfPage.waitForLoadState("networkidle").catch(() => {});
              await saveReceiptPdf(pdfPage, pdfPath);
            } finally {
              await pdfPage.close().catch(() => {});
            }
          }
          pdfSaved += 1;
        }
      } catch (e) {
        status = "error";
        if (debugDir) await writeDebug(page, debugDir, `order_${safeFilePart(order.order_id)}_error`);
      }

      lines.push(
        JSON.stringify({
          order_id: order.order_id,
          order_date: order.order_date,
          total_yen: order.total_yen,
          detail_url: order.detail_url,
          receipt_url: receiptUrl,
          pdf_path: pdfPath,
          status,
        })
      );
    }

    fs.writeFileSync(outJsonl, lines.join("\n") + (lines.length ? "\n" : ""), "utf-8");
    console.log(
      JSON.stringify({
        status: "success",
        data: { orders_total: allOrders.length, pdf_saved: pdfSaved, no_receipt: noReceipt, out_jsonl: outJsonl, out_pdfs_dir: outPdfsDir },
      })
    );
  } catch (e) {
    if (debugDir) await writeDebug(page, debugDir, "fatal");
    throw e;
  } finally {
    await context.close().catch(() => {});
    if (pdfContext !== context) await pdfContext.close().catch(() => {});
    await browser.close().catch(() => {});
    if (pdfBrowser !== browser) await pdfBrowser.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});

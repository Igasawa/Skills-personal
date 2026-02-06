#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";
import { ensureDir, locatorVisible, parseArgs, safeFilePart, writeDebug } from "./mjs_common.mjs";

function yenToInt(s) {
  if (s == null) return null;
  const normalized = String(s)
    .replace(/[０-９]/g, (d) => String.fromCharCode(d.charCodeAt(0) - 0xfee0))
    .replace(/[，,]/g, "")
    .replace(/[円\s]/g, "")
    .replace(/[¥￥]/g, "");
  const m = normalized.match(/-?\d+/);
  return m ? Number.parseInt(m[0], 10) : null;
}

function normalizeOrderText(s) {
  return String(s)
    .replace(/[０-９]/g, (d) => String.fromCharCode(d.charCodeAt(0) - 0xfee0))
    .replace(/[，,]/g, ",")
    .replace(/[￥¥]/g, "円")
    .replace(/[／]/g, "/")
    .replace(/[－–—]/g, "-")
    .replace(/[（]/g, "(")
    .replace(/[）]/g, ")")
    .replace(/[\u200B-\u200D\uFEFF]/g, "");
}

function parseJapaneseDate(s, fallbackYear) {
  if (!s) return null;
  const t = normalizeOrderText(s).trim();
  let m = t.match(/(\d{4})[/-](\d{1,2})[/-](\d{1,2})/);
  if (m) return { y: +m[1], m: +m[2], d: +m[3] };
  m = t.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);
  if (m) return { y: +m[1], m: +m[2], d: +m[3] };
  m = t.match(/(\d{1,2})月(\d{1,2})日/);
  if (m && fallbackYear) return { y: +fallbackYear, m: +m[1], d: +m[2] };
  return null;
}

function extractTotalFromText(text) {
  if (!text) return null;
  const t = normalizeOrderText(text);
  const patterns = [
    /合計\s*[:：]?\s*([0-9,]+)\s*円/,
    /ご請求額\s*[:：]?\s*([0-9,]+)\s*円/,
    /注文合計\s*[:：]?\s*([0-9,]+)\s*円/,
    /合計金額\s*[:：]?\s*([0-9,]+)\s*円/,
  ];
  for (const p of patterns) {
    const m = t.match(p);
    if (m) return yenToInt(m[1]);
  }
  const all = [...t.matchAll(/([0-9][0-9,]*)\s*円/g)];
  if (all.length) return yenToInt(all[all.length - 1][1]);
  return null;
}

async function extractTotalFromPage(page) {
  const text = await page.innerText("body").catch(() => "");
  return extractTotalFromText(text);
}

async function extractItemNamesFromDom(page) {
  const selectors = [
    "a[href*='/dp/']",
    "a[href*='/gp/product/']",
    ".item-view-left-col-inner a",
    ".a-unordered-list.a-vertical.a-spacing-mini span",
  ];
  const blacklist = [
    "注文",
    "返品",
    "返品手続き",
    "領収書",
    "請求",
    "配送",
    "ヘルプ",
    "お問い合わせ",
    "アカウント",
    "お届け",
    "詳細",
    "支払い",
    "ギフト",
  ];
  const out = [];
  const seen = new Set();

  for (const selector of selectors) {
    let texts = [];
    try {
      texts = await page.locator(selector).allTextContents();
    } catch {
      texts = [];
    }
    for (const raw of texts) {
      const t = normalizeOrderText(raw).replace(/\s+/g, " ").trim();
      if (!t) continue;
      if (t.length < 3 || t.length > 120) continue;
      const lower = t.toLowerCase();
      if (lower.includes("order") || lower.includes("invoice") || lower.includes("help")) continue;
      if (blacklist.some((b) => t.includes(b))) continue;
      if (seen.has(t)) continue;
      seen.add(t);
      out.push(t);
      if (out.length >= 3) break;
    }
    if (out.length >= 3) break;
  }

  return out.length ? out.join(" / ") : null;
}

async function extractItemNamesFromCard(card) {
  const selectors = [
    "a.a-link-normal",
    "a[href*='/dp/']",
    "a[href*='/gp/product/']",
    ".a-unordered-list.a-vertical.a-spacing-mini span",
    "span.a-size-base",
  ];
  const blacklist = [
    "注文",
    "返品",
    "返品手続き",
    "領収書",
    "請求",
    "配送",
    "ヘルプ",
    "お問い合わせ",
    "アカウント",
    "お届け",
    "詳細",
    "支払い",
    "ギフト",
    "注文内容を表示",
  ];
  const out = [];
  const seen = new Set();
  for (const selector of selectors) {
    let texts = [];
    try {
      texts = await card.locator(selector).allTextContents();
    } catch {
      texts = [];
    }
    for (const raw of texts) {
      const t = normalizeOrderText(raw).replace(/\s+/g, " ").trim();
      if (!t) continue;
      if (t.length < 3 || t.length > 120) continue;
      const lower = t.toLowerCase();
      if (lower.includes("order") || lower.includes("invoice") || lower.includes("help")) continue;
      if (blacklist.some((b) => t.includes(b))) continue;
      if (seen.has(t)) continue;
      seen.add(t);
      out.push(t);
      if (out.length >= 2) break;
    }
    if (out.length >= 2) break;
  }
  return out.length ? out.join(" / ") : null;
}


function isAmazonLoginUrl(url) {
  return /\/ap\/signin|signin|login/i.test(url || "");
}

async function isAmazonLoginPage(page) {
  const url = page.url();
  if (isAmazonLoginUrl(url)) return true;
  const email = page.locator("input#ap_email, input[type='email']");
  if (await locatorVisible(email)) return true;
  const password = page.locator("input#ap_password, input[type='password']");
  if (await locatorVisible(password)) return true;
  const signIn = page.locator("input#signInSubmit, button", { hasText: /sign in|signin|sign-in/i });
  if (await locatorVisible(signIn)) return true;
  return false;
}



async function waitForUserAuth(page, label) {
  console.error(`[AUTH_REQUIRED] ${label}`);
  await page.bringToFront().catch(() => {});
  const timeoutMs = 15 * 60 * 1000;
  const start = Date.now();
  let entered = false;
  if (process.stdin && process.stdin.isTTY) {
    console.error("Please complete login in the browser. (auto-continue enabled, Enter optional)");
    process.stdin.resume();
    process.stdin.once("data", () => {
      entered = true;
    });
  }
  while (Date.now() - start < timeoutMs) {
    if (entered) return;
    await page.waitForTimeout(1000);
    if (!(await isAmazonLoginPage(page))) {
      return;
    }
  }
  throw new Error(`AUTH_REQUIRED: ${label} (timeout waiting for manual login)`);
}


async function ensureAuthenticated(page, authHandoff, label) {
  if (!(await isAmazonLoginPage(page))) return;
  if (!authHandoff) {
    throw new Error(`AUTH_REQUIRED: ${label} (storage_state expired)`);
  }
  await waitForUserAuth(page, label);
  await page.waitForLoadState("networkidle").catch(() => {});
  if (await isAmazonLoginPage(page)) {
    throw new Error(`AUTH_REQUIRED: ${label} (still on login page)`);
  }
}

async function findReceiptNameInput(page) {
  const byLabel = page.getByLabel("宛名", { exact: false });
  if ((await byLabel.count()) > 0) return byLabel.first();
  const byPlaceholder = page.locator("input[placeholder*='宛名'], textarea[placeholder*='宛名']");
  if ((await byPlaceholder.count()) > 0) return byPlaceholder.first();
  const byName = page.locator(
    "input[name*='name' i], input[id*='name' i], input[name*='recipient' i], input[id*='recipient' i], input[name*='invoice' i], input[id*='invoice' i]"
  );
  if ((await byName.count()) > 0) return byName.first();
  const label = page.locator("text=宛名").first();
  if ((await label.count()) > 0) {
    const container = label.locator("xpath=ancestor::*[self::div or self::section or self::td][1]");
    const input = container.locator("input,textarea");
    if ((await input.count()) > 0) return input.first();
  }
  return null;
}

async function applyReceiptName(page, receiptName) {
  const name = (receiptName || "").trim();
  if (!name) return false;

  const label = page.locator("text=宛名").first();
  if ((await label.count()) > 0) {
    const container = label.locator("xpath=ancestor::*[self::div or self::section or self::td][1]");
    const edit = container.locator("a,button", { hasText: /変更|編集|入力|追加/ }).first();
    if ((await edit.count()) > 0) {
      await edit.click().catch(() => {});
      await page.waitForTimeout(200);
    }
  }

  const input = await findReceiptNameInput(page);
  if (!input) return false;

  try {
    await input.fill(name);
  } catch {
    return false;
  }

  const save = page.locator("button, input[type='submit'], a", { hasText: /保存|更新|適用|登録/ }).first();
  if ((await save.count()) > 0) {
    await save.click().catch(() => {});
    await page.waitForTimeout(200);
  }
  return true;
}

async function applyReceiptNameWithFallback(page, primary, fallback) {
  if (await applyReceiptName(page, primary)) {
    return { applied: true, name: (primary || "").trim() };
  }
  if (fallback && (await applyReceiptName(page, fallback))) {
    return { applied: true, name: (fallback || "").trim() };
  }
  return { applied: false, name: null };
}

async function readReceiptNameValue(page) {
  const input = await findReceiptNameInput(page);
  if (!input) return null;
  try {
    const v = await input.inputValue();
    return v ? String(v).trim() : null;
  } catch {
    return null;
  }
}

async function promptUserReceiptName(page) {
  if (!process.stdin || !process.stdin.isTTY) return false;
  console.error("[ACTION_REQUIRED] 領収書の宛名が自動入力できませんでした。手動で設定してEnterを押してください。");
  await page.bringToFront().catch(() => {});
  await new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once("data", () => resolve());
  });
  return true;
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
  let orderCards = page.locator(".order-card, .js-order-card");
  let n = await orderCards.count();
  if (n === 0) {
    orderCards = page.locator("div").filter({ hasText: "注文番号" });
    n = await orderCards.count();
  }
  const orders = [];

  for (let i = 0; i < n; i++) {
    const card = orderCards.nth(i);
    const cardText = await card.innerText().catch(() => "");
    const cardTextNorm = normalizeOrderText(cardText);

    const idMatch = cardTextNorm.match(/注文番号\s*[:：]?\s*([0-9-]{10,})/);
    const orderId = idMatch ? idMatch[1] : null;

    const dateMatch =
      cardTextNorm.match(/注文日\s*[:：]?\s*([0-9/年月日()]+)/) ||
      cardTextNorm.match(/注文日\s*([0-9/年月日()]+)/) ||
      cardTextNorm.match(/(\d{4}[/-]\d{1,2}[/-]\d{1,2})/);
    const dateParts = dateMatch ? parseJapaneseDate(dateMatch[1], year) : null;
    const orderDate = dateParts
      ? `${String(dateParts.y).padStart(4, "0")}-${String(dateParts.m).padStart(2, "0")}-${String(dateParts.d).padStart(2, "0")}`
      : null;

    if (!orderDate) continue;
    const m = Number.parseInt(orderDate.slice(5, 7), 10);
    if (m !== targetMonth) continue;

    const totalMatch =
      cardTextNorm.match(/合計\s*[:：]?\s*([0-9,]+)\s*円/) ||
      cardTextNorm.match(/注文合計\s*[:：]?\s*([0-9,]+)\s*円/) ||
      cardTextNorm.match(/合計\s*([0-9,]+)\s*円/);
    const totalYen = totalMatch ? yenToInt(totalMatch[1]) : null;
    const itemName = await extractItemNamesFromCard(card);

    let detailUrl = null;
    const detailLink = card.locator("a[href*='order-details'], a", { hasText: "注文内容を表示" }).first();
    if ((await detailLink.count()) > 0) detailUrl = await detailLink.getAttribute("href");
    if (detailUrl && detailUrl.startsWith("/")) {
      detailUrl = new URL(detailUrl, page.url()).toString();
    }

    orders.push({
      order_id: orderId,
      order_date: orderDate,
      total_yen: totalYen,
      detail_url: detailUrl,
      item_name: itemName,
    });
  }

  return orders;
}

async function extractDetailLinks(page) {
  const links = page.locator("a[href*='order-details'], a[href*='orderID=']");
  const n = await links.count();
  const out = [];
  const seen = new Set();
  for (let i = 0; i < n; i++) {
    const href = await links.nth(i).getAttribute("href");
    if (!href) continue;
    const url = href.startsWith("/") ? new URL(href, page.url()).toString() : href;
    let parsed = null;
    try {
      parsed = new URL(url);
    } catch {
      continue;
    }
    if (!parsed.pathname.includes("/your-orders/order-details")) continue;
    const orderId = parsed.searchParams.get("orderID");
    if (!orderId || !/^\d{3}-\d{7}-\d{7}$/.test(orderId)) continue;
    const normalized = parsed.toString();
    if (seen.has(normalized)) continue;
    seen.add(normalized);
    out.push(normalized);
  }
  return out;
}

function isGiftCardOrder(textRaw) {
  const text = String(textRaw || "");
  const lower = text.toLowerCase();
  const jpTerms = [
    "Amazonギフト券",
    "ギフト券",
    "ギフトカード",
  ];
  const enTerms = ["amazon gift card", "gift card"];
  const jpContextTerms = [
    "注文商品",
    "注文内容",
    "商品名",
    "明細",
    "注文の詳細",
  ];
  const enContextTerms = ["order", "item", "order details"];

  const hasContext = (near, terms) => terms.some((t) => near.includes(t));

  for (const term of jpTerms) {
    const idx = text.indexOf(term);
    if (idx >= 0) {
      const startIdx = Math.max(0, idx - 200);
      const endIdx = Math.min(text.length, idx + 200);
      const near = text.slice(startIdx, endIdx);
      if (hasContext(near, jpContextTerms)) return true;
    }
  }

  for (const term of enTerms) {
    const idx = lower.indexOf(term);
    if (idx >= 0) {
      const startIdx = Math.max(0, idx - 200);
      const endIdx = Math.min(lower.length, idx + 200);
      const near = lower.slice(startIdx, endIdx);
      if (hasContext(near, enContextTerms)) return true;
    }
  }

  return false;
}

async function parseOrderDetail(page, fallbackYear) {
  const textRaw = await page.innerText("body").catch(() => "");
  const text = normalizeOrderText(textRaw);
  const idMatch = text.match(/注文番号\s*[:：]?\s*([0-9-]{10,})/);
  const orderId = idMatch ? idMatch[1] : null;

  const dateMatch = text.match(/注文日\s*[:：]?\s*([^\n]+)/) || text.match(/注文日\s*([^\n]+)/);
  const dateParts = dateMatch ? parseJapaneseDate(dateMatch[1], fallbackYear) : null;
  const orderDate = dateParts
    ? `${String(dateParts.y).padStart(4, "0")}-${String(dateParts.m).padStart(2, "0")}-${String(dateParts.d).padStart(2, "0")}`
    : null;

  const totalYen = extractTotalFromText(text);
  const itemName = await extractItemNamesFromDom(page);

  const isGiftCard = isGiftCardOrder(textRaw);

  return { orderId, orderDate, totalYen, itemName, isGiftCard };
}

async function findReceiptLink(page) {
  const labels = ["領収書", "領収書/購入明細", "購入明細書", "領収書等", "Invoice", "Receipt"];
  for (const label of labels) {
    const a = page.locator("a", { hasText: label }).first();
    if ((await a.count()) > 0) return a;
  }
  return null;
}

async function findPopoverReceiptUrl(page, receiptLink) {
  let popover = null;
  if (receiptLink) {
    popover = await receiptLink.getAttribute("data-a-popover");
    if (!popover) {
      const ancestor = receiptLink.locator("xpath=ancestor-or-self::*[@data-a-popover]").first();
      if ((await ancestor.count()) > 0) popover = await ancestor.getAttribute("data-a-popover");
    }
  }
  if (!popover) {
    const anyPopover = page.locator("[data-a-popover*='invoice'], [data-a-popover*='Invoice']");
    if ((await anyPopover.count()) > 0) popover = await anyPopover.first().getAttribute("data-a-popover");
  }
  if (!popover) return null;
  try {
    const parsed = JSON.parse(popover);
    if (parsed && parsed.url) return parsed.url;
  } catch {
    return null;
  }
  return null;
}

async function saveReceiptPdf(page, outPdfPath) {
  await page.emulateMedia({ media: "print" });
  await page.pdf({ path: outPdfPath, format: "A4", printBackground: true });
}

function assessAmazonReceiptPageText(textRaw) {
  const text = normalizeOrderText(textRaw).replace(/\s+/g, " ").trim();
  const lower = text.toLowerCase();
  if (!text || text.length < 20) {
    return { ok: false, reason: "amazon_receipt_page_empty_or_too_short" };
  }
  const wrongPageKeywords = [
    "ご迷惑をおかけしています",
    "処理中にエラーが発生",
    "Amazon.co.jp ホームへ",
    "注文商品のキャンセル",
    "個数変更・キャンセル",
    "an error has occurred",
  ];
  for (const keyword of wrongPageKeywords) {
    if (text.includes(keyword) || lower.includes(String(keyword).toLowerCase())) {
      return { ok: false, reason: `amazon_receipt_invalid_page:${keyword}` };
    }
  }
  return { ok: true, reason: null };
}

async function assertAmazonReceiptPage(page) {
  const bodyText = await page.innerText("body").catch(() => "");
  const checked = assessAmazonReceiptPageText(bodyText);
  if (!checked.ok) {
    throw new Error(checked.reason || "amazon_receipt_invalid_page");
  }
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
  const receiptName = args["receipt-name"] ? String(args["receipt-name"]) : process.env.RECEIPT_NAME || "";
  const receiptNameFallback = args["receipt-name-fallback"]
    ? String(args["receipt-name-fallback"])
    : process.env.RECEIPT_NAME_FALLBACK || "";
  const skipReceiptName = Boolean(args["skip-receipt-name"]);
  const authHandoff = Boolean(args["auth-handoff"]);

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
  const navTimeoutMs = Number.parseInt(process.env.PW_NAV_TIMEOUT_MS || "45000", 10);
  page.setDefaultTimeout(navTimeoutMs);
  page.setDefaultNavigationTimeout(navTimeoutMs);
  console.log("[amazon] open orders page");

  let allOrders = [];
  try {
    await page.goto(ordersUrl, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});
    await ensureAuthenticated(page, authHandoff, "Amazon orders page");
    console.log("[amazon] authenticated");

    await trySelectYear(page, year);
    await page.waitForSelector(".order-card, .js-order-card", { timeout: 15000 }).catch(() => {});

    const seenOrderIds = new Set();
    const seenDetailUrls = new Set();
    for (let pageNo = 1; pageNo <= 50; pageNo++) {
      await page.waitForTimeout(300);
      const orders = await extractOrdersFromPage(page, year, month);
      const detailLinks = await extractDetailLinks(page);

      if (pageNo === 1 && orders.length === 0 && detailLinks.length === 0 && debugDir) {
        await writeDebug(page, debugDir, "orders_page_empty");
      }

      for (const o of orders) {
        if (!seenOrderIds.has(o.order_id)) {
          seenOrderIds.add(o.order_id);
          allOrders.push(o);
          if (o.detail_url) seenDetailUrls.add(o.detail_url);
        }
      }

      for (const url of detailLinks) {
        if (!seenDetailUrls.has(url)) {
          seenDetailUrls.add(url);
          allOrders.push({ order_id: null, order_date: null, total_yen: null, detail_url: url });
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
    let debugDetailSaved = false;
    let pdfSaved = 0;
    let noReceipt = 0;

    console.log(`[amazon] total orders to process: ${allOrders.length}`);
    for (let i = 0; i < allOrders.length; i++) {
      const order = allOrders[i];
      console.log(`[amazon] processing ${i + 1}/${allOrders.length}`);
      let status = "ok";
      let receiptUrl = null;
      let pdfPath = null;
      let errorReason = null;

      try {
        if (!order.detail_url) throw new Error("missing detail_url");
        await page.goto(order.detail_url, { waitUntil: "domcontentloaded" });
        await page.waitForLoadState("networkidle").catch(() => {});
        await ensureAuthenticated(page, authHandoff, "Amazon order detail");

        const parsed = await parseOrderDetail(page, year);
        if (!order.order_id || !order.order_date || order.total_yen == null) {
          order.order_id = order.order_id || parsed.orderId;
          order.order_date = order.order_date || parsed.orderDate;
          if (order.total_yen == null && parsed.totalYen != null) order.total_yen = parsed.totalYen;
          if (!order.item_name && parsed.itemName) order.item_name = parsed.itemName;
        }

        if (order.order_date) {
          const m = Number.parseInt(order.order_date.slice(5, 7), 10);
          if (m !== month) {
            status = "out_of_month";
            lines.push(
              JSON.stringify({
                order_id: order.order_id,
                order_date: order.order_date,
                total_yen: order.total_yen,
                item_name: order.item_name || null,
                receipt_name: receiptName || null,
                receipt_name_applied: false,
                source: "amazon",
                detail_url: order.detail_url,
                receipt_url: null,
                pdf_path: null,
                status,
              })
            );
            continue;
          }
        } else {
          status = "unknown_date";
          lines.push(
            JSON.stringify({
              order_id: order.order_id,
              order_date: order.order_date,
              total_yen: order.total_yen,
              receipt_name: receiptName || null,
              receipt_name_applied: false,
              source: "amazon",
              detail_url: order.detail_url,
              receipt_url: null,
              pdf_path: null,
              status,
            })
          );
          continue;
        }

        if (parsed.isGiftCard) {
          status = "gift_card";
          lines.push(
            JSON.stringify({
              order_id: order.order_id,
              order_date: order.order_date,
              total_yen: order.total_yen,
              receipt_name: receiptName || null,
              receipt_name_applied: false,
              source: "amazon",
              detail_url: order.detail_url,
              receipt_url: null,
              pdf_path: null,
              status,
              include: false,
              gift_card: true,
            })
          );
          continue;
        }

        const receiptLink = await findReceiptLink(page);
        if (!receiptLink) {
          status = "no_receipt";
          noReceipt += 1;
        } else {
          let href = await receiptLink.getAttribute("href");
          if (href && href.startsWith("javascript")) href = null;
          const popoverUrl = await findPopoverReceiptUrl(page, receiptLink);
          const chosen = href || popoverUrl;
          receiptUrl = chosen ? (chosen.startsWith("/") ? new URL(chosen, page.url()).toString() : chosen) : null;
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
            await page.goto(receiptUrl, { waitUntil: "domcontentloaded" });
            await page.waitForLoadState("networkidle").catch(() => {});
            await ensureAuthenticated(page, authHandoff, "Amazon receipt page");
            await assertAmazonReceiptPage(page);
            if (order.total_yen == null) {
              const t = await extractTotalFromPage(page);
              if (t != null) order.total_yen = t;
            }
            let nameResult = { applied: false, name: null };
            if (!skipReceiptName) {
              const input = await findReceiptNameInput(page);
              if (input) {
                nameResult = await applyReceiptNameWithFallback(page, receiptName, receiptNameFallback);
              }
            }
            if (nameResult.applied) order.receipt_name = nameResult.name;
            order.receipt_name_applied = Boolean(nameResult.applied);
            await assertAmazonReceiptPage(page);
            await saveReceiptPdf(page, pdfPath);
          } else {
            const pdfPage = await pdfContext.newPage();
            pdfPage.setDefaultTimeout(navTimeoutMs);
            pdfPage.setDefaultNavigationTimeout(navTimeoutMs);
            try {
              await pdfPage.goto(receiptUrl, { waitUntil: "domcontentloaded" });
              await pdfPage.waitForLoadState("networkidle").catch(() => {});
              await ensureAuthenticated(pdfPage, authHandoff, "Amazon receipt page");
              await assertAmazonReceiptPage(pdfPage);
              if (order.total_yen == null) {
                const t = await extractTotalFromPage(pdfPage);
                if (t != null) order.total_yen = t;
              }
              let nameResult = { applied: false, name: null };
              if (!skipReceiptName) {
                const input = await findReceiptNameInput(pdfPage);
                if (input) {
                  nameResult = await applyReceiptNameWithFallback(pdfPage, receiptName, receiptNameFallback);
                }
              }
              if (nameResult.applied) order.receipt_name = nameResult.name;
              order.receipt_name_applied = Boolean(nameResult.applied);
              await assertAmazonReceiptPage(pdfPage);
              await saveReceiptPdf(pdfPage, pdfPath);
            } finally {
              await pdfPage.close().catch(() => {});
            }
          }
          pdfSaved += 1;
        }
      } catch (e) {
        status = "error";
        errorReason = String(e?.message || e);
        console.error(`[amazon] order ${order.order_id || "unknown"} error: ${errorReason}`);
        if (debugDir) await writeDebug(page, debugDir, `order_${safeFilePart(order.order_id)}_error`);
      }

      if (debugDir && !debugDetailSaved && order.total_yen == null) {
        await writeDebug(page, debugDir, `order_${safeFilePart(order.order_id || "unknown")}_detail`);
        debugDetailSaved = true;
      }

      lines.push(
        JSON.stringify({
          order_id: order.order_id,
          order_date: order.order_date,
          total_yen: order.total_yen,
          item_name: order.item_name || null,
          receipt_name: order.receipt_name || receiptName || null,
          receipt_name_applied: Boolean(order.receipt_name_applied),
          source: "amazon",
          detail_url: order.detail_url,
          receipt_url: receiptUrl,
          pdf_path: pdfPath,
          status,
          error_reason: errorReason,
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

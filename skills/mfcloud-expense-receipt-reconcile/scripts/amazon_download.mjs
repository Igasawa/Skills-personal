#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
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

const AMAZON_ORDER_ID_FULL_REGEX = /^[A-Za-z0-9]{3}-\d{7}-\d{7}$/i;
const AMAZON_ORDER_ID_REGEX = /\b[A-Za-z0-9]{3}-\d{7}-\d{7}\b/i;
const AMAZON_ORDER_DATE_LABELS = ["注文日", "サブスクリプション課金日", "課金日"];

function toYmd(dateParts) {
  if (!dateParts) return null;
  return `${String(dateParts.y).padStart(4, "0")}-${String(dateParts.m).padStart(2, "0")}-${String(dateParts.d).padStart(2, "0")}`;
}

function extractOrderDateFromText(textRaw, fallbackYear) {
  const text = normalizeOrderText(textRaw);
  for (const label of AMAZON_ORDER_DATE_LABELS) {
    const escaped = String(label || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    if (!escaped) continue;
    const labeledMatch =
      text.match(new RegExp(`${escaped}\\s*[:：]?\\s*([^\\n]+)`)) ||
      text.match(new RegExp(`${escaped}\\s*([0-9/年月日()]+)`));
    const dateParts = labeledMatch ? parseJapaneseDate(labeledMatch[1], fallbackYear) : null;
    if (dateParts) return toYmd(dateParts);
  }
  const fallbackMatch = text.match(/(\d{4}[/-]\d{1,2}[/-]\d{1,2})/);
  const fallbackParts = fallbackMatch ? parseJapaneseDate(fallbackMatch[1], fallbackYear) : null;
  return toYmd(fallbackParts);
}

function extractTotalFromText(text) {
  if (!text) return null;
  const totals = extractSummaryTotalsFromText(text);
  if (totals.billingTotalYen != null) return totals.billingTotalYen;
  if (totals.orderTotalYen != null) return totals.orderTotalYen;
  if (totals.totalAmountYen != null) return totals.totalAmountYen;

  const t = normalizeOrderText(text);
  const all = [
    ...t.matchAll(/(?:[¥￥円]\s*)?([0-9][0-9,]*)\s*円/g),
    ...t.matchAll(/(?:[¥￥円]\s*)+([0-9][0-9,]*)/g),
  ];
  if (all.length) {
    const last = all[all.length - 1];
    if (last && last[1]) return yenToInt(last[1]);
  }
  return null;
}

function extractLabeledAmount(text, labels) {
  if (!text || !Array.isArray(labels) || !labels.length) return null;
  const t = normalizeOrderText(text);
  for (const label of labels) {
    const escaped = String(label || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    if (!escaped) continue;
    const patterns = [
      new RegExp(`${escaped}\\s*[:：]?\\s*(?:[¥￥円]\\s*)?([0-9][0-9,]*)`, "m"),
      new RegExp(`${escaped}\\s*[:：]?\\s*([0-9][0-9,]*)\\s*(?:円)?`, "m"),
    ];
    for (const pattern of patterns) {
      const m = t.match(pattern);
      if (m && m[1]) {
        const parsed = yenToInt(m[1]);
        if (parsed != null) return parsed;
      }
    }
  }
  return null;
}

function extractSummaryTotalsFromText(text) {
  const billingTotalYen = extractLabeledAmount(text, ["ご請求額", "請求額"]);
  const orderTotalYen = extractLabeledAmount(text, ["注文合計", "お支払い金額", "支払金額"]);
  const totalAmountYen = extractLabeledAmount(text, ["合計金額", "合計"]);
  return { billingTotalYen, orderTotalYen, totalAmountYen };
}

function chooseAmazonOrderTotal({
  billingTotalYen = null,
  summaryTotalYen = null,
  invoiceTotalSumYen = null,
  fallbackTotalYen = null,
} = {}) {
  if (billingTotalYen != null) {
    return { totalYen: billingTotalYen, totalSource: "billing_total" };
  }
  if (summaryTotalYen != null) {
    return { totalYen: summaryTotalYen, totalSource: "summary_total" };
  }
  if (invoiceTotalSumYen != null) {
    return { totalYen: invoiceTotalSumYen, totalSource: "invoice_sum" };
  }
  if (fallbackTotalYen != null) {
    return { totalYen: fallbackTotalYen, totalSource: "card_fallback" };
  }
  return { totalYen: null, totalSource: "unknown" };
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

async function extractOrderFromCard(card, pageUrl, year) {
  const cardText = await card.innerText().catch(() => "");
  const cardTextNorm = normalizeOrderText(cardText);

  const orderId = extractOrderIdFromText(cardTextNorm);
  const orderDate = extractOrderDateFromText(cardTextNorm, year);

  const totalMatch =
    cardTextNorm.match(/合計\s*[:：]?\s*(?:[¥￥円]\s*)?([0-9,]+)\s*(?:円)?/) ||
    cardTextNorm.match(/注文合計\s*[:：]?\s*(?:[¥￥円]\s*)?([0-9,]+)\s*(?:円)?/) ||
    cardTextNorm.match(/合計\s*(?:[¥￥円]\s*)?([0-9,]+)\s*(?:円)?/);
  const totalYen = totalMatch ? yenToInt(totalMatch[1]) : null;
  const itemName = await extractItemNamesFromCard(card);

  let detailUrl = null;
  const detailLink = card.locator("a[href*='order-details'], a", { hasText: "注文内容を表示" }).first();
  if ((await detailLink.count()) > 0) detailUrl = await detailLink.getAttribute("href");
  if (detailUrl) {
    detailUrl = toAbsoluteUrl(detailUrl, pageUrl);
  }
  const orderIdFromUrl = extractOrderIdFromUrl(detailUrl);

  return {
    order_id: orderId || orderIdFromUrl,
    order_date: orderDate,
    total_yen: totalYen,
    detail_url: detailUrl,
    item_name: itemName,
    payment_method: extractAmazonPaymentMethodFromText(cardText),
    card_text: cardText,
  };
}

function normalizeAmazonPaymentMethodText(rawText) {
  return normalizeTextForMatch(rawText).replace(/[\s._()\-\/]/g, "");
}

function extractAmazonPaymentMethodFromText(textRaw) {
  const raw = String(textRaw || "").replace(/\r/g, "\n");
  const patterns = [
    /お支払い方法\s*[:：]?\s*([^\n\r]+)/i,
    /お支払方法\s*[:：]?\s*([^\n\r]+)/i,
    /支払い方法\s*[:：]?\s*([^\n\r]+)/i,
    /決済方法\s*[:：]?\s*([^\n\r]+)/i,
    /payment\s*method\s*[:：]?\s*([^\n\r]+)/i,
  ];

  for (const pattern of patterns) {
    const match = raw.match(pattern);
    if (match && match[1]) {
      const captured = String(match[1]).trim();
      if (captured) return captured;
    }
  }
  return null;
}

function isAmazonNoReceiptPaymentMethod(paymentMethodRaw) {
  const normalized = normalizeAmazonPaymentMethodText(paymentMethodRaw);
  if (!normalized) return false;
  const noReceiptSignals = [
    "代金引換",
    "代引き",
    "cod",
    "cashondelivery",
    "cash-on-delivery",
    "c.o.d",
    "collectondelivery",
  ];
  return noReceiptSignals.some((signal) => normalized.includes(signal));
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

function deriveAmazonDocumentType({ documents = [], docType = null, status = null } = {}) {
  if (status === "no_receipt") return "no_receipt";
  if (status === "gift_card") return null;

  const kinds = Array.isArray(documents)
    ? documents.map((d) => (d && typeof d.doc_type === "string" ? d.doc_type : null)).filter(Boolean)
    : [];

  if (kinds.includes("tax_invoice")) return "invoice";
  if (
    kinds.includes("order_summary") ||
    kinds.includes("receipt_like") ||
    docType === "order_summary" ||
    docType === "receipt_like"
  ) {
    return "receipt";
  }
  if (docType === "tax_invoice") return "invoice";
  return null;
}

async function parseOrderDetail(page, fallbackYear) {
  const textRaw = await page.innerText("body").catch(() => "");
  const text = normalizeOrderText(textRaw);
  const orderId = extractOrderIdFromText(text);
  const orderDate = extractOrderDateFromText(text, fallbackYear);

  const summaryTotals = extractSummaryTotalsFromText(text);
  const totalYen =
    summaryTotals.billingTotalYen ?? summaryTotals.orderTotalYen ?? summaryTotals.totalAmountYen ?? extractTotalFromText(text);
  const itemName = await extractItemNamesFromDom(page);
  const paymentMethod = extractAmazonPaymentMethodFromText(textRaw);

  const isGiftCard = isGiftCardOrder(textRaw);

  return {
    orderId,
    orderDate,
    totalYen,
    billingTotalYen: summaryTotals.billingTotalYen,
    summaryTotalYen: summaryTotals.orderTotalYen ?? summaryTotals.totalAmountYen,
    itemName,
    paymentMethod,
    isGiftCard,
  };
}

async function findReceiptLink(page) {
  const labels = ["領収書", "領収書/購入明細", "購入明細書", "領収書等", "Invoice", "Receipt"];
  for (const label of labels) {
    const a = page.locator("a", { hasText: label }).first();
    if ((await a.count()) > 0) return a;
  }
  return null;
}

async function findReceiptLinkInCard(card) {
  const invoiceSelectors = [
    "a[href*='/your-orders/invoice/popover']",
    "a[href*='ref_=fed_invoice_ajax']",
    "[data-a-popover*='/your-orders/invoice/popover']",
    "[data-a-popover*='fed_invoice_ajax']",
    "[data-a-popover*='fed_digi_order_invoice_ajax']",
  ];
  for (const selector of invoiceSelectors) {
    const candidate = card.locator(selector).first();
    if ((await candidate.count()) > 0) return candidate;
  }

  const labels = ["領収書等", "領収書", "購入明細書", "Invoice", "Receipt"];
  for (const label of labels) {
    const clickable = card.locator("a,button", { hasText: label }).first();
    if ((await clickable.count()) > 0) return clickable;
  }
  const popoverHost = card.locator("[data-a-popover], [data-action*='a-popover']").first();
  if ((await popoverHost.count()) > 0) return popoverHost;
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
  if (!popover) return null;
  try {
    const parsed = JSON.parse(popover);
    if (parsed && parsed.url) return parsed.url;
  } catch {
    return null;
  }
  return null;
}

function fileLooksLikePdf(filePath) {
  if (!filePath) return false;
  try {
    if (!fs.existsSync(filePath)) return false;
    const fd = fs.openSync(filePath, "r");
    try {
      const header = Buffer.alloc(5);
      const size = fs.fstatSync(fd).size;
      if (size < 5) return false;
      fs.readSync(fd, header, 0, 5, 0);
      return header.toString("utf-8") === "%PDF-";
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    return false;
  }
}

function extractOrderIdFromText(textRaw) {
  const text = normalizeOrderText(textRaw);
  const m = text.match(AMAZON_ORDER_ID_REGEX);
  return m ? m[0] : null;
}

function extractOrderIdFromUrl(rawUrl) {
  if (!rawUrl) return null;
  try {
    const u = new URL(String(rawUrl));
    const byQuery = u.searchParams.get("orderID") || u.searchParams.get("orderId");
    if (byQuery && AMAZON_ORDER_ID_FULL_REGEX.test(byQuery.trim())) return byQuery.trim();
    const byPath = u.pathname.match(AMAZON_ORDER_ID_REGEX);
    if (byPath) return byPath[0];
    return null;
  } catch {
    const byText = normalizeOrderText(rawUrl).match(AMAZON_ORDER_ID_REGEX);
    return byText ? byText[0] : null;
  }
}

function toAbsoluteUrl(rawUrl, baseUrl) {
  if (!rawUrl) return null;
  try {
    return new URL(rawUrl, baseUrl || undefined).toString();
  } catch {
    return null;
  }
}

function looksLikeAmazonReceiptUrl(rawUrl) {
  if (!rawUrl) return false;
  let u = null;
  try {
    u = new URL(rawUrl);
  } catch {
    return false;
  }
  const joined = `${u.pathname}${u.search}`.toLowerCase();
  if (joined.includes("/your-orders/order-details")) return false;
  if (joined.includes("/invoice/popover")) return false;
  if (joined.includes("fed_invoice_ajax")) return false;
  if (joined.includes("/gcx/-/ty/gr/")) return false;
  if (joined.includes("gift_receipt")) return false;
  const positiveMarkers = [
    "invoice",
    "receipt",
    "summary/print",
    "print.html",
    "order-summary",
    "tax",
    "document",
  ];
  return positiveMarkers.some((marker) => joined.includes(marker));
}

function isDirectAmazonPdfUrl(rawUrl) {
  if (!rawUrl) return false;
  try {
    const u = new URL(String(rawUrl));
    const pathLower = String(u.pathname || "").toLowerCase();
    if (pathLower.endsWith(".pdf")) return true;
    if (pathLower.includes("/documents/download/")) return true;
    return false;
  } catch {
    return false;
  }
}

function normalizeTextForMatch(value) {
  return String(value || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function containsAny(text, markers) {
  return markers.some((marker) => text.includes(String(marker).toLowerCase()));
}

function classifyAmazonDocumentCandidate(rawUrl, rawText) {
  const url = toAbsoluteUrl(rawUrl, undefined);
  if (!url) return null;
  const text = normalizeTextForMatch(rawText);
  const urlLower = normalizeTextForMatch(url);

  if (urlLower.includes("/your-orders/order-details")) return null;
  if (urlLower.includes("/invoice/popover")) return null;
  if (urlLower.includes("fed_invoice_ajax")) return null;
  if (urlLower.includes("/gcx/-/ty/gr/")) return null;
  if (urlLower.includes("gift_receipt")) return null;

  const taxTextMarkers = [
    "\u9069\u683c\u8acb\u6c42\u66f8",
    "tax invoice",
    "qualified invoice",
    "invoice",
  ];
  const taxUrlMarkers = ["tax", "invoice", "billing", "document"];

  const summaryTextMarkers = [
    "\u5370\u5237\u53ef\u80fd\u306a\u6ce8\u6587\u6982\u8981",
    "\u6ce8\u6587\u6982\u8981",
    "printable order summary",
    "order summary",
    "print summary",
  ];
  const summaryUrlMarkers = ["order-summary", "summary/print", "print.html", "print"];

  const taxTextHit = containsAny(text, taxTextMarkers);
  const taxUrlHit = containsAny(urlLower, taxUrlMarkers);
  const summaryTextHit = containsAny(text, summaryTextMarkers);
  const summaryUrlHit = containsAny(urlLower, summaryUrlMarkers);

  if (taxTextHit || (taxUrlHit && !summaryUrlHit)) {
    return { kind: "tax_invoice", score: (taxTextHit ? 300 : 200) + (taxUrlHit ? 20 : 0), url };
  }
  if (summaryTextHit || summaryUrlHit) {
    return { kind: "order_summary", score: (summaryTextHit ? 220 : 140) + (summaryUrlHit ? 20 : 0), url };
  }
  if (looksLikeAmazonReceiptUrl(url)) {
    return { kind: "receipt_like", score: 80, url };
  }
  return null;
}

async function collectAmazonDocumentCandidates(page) {
  const out = [];
  const seen = new Set();
  const currentUrl = page.url();
  const currentTitle = await page.title().catch(() => "");
  const currentCandidate = classifyAmazonDocumentCandidate(currentUrl, currentTitle);
  if (currentCandidate) {
    out.push(currentCandidate);
    seen.add(currentCandidate.url);
  }

  const focusedAnchors = page.locator(
    ".invoice-list a[href], a[href*='/documents/download/'], a[href*='/summary/print'], a[href*='order-summary']"
  );
  const focusedCount = Math.min(await focusedAnchors.count().catch(() => 0), 240);
  for (let i = 0; i < focusedCount; i++) {
    const a = focusedAnchors.nth(i);
    const href = await a.getAttribute("href").catch(() => null);
    const text = await a.innerText().catch(() => "");
    const abs = toAbsoluteUrl(href, currentUrl);
    const candidate = classifyAmazonDocumentCandidate(abs, text);
    if (!candidate) continue;
    if (seen.has(candidate.url)) continue;
    seen.add(candidate.url);
    out.push(candidate);
  }

  const anchors = page.locator("a[href]");
  const n = Math.min(await anchors.count().catch(() => 0), 400);
  for (let i = 0; i < n; i++) {
    const a = anchors.nth(i);
    const href = await a.getAttribute("href").catch(() => null);
    const text = await a.innerText().catch(() => "");
    const abs = toAbsoluteUrl(href, currentUrl);
    const candidate = classifyAmazonDocumentCandidate(abs, text);
    if (!candidate) continue;
    if (seen.has(candidate.url)) continue;
    seen.add(candidate.url);
    out.push(candidate);
  }
  return out;
}

function buildAmazonDocumentPlan(candidates, fallbackUrl = null) {
  const normalized = [];
  const seenUrls = new Set();

  const pushCandidate = (raw) => {
    if (!raw || typeof raw !== "object") return;
    const url = toAbsoluteUrl(raw.url, undefined);
    if (!url || seenUrls.has(url)) return;
    seenUrls.add(url);
    normalized.push({
      kind: raw.kind || "receipt_like",
      score: Number(raw.score || 0),
      url,
    });
  };

  for (const c of candidates || []) {
    pushCandidate(c);
  }
  if (fallbackUrl) {
    pushCandidate(classifyAmazonDocumentCandidate(fallbackUrl, ""));
  }

  if (!normalized.length) return [];

  const bestByKind = new Map();
  for (const c of normalized) {
    const prev = bestByKind.get(c.kind);
    if (!prev || c.score > prev.score) {
      bestByKind.set(c.kind, c);
    }
  }

  const out = [];
  const summary = bestByKind.get("order_summary");
  const taxInvoice = bestByKind.get("tax_invoice");
  const receiptLike = bestByKind.get("receipt_like");

  if (summary) out.push(summary);
  if (taxInvoice && (!summary || taxInvoice.url !== summary.url)) out.push(taxInvoice);
  if (!summary && !taxInvoice && receiptLike) out.push(receiptLike);

  if (!out.length) {
    const bestOverall = normalized.sort((a, b) => b.score - a.score)[0];
    if (bestOverall) out.push(bestOverall);
  }
  return out;
}

async function resolvePreferredAmazonDocumentPage(page, fallbackUrl, options = {}) {
  const navigate = options.navigate !== false;
  const currentUrl = page.url() || fallbackUrl || "";
  const candidates = await collectAmazonDocumentCandidates(page);
  const plan = buildAmazonDocumentPlan(candidates, fallbackUrl);

  const best = plan.length ? plan[0] : null;
  if (!best || !best.url) {
    return { kind: "none", url: currentUrl };
  }

  if (navigate && best.url !== currentUrl) {
    await page.goto(best.url, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});
  }
  return { kind: best.kind, url: navigate ? page.url() || best.url : best.url };
}

async function resolveReceiptSource(context, page, receiptLink) {
  const baseUrl = page.url();

  let href = await receiptLink.getAttribute("href");
  if (href && href.startsWith("javascript")) href = null;
  const popoverUrl = await findPopoverReceiptUrl(page, receiptLink);
  const hrefAbs = toAbsoluteUrl(href, baseUrl);
  const popoverAbs = toAbsoluteUrl(popoverUrl, baseUrl);
  const directCandidates = [hrefAbs, popoverAbs]
    .map((u) => classifyAmazonDocumentCandidate(u, ""))
    .filter(Boolean);
  const directPlan = buildAmazonDocumentPlan(directCandidates, null);
  const directUrl = directPlan.length ? directPlan[0].url : null;
  if (directUrl) {
    return { receiptUrl: directUrl, popupPage: null, download: null, documentPlan: directPlan };
  }

  const popupPromise = page.waitForEvent("popup", { timeout: 2500 }).catch(() => null);
  const downloadPromise = context.waitForEvent("download", { timeout: 2500 }).catch(() => null);

  await receiptLink.click().catch(() => {});
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  await page.waitForTimeout(300);

  const [popupPage, download] = await Promise.all([popupPromise, downloadPromise]);

  let receiptUrl = null;
  let documentPlan = [];
  const afterUrl = page.url();
  if (afterUrl !== baseUrl && looksLikeAmazonReceiptUrl(afterUrl)) {
    receiptUrl = afterUrl;
  }
  if (!receiptUrl && popupPage) {
    await popupPage.waitForLoadState("domcontentloaded").catch(() => {});
    const popupUrl = popupPage.url();
    if (looksLikeAmazonReceiptUrl(popupUrl)) {
      receiptUrl = popupUrl;
    }
  }

  if (!receiptUrl) {
    const popoverAnchors = page.locator(".a-popover[aria-hidden='false'] a[href], .a-popover:not([aria-hidden='true']) a[href]");
    const popoverCount = Math.min(await popoverAnchors.count().catch(() => 0), 24);
    const popoverCandidates = [];
    for (let i = 0; i < popoverCount; i++) {
      const a = popoverAnchors.nth(i);
      const href2 = await a.getAttribute("href").catch(() => null);
      const text2 = await a.innerText().catch(() => "");
      const abs2 = toAbsoluteUrl(href2, afterUrl || baseUrl);
      const candidate = classifyAmazonDocumentCandidate(abs2, text2);
      if (candidate) popoverCandidates.push(candidate);
    }
    const planned = buildAmazonDocumentPlan(popoverCandidates, null);
    if (planned.length) {
      documentPlan = planned;
      receiptUrl = planned[0].url;
    }
  }

  if (!documentPlan.length && receiptUrl) {
    const fallbackCandidate = classifyAmazonDocumentCandidate(receiptUrl, "");
    documentPlan = buildAmazonDocumentPlan(fallbackCandidate ? [fallbackCandidate] : [], receiptUrl);
  }

  return { receiptUrl, popupPage, download, documentPlan };
}

const AMAZON_HEAD_ONLY_STYLE_ID = "ax-amazon-head-only-style";
const AMAZON_HEAD_ONLY_HIDDEN_ATTR = "data-ax-head-hidden";
const AMAZON_HEAD_ONLY_PDF_ENABLED = false;
const AMAZON_RECEIPT_DETAIL_MARKERS = [
  "お届け済み",
  "お届け予定",
  "購入明細",
  "注文情報",
  "注文内容",
];

function detectAmazonReceiptCutoffFromBlocks(blocks, markers = AMAZON_RECEIPT_DETAIL_MARKERS) {
  if (!Array.isArray(blocks) || !Array.isArray(markers) || !markers.length) return null;
  const normalizedMarkers = markers
    .map((m) => normalizeOrderText(m).replace(/\s+/g, "").trim())
    .filter(Boolean);
  if (!normalizedMarkers.length) return null;

  let cutoff = null;
  for (const block of blocks) {
    if (!block || typeof block !== "object") continue;
    const top = Number(block.top);
    if (!Number.isFinite(top) || top <= 0) continue;
    const textNorm = normalizeOrderText(block.text || "").replace(/\s+/g, "").trim();
    if (!textNorm) continue;
    if (!normalizedMarkers.some((needle) => textNorm.includes(needle))) continue;
    if (cutoff == null || top < cutoff) {
      cutoff = top;
    }
  }
  return cutoff == null ? null : Math.max(0, Math.floor(cutoff));
}

async function detectAmazonReceiptCutoff(page, markers = AMAZON_RECEIPT_DETAIL_MARKERS) {
  const markerList = Array.isArray(markers) ? markers : AMAZON_RECEIPT_DETAIL_MARKERS;
  const blocks = await page.evaluate((needleKeywords) => {
    const needles = Array.isArray(needleKeywords) ? needleKeywords : [];
    if (!needles.length || !document || !document.body) return [];

    const out = [];
    const nodes = document.querySelectorAll("h1, h2, h3, h4, h5, section, div, p, li, span");
    for (const node of nodes) {
      if (!(node instanceof HTMLElement)) continue;
      const text = (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
      if (!text || text.length > 160) continue;
      if (!needles.some((needle) => text.includes(needle))) continue;
      const rect = node.getBoundingClientRect();
      if (!rect || rect.width <= 0 || rect.height <= 0) continue;
      if (rect.bottom <= 0) continue;
      out.push({ text: text.slice(0, 160), top: rect.top });
    }
    return out;
  }, markerList);
  return detectAmazonReceiptCutoffFromBlocks(blocks, markerList);
}

async function applyAmazonHeadOnlyMask(page, cutoffY) {
  return page.evaluate(
    ({ cutoff, styleId, hiddenAttr }) => {
      if (!Number.isFinite(cutoff) || !document || !document.body) {
        return { applied: false, hiddenCount: 0 };
      }

      let style = document.getElementById(styleId);
      if (!style) {
        style = document.createElement("style");
        style.id = styleId;
        style.textContent = `@media print {
  [${hiddenAttr}="1"] { display: none !important; visibility: hidden !important; }
}`;
        document.head.appendChild(style);
      }

      const hidden = [];
      for (const node of document.body.querySelectorAll("*")) {
        if (!(node instanceof HTMLElement)) continue;
        node.removeAttribute(hiddenAttr);
      }

      for (const node of document.body.querySelectorAll("*")) {
        if (!(node instanceof HTMLElement)) continue;
        if (node.id === styleId) continue;
        const rect = node.getBoundingClientRect();
        if (!rect || rect.width <= 0 || rect.height <= 0) continue;
        if (rect.top >= cutoff - 1) {
          node.setAttribute(hiddenAttr, "1");
          hidden.push(node);
        }
      }
      return { applied: hidden.length > 0, hiddenCount: hidden.length };
    },
    { cutoff: cutoffY, styleId: AMAZON_HEAD_ONLY_STYLE_ID, hiddenAttr: AMAZON_HEAD_ONLY_HIDDEN_ATTR }
  );
}

async function clearAmazonHeadOnlyMask(page) {
  return page.evaluate(
    ({ styleId, hiddenAttr }) => {
      const style = document.getElementById(styleId);
      if (style) style.remove();
      for (const node of document.querySelectorAll(`[${hiddenAttr}="1"]`)) {
        if (node instanceof HTMLElement) node.removeAttribute(hiddenAttr);
      }
      return true;
    },
    { styleId: AMAZON_HEAD_ONLY_STYLE_ID, hiddenAttr: AMAZON_HEAD_ONLY_HIDDEN_ATTR }
  );
}

async function saveReceiptPdf(page, outPdfPath, options = {}) {
  const headOnly = Boolean(options && options.headOnly);
  let headOnlyApplied = false;
  let cutoffY = null;
  let hiddenCount = 0;
  let maskApplied = false;

  if (headOnly) {
    try {
      cutoffY = await detectAmazonReceiptCutoff(page);
      if (cutoffY == null) {
        console.warn("[amazon] head-only cutoff detection failed; fallback to full-page PDF.");
      } else {
        const masked = await applyAmazonHeadOnlyMask(page, cutoffY);
        hiddenCount = Number(masked && masked.hiddenCount) || 0;
        headOnlyApplied = Boolean(masked && masked.applied);
        maskApplied = headOnlyApplied;
        if (headOnlyApplied) {
          console.log(`[amazon] head-only mask applied cutoffY=${cutoffY} hidden=${hiddenCount}`);
        } else {
          console.warn("[amazon] head-only mask did not hide elements; fallback to full-page PDF.");
        }
      }
    } catch (err) {
      console.warn(`[amazon] head-only mask failed; fallback to full-page PDF. reason=${String(err)}`);
      headOnlyApplied = false;
      maskApplied = false;
      cutoffY = null;
      hiddenCount = 0;
    }
  }

  try {
    await page.emulateMedia({ media: "print" });
    await page.pdf({ path: outPdfPath, format: "A4", printBackground: true });
  } catch (err) {
    if (!headOnly || !maskApplied) {
      throw err;
    }
    console.warn(`[amazon] head-only PDF failed, retrying full-page PDF. reason=${String(err)}`);
    try {
      await clearAmazonHeadOnlyMask(page);
    } catch {
      // ignore mask cleanup failures during fallback
    }
    headOnlyApplied = false;
    maskApplied = false;
    cutoffY = null;
    hiddenCount = 0;
    await page.emulateMedia({ media: "print" });
    await page.pdf({ path: outPdfPath, format: "A4", printBackground: true });
  } finally {
    if (maskApplied) {
      await clearAmazonHeadOnlyMask(page).catch(() => {});
    }
  }

  if (!fileLooksLikePdf(outPdfPath)) {
    throw new Error("amazon_pdf_not_created_or_invalid");
  }
  return { headOnlyApplied, cutoffY, hiddenCount };
}

async function savePdfFromDirectUrl(context, receiptUrl, outPdfPath) {
  if (!isDirectAmazonPdfUrl(receiptUrl)) return false;

  let response = null;
  try {
    response = await context.request.get(receiptUrl, {
      timeout: 30000,
      failOnStatusCode: false,
    });
  } catch {
    response = null;
  }
  if (response && response.ok()) {
    const body = await response.body().catch(() => null);
    if (body && body.length >= 5 && body.subarray(0, 5).toString("utf-8") === "%PDF-") {
      fs.writeFileSync(outPdfPath, body);
      if (!fileLooksLikePdf(outPdfPath)) {
        throw new Error("amazon_downloaded_file_not_pdf");
      }
      return true;
    }
  }

  const tempPage = await context.newPage();
  try {
    const downloadPromise = context.waitForEvent("download", { timeout: 10000 }).catch(() => null);
    await tempPage.goto(receiptUrl, { waitUntil: "domcontentloaded" }).catch(() => {});
    const download = await downloadPromise;
    if (!download) {
      throw new Error("amazon_direct_pdf_download_event_missing");
    }
    await download.saveAs(outPdfPath);
    if (!fileLooksLikePdf(outPdfPath)) {
      throw new Error("amazon_downloaded_file_not_pdf");
    }
    return true;
  } finally {
    await tempPage.close().catch(() => {});
  }
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
  const hasDetailSelector = text.includes("明細書");
  const hasTaxSelector = text.includes("適格請求書");
  const hasSummarySelector = text.includes("印刷可能な注文概要");
  const hasDocumentBody =
    text.includes("注文情報") ||
    text.includes("購入明細") ||
    text.includes("合計") ||
    lower.includes("order information") ||
    lower.includes("order details") ||
    lower.includes("total");
  if ((hasDetailSelector || hasSummarySelector) && hasTaxSelector && !hasDocumentBody) {
    return { ok: false, reason: "amazon_receipt_selection_page" };
  }
  const receiptSignals = ["領収書", "購入明細書", "適格請求書", "印刷可能な注文概要", "Invoice", "Receipt", "Tax Invoice", "Billing"];
  if (!receiptSignals.some((s) => text.includes(s) || lower.includes(String(s).toLowerCase()))) {
    return { ok: false, reason: "amazon_receipt_missing_signal" };
  }
  if (!extractOrderIdFromText(text)) {
    return { ok: false, reason: "amazon_receipt_missing_order_id" };
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

function mergeReceiptMetaIntoOrder(order, parsed) {
  if (!parsed || typeof parsed !== "object") return;
  if (parsed.orderId) {
    if (order.order_id && order.order_id !== parsed.orderId) {
      throw new Error(`amazon_receipt_order_mismatch:${order.order_id}:${parsed.orderId}`);
    }
    order.order_id = parsed.orderId;
  }
  if (parsed.orderDate && !order.order_date) {
    order.order_date = parsed.orderDate;
  }
  if (parsed.totalYen != null) {
    order.total_yen = parsed.totalYen;
  }
  if (parsed.itemName) {
    order.item_name = parsed.itemName;
  }
  if (parsed.paymentMethod) {
    order.payment_method = parsed.paymentMethod;
  }
}

function normalizeAmazonOrderErrorReason(rawError) {
  const msg = String(rawError || "");
  if (!msg) return "unknown_error";
  if (msg.includes("menu_not_found")) return "menu_not_found";
  if (msg.includes("link_not_resolved")) return "link_not_resolved";
  if (msg.includes("Download is starting")) return "save_failed:download_started";
  if (msg.includes("amazon_downloaded_file_not_pdf") || msg.includes("amazon_pdf_not_created_or_invalid")) return "save_failed";
  if (
    msg.includes("amazon_receipt_selection_page") ||
    msg.includes("amazon_receipt_missing_signal") ||
    msg.includes("amazon_receipt_missing_order_id") ||
    msg.includes("amazon_receipt_page_empty_or_too_short") ||
    msg.includes("amazon_receipt_invalid_page")
  ) {
    return `document_validation_failed:${msg}`;
  }
  if (msg.includes("AUTH_REQUIRED")) return "auth_required";
  // Keep error_reason stable for audit; put any raw text into error_detail instead.
  return "unknown_error";
}

function formatElapsedMs(ms) {
  const totalSec = Math.max(0, Math.floor(Number(ms || 0) / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h${String(m).padStart(2, "0")}m${String(s).padStart(2, "0")}s`;
  if (m > 0) return `${m}m${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

function createHeartbeat(label, buildState) {
  const startedAt = Date.now();
  let lastLogAt = 0;
  const interval = setInterval(() => {
    try {
      const state = buildState ? buildState() : {};
      const now = Date.now();
      if (now - lastLogAt < 20000) return;
      lastLogAt = now;
      const elapsed = formatElapsedMs(now - startedAt);
      console.log(
        `[${label}] progress elapsed=${elapsed} ` +
          Object.entries(state)
            .map(([k, v]) => `${k}=${v == null ? "-" : String(v)}`)
            .join(" ")
      );
    } catch {
      // best-effort
    }
  }, 10000);
  interval.unref?.();
  return {
    stop() {
      clearInterval(interval);
    },
    startedAt,
  };
}

function computeCoverageSummary({ monthlyOrdersTotal, pdfSaved, noReceipt, failedOrders }) {
  const total = Number.isFinite(monthlyOrdersTotal) ? monthlyOrdersTotal : 0;
  const saved = Number.isFinite(pdfSaved) ? pdfSaved : 0;
  const coverage = total > 0 ? saved / total : 1;
  return {
    monthly_orders_total: total,
    pdf_saved: saved,
    no_receipt: Number.isFinite(noReceipt) ? noReceipt : 0,
    failed_orders: Array.isArray(failedOrders) ? failedOrders : [],
    failed_orders_count: Array.isArray(failedOrders) ? failedOrders.length : 0,
    coverage,
  };
}

function assertCoverageThreshold(summary, minPdfSuccessRate) {
  const threshold = Number.isFinite(minPdfSuccessRate) ? minPdfSuccessRate : 0.8;
  if (summary.coverage < threshold) {
    const msg = [
      "AMAZON_COVERAGE_THRESHOLD_NOT_MET",
      `coverage=${summary.coverage.toFixed(3)}`,
      `threshold=${threshold.toFixed(3)}`,
      `monthly_orders_total=${summary.monthly_orders_total}`,
      `pdf_saved=${summary.pdf_saved}`,
    ].join(" ");
    throw new Error(msg);
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
  const historyOnlyReceiptFlow = args["history-only-receipt-flow"] !== false;
  const minPdfSuccessRate = Number.parseFloat(args["min-pdf-success-rate"] || "0.8");

  if (!storageState) throw new Error("Missing --storage-state");
  if (!outJsonl) throw new Error("Missing --out-jsonl");
  if (!outPdfsDir) throw new Error("Missing --out-pdfs-dir");
  if (!year || !month) throw new Error("Missing --year/--month");
  if (!Number.isFinite(minPdfSuccessRate) || minPdfSuccessRate < 0 || minPdfSuccessRate > 1) {
    throw new Error("Invalid --min-pdf-success-rate (expected 0.0 to 1.0)");
  }
  if (!historyOnlyReceiptFlow) {
    console.warn("[amazon] detail-page fallback is disabled by policy. history-only flow is always used.");
  }

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

  const outStream = fs.createWriteStream(outJsonl, { flags: "w" });
  const failedOrders = [];
  let monthlyOrdersTotal = 0;
  let pdfSaved = 0;
  let noReceipt = 0;
  let debugDetailSaved = false;
  const seenOrderKeys = new Set();
  let errorCount = 0;
  const current = { orderId: "", stage: "" };
  const heartbeat = createHeartbeat("amazon", () => ({
    in_month: monthlyOrdersTotal,
    pdf_saved: pdfSaved,
    no_receipt: noReceipt,
    errors: errorCount,
    current_order: current.orderId || "-",
    stage: current.stage || "-",
  }));

  try {
    await page.goto(ordersUrl, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});
    await ensureAuthenticated(page, authHandoff, "Amazon orders page");
    console.log("[amazon] authenticated");

    await trySelectYear(page, year);
    await page.waitForSelector(".order-card, .js-order-card", { timeout: 15000 }).catch(() => {});

    for (let pageNo = 1; pageNo <= 50; pageNo++) {
      await page.waitForTimeout(300);
      let orderCards = page.locator(".order-card, .js-order-card");
      let cardCount = await orderCards.count();
      if (cardCount === 0) {
        orderCards = page.locator("div").filter({ hasText: "注文番号" });
        cardCount = await orderCards.count();
      }
      if (pageNo === 1 && cardCount === 0 && debugDir) {
        await writeDebug(page, debugDir, "orders_page_empty");
      }

      for (let cardIndex = 0; cardIndex < cardCount; cardIndex++) {
        orderCards = page.locator(".order-card, .js-order-card");
        if ((await orderCards.count()) === 0) {
          orderCards = page.locator("div").filter({ hasText: "注文番号" });
        }
        const card = orderCards.nth(cardIndex);
        if ((await card.count()) === 0) continue;

        const order = await extractOrderFromCard(card, page.url(), year);
        if (!order.order_date) continue;
        const m = Number.parseInt(order.order_date.slice(5, 7), 10);
        if (m !== month) continue;

        const dedupeKey =
          order.order_id ||
          order.detail_url ||
          `${order.order_date}|${order.total_yen ?? ""}|${order.item_name ?? ""}|${pageNo}|${cardIndex}`;
        if (seenOrderKeys.has(dedupeKey)) continue;
        seenOrderKeys.add(dedupeKey);

        monthlyOrdersTotal += 1;
        if (!order.order_id) {
          order.order_id = extractOrderIdFromUrl(order.detail_url);
        }

        let status = "ok";
        let receiptUrl = null;
        let pdfPath = null;
        let errorReason = null;
        let errorDetail = null;
        order.receipt_name_applied = false;
        let documents = [];
        let docType = null;
        let docTotalYen = null;
        const cardTotalYen = order.total_yen ?? null;
        let orderTotalYen = cardTotalYen;
        let billingTotalYen = null;
        let summaryTotalYen = null;
        let invoiceTotalSumYen = null;
        let totalSource = orderTotalYen != null ? "card_fallback" : "unknown";
        let totalConflict = false;
        let splitInvoice = false;
        let pdfHeadOnlyApplied = false;

        current.orderId = order.order_id || "unknown";
        current.stage = "start";
        console.log(`[amazon] processing order ${monthlyOrdersTotal} id=${current.orderId}`);

        try {
          if (isGiftCardOrder(order.card_text || "")) {
            status = "gift_card";
          } else if (isAmazonNoReceiptPaymentMethod(order.payment_method)) {
            status = "no_receipt";
            noReceipt += 1;
            errorReason = "no_receipt_payment_method";
            errorDetail = `payment_method=${normalizeAmazonPaymentMethodText(order.payment_method)}`;
            console.error(
              `[amazon] order ${order.order_id || "unknown"} no receipt by payment method: ${String(order.payment_method || "")}`
            );
          } else {
            current.stage = "find_receipt_link";
            const receiptLink = await findReceiptLinkInCard(card);
            if (!receiptLink) {
              status = "error";
              errorReason = "menu_not_found";
            } else {
              current.stage = "resolve_receipt_source";
              const source = await resolveReceiptSource(context, page, receiptLink);
              receiptUrl = source.receiptUrl;
              const popupPage = source.popupPage;
              const download = source.download;
              const sourceDocumentPlan = buildAmazonDocumentPlan(source.documentPlan || [], receiptUrl);

              const ymd = order.order_date || `${year}-??-??`;
              const total = order.total_yen ?? "unknown";
              const fileName = `${safeFilePart(ymd)}_amazon_${safeFilePart(order.order_id || "unknown")}_${safeFilePart(total)}.pdf`;
              const plannedPdfPath = path.join(outPdfsDir, fileName);

              try {
                if (download) {
                  current.stage = "save_pdf_from_download";
                  await download.saveAs(plannedPdfPath);
                  if (!fileLooksLikePdf(plannedPdfPath)) {
                    throw new Error("amazon_downloaded_file_not_pdf");
                  }
                  pdfPath = plannedPdfPath;
                  docType = "receipt_like";
                  docTotalYen = orderTotalYen;
                  documents = [
                    {
                      doc_type: docType,
                      doc_url: receiptUrl,
                      pdf_path: plannedPdfPath,
                      total_yen: docTotalYen,
                      pdf_head_only_applied: false,
                      primary: true,
                    },
                  ];
                  pdfSaved += 1;
                } else {
                  if (!receiptUrl) {
                    const preferredFromHistory = await resolvePreferredAmazonDocumentPage(page, null, { navigate: false });
                    if (preferredFromHistory.url && preferredFromHistory.kind !== "none") {
                      receiptUrl = preferredFromHistory.url;
                    }
                  }
                  if (!receiptUrl) {
                    status = "no_receipt";
                    noReceipt += 1;
                    errorReason = "link_not_resolved";
                  } else {
                    const hasNonDirectDoc = sourceDocumentPlan.some((doc) => !isDirectAmazonPdfUrl(doc.url));
                    if (isDirectAmazonPdfUrl(receiptUrl) && !hasNonDirectDoc) {
                      const directPlan = sourceDocumentPlan.length
                        ? sourceDocumentPlan
                        : buildAmazonDocumentPlan([classifyAmazonDocumentCandidate(receiptUrl, "")].filter(Boolean), receiptUrl);
                      for (let directIndex = 0; directIndex < Math.max(1, directPlan.length); directIndex++) {
                        const directDoc = directPlan[directIndex] || { kind: "receipt_like", url: receiptUrl };
                        const directUrl = directDoc.url || receiptUrl;
                        if (!directUrl || !isDirectAmazonPdfUrl(directUrl)) continue;
                        let outPdfPath = plannedPdfPath;
                        if (directIndex > 0) {
                          const parsed = path.parse(plannedPdfPath);
                          const ext = parsed.ext || ".pdf";
                          let suffix = "receipt";
                          if (directDoc.kind === "tax_invoice") suffix = "invoice";
                          else if (directDoc.kind === "order_summary") suffix = "summary";
                          outPdfPath = path.join(parsed.dir, `${parsed.name}_${suffix}_${directIndex + 1}${ext}`);
                        }
                        await savePdfFromDirectUrl(context, directUrl, outPdfPath);
                        documents.push({
                          doc_type: directDoc.kind || "receipt_like",
                          doc_url: directUrl,
                          pdf_path: outPdfPath,
                          total_yen: null,
                          pdf_head_only_applied: false,
                          primary: false,
                        });
                      }
                      if (documents.length) {
                        const summaryDoc = documents.find((d) => d.doc_type === "order_summary") || null;
                        const primaryDoc = summaryDoc || documents[0];
                        for (const d of documents) d.primary = d === primaryDoc;
                        pdfPath = primaryDoc.pdf_path;
                        docType = primaryDoc.doc_type;
                        docTotalYen = null;
                        pdfSaved += 1;
                      } else {
                        status = "no_receipt";
                        noReceipt += 1;
                        errorReason = "link_not_resolved";
                      }
                          } else {
                            const usePopup = Boolean(popupPage && !popupPage.isClosed());
                            const targetPage = usePopup ? popupPage : await pdfContext.newPage();
                            targetPage.setDefaultTimeout(navTimeoutMs);
                            targetPage.setDefaultNavigationTimeout(navTimeoutMs);

                      try {
                        if (!usePopup || targetPage.url() !== receiptUrl) {
                          await targetPage.goto(receiptUrl, { waitUntil: "domcontentloaded" });
                          await targetPage.waitForLoadState("networkidle").catch(() => {});
                        }
                        await ensureAuthenticated(targetPage, authHandoff, "Amazon receipt page");
                        let documentPlan = sourceDocumentPlan;
                        if (!documentPlan.length) {
                          const candidates = await collectAmazonDocumentCandidates(targetPage);
                          documentPlan = buildAmazonDocumentPlan(candidates, receiptUrl);
                        }
                        if (!documentPlan.length && receiptUrl) {
                          documentPlan.push({ kind: "receipt_like", score: 0, url: receiptUrl });
                        }

                            for (let planIndex = 0; planIndex < documentPlan.length; planIndex++) {
                              const doc = documentPlan[planIndex];
                              const docUrl = doc && doc.url ? doc.url : receiptUrl;
                              if (!docUrl) continue;

                          let outPdfPath = plannedPdfPath;
                          if (planIndex > 0) {
                            const parsed = path.parse(plannedPdfPath);
                            const ext = parsed.ext || ".pdf";
                            let suffix = "doc";
                            if (doc.kind === "order_summary") suffix = "summary";
                            else if (doc.kind === "tax_invoice") suffix = "invoice";
                            else if (doc.kind === "receipt_like") suffix = "receipt";
                            outPdfPath = path.join(parsed.dir, `${parsed.name}_${suffix}${ext}`);
                            if (outPdfPath === plannedPdfPath || documents.some((x) => x.pdf_path === outPdfPath)) {
                              outPdfPath = path.join(parsed.dir, `${parsed.name}_${suffix}_${planIndex + 1}${ext}`);
                            }
                          }

                          let currentDocTotal = null;
                          if (isDirectAmazonPdfUrl(docUrl)) {
                            await savePdfFromDirectUrl(context, docUrl, outPdfPath);
                          } else {
                            if (targetPage.url() !== docUrl) {
                              await targetPage.goto(docUrl, { waitUntil: "domcontentloaded" });
                              await targetPage.waitForLoadState("networkidle").catch(() => {});
                            }
                            await ensureAuthenticated(targetPage, authHandoff, "Amazon receipt page");
                            await assertAmazonReceiptPage(targetPage);

                            const parsedReceipt = await parseOrderDetail(targetPage, year);
                            mergeReceiptMetaIntoOrder(order, parsedReceipt);
                            currentDocTotal = parsedReceipt.totalYen;
                            const paymentMethodForSkip =
                              parsedReceipt.paymentMethod || order.payment_method;
                            if (isAmazonNoReceiptPaymentMethod(paymentMethodForSkip)) {
                              status = "no_receipt";
                              noReceipt += 1;
                              errorReason = "no_receipt_payment_method";
                              errorDetail = `payment_method=${normalizeAmazonPaymentMethodText(paymentMethodForSkip)}`;
                              console.error(
                                `[amazon] order ${
                                  order.order_id || "unknown"
                                } no receipt by payment method at detail: ${String(paymentMethodForSkip || "")}`
                              );
                              break;
                            }
                            if (doc.kind === "order_summary") {
                              if (parsedReceipt.billingTotalYen != null) {
                                billingTotalYen = parsedReceipt.billingTotalYen;
                              }
                              if (parsedReceipt.summaryTotalYen != null) {
                                summaryTotalYen = parsedReceipt.summaryTotalYen;
                              }
                            }
                            if (currentDocTotal == null) {
                              currentDocTotal = await extractTotalFromPage(targetPage);
                            }
                            if (doc.kind === "order_summary") {
                              if (summaryTotalYen == null && currentDocTotal != null) {
                                summaryTotalYen = currentDocTotal;
                              }
                              const summaryPreferred = billingTotalYen ?? summaryTotalYen ?? currentDocTotal;
                              if (summaryPreferred != null) {
                                orderTotalYen = summaryPreferred;
                                totalSource = billingTotalYen != null ? "billing_total" : "summary_total";
                              }
                            } else if (orderTotalYen == null && currentDocTotal != null) {
                              orderTotalYen = currentDocTotal;
                              totalSource = "card_fallback";
                            }

                            if (!skipReceiptName && !order.receipt_name_applied) {
                              const input = await findReceiptNameInput(targetPage);
                              if (input) {
                                const nameResult = await applyReceiptNameWithFallback(targetPage, receiptName, receiptNameFallback);
                                if (nameResult.applied) {
                                  order.receipt_name = nameResult.name;
                                }
                                order.receipt_name_applied = Boolean(nameResult.applied);
                              }
                            }

                            await assertAmazonReceiptPage(targetPage);
                            const headOnlyRequested = AMAZON_HEAD_ONLY_PDF_ENABLED && doc.kind === "order_summary";
                            const saveResult = await saveReceiptPdf(targetPage, outPdfPath, {
                              headOnly: headOnlyRequested,
                            });
                            const currentDocHeadOnlyApplied = Boolean(saveResult && saveResult.headOnlyApplied);
                            if (headOnlyRequested && currentDocHeadOnlyApplied) {
                              console.log(
                                `[amazon] order ${order.order_id || "unknown"} doc=${doc.kind || "receipt_like"} head-only saved`
                              );
                            }
                            if (headOnlyRequested && doc.kind === "order_summary" && !currentDocHeadOnlyApplied) {
                              console.warn(
                                `[amazon] order ${order.order_id || "unknown"} doc=order_summary head-only fallback to full-page`
                              );
                            }
                            docType = doc.kind || docType;
                            documents.push({
                              doc_type: doc.kind || "receipt_like",
                              doc_url: docUrl,
                              pdf_path: outPdfPath,
                              total_yen: currentDocTotal,
                              pdf_head_only_applied: currentDocHeadOnlyApplied,
                              primary: false,
                            });
                            continue;
                          }

                          documents.push({
                            doc_type: doc.kind || "receipt_like",
                            doc_url: docUrl,
                            pdf_path: outPdfPath,
                            total_yen: currentDocTotal,
                            pdf_head_only_applied: false,
                            primary: false,
                          });
                        }

                        if (!documents.length) {
                          if (status !== "no_receipt") {
                            status = "no_receipt";
                            noReceipt += 1;
                            errorReason = "link_not_resolved";
                          }
                        } else {
                          const summaryDoc = documents.find((d) => d.doc_type === "order_summary") || null;
                          const primaryDoc = summaryDoc || documents[0];
                          for (const d of documents) {
                            d.primary = d === primaryDoc;
                          }
                          pdfPath = primaryDoc.pdf_path;
                          docType = primaryDoc.doc_type;
                          docTotalYen = primaryDoc.total_yen == null ? null : primaryDoc.total_yen;
                          pdfHeadOnlyApplied = Boolean(primaryDoc.pdf_head_only_applied);
                          const taxInvoiceDocs = documents.filter(
                            (d) => d.doc_type === "tax_invoice" && Number.isFinite(d.total_yen)
                          );
                          const taxInvoiceDocCount = documents.filter((d) => d.doc_type === "tax_invoice").length;
                          if (taxInvoiceDocCount > 0 && taxInvoiceDocs.length === taxInvoiceDocCount) {
                            invoiceTotalSumYen = taxInvoiceDocs.reduce((sum, d) => sum + Number(d.total_yen), 0);
                          } else {
                            invoiceTotalSumYen = null;
                          }

                          const finalTotal = chooseAmazonOrderTotal({
                            billingTotalYen,
                            summaryTotalYen,
                            invoiceTotalSumYen,
                            fallbackTotalYen: orderTotalYen,
                          });
                          orderTotalYen = finalTotal.totalYen;
                          totalSource = finalTotal.totalSource;
                          if (orderTotalYen != null) {
                            order.total_yen = orderTotalYen;
                          }
                          totalConflict = Boolean(
                            billingTotalYen != null && invoiceTotalSumYen != null && billingTotalYen !== invoiceTotalSumYen
                          );
                          splitInvoice =
                            totalConflict ||
                            documents.some(
                              (d) =>
                                d.doc_type === "tax_invoice" &&
                                d.total_yen != null &&
                                order.total_yen != null &&
                                d.total_yen !== order.total_yen
                            );
                          pdfSaved += 1;
                        }
                      } finally {
                        if (!usePopup) {
                          await targetPage.close().catch(() => {});
                        }
                      }
                    }
                  }
                }
              } finally {
                if (popupPage && !popupPage.isClosed()) {
                  await popupPage.close().catch(() => {});
                }
              }
            }
          }
        } catch (e) {
          status = "error";
          const rawMsg = String(e?.message || e || "");
          errorReason = normalizeAmazonOrderErrorReason(rawMsg);
          errorDetail = rawMsg.length > 300 ? `${rawMsg.slice(0, 300)}...` : rawMsg;
          errorCount += 1;
          console.error(`[amazon] order ${order.order_id || "unknown"} error: ${errorReason}`);
          if (debugDir) await writeDebug(page, debugDir, `order_${safeFilePart(order.order_id || "unknown")}_error`);
        }

        if (debugDir && !debugDetailSaved && order.total_yen == null) {
          await writeDebug(page, debugDir, `order_${safeFilePart(order.order_id || "unknown")}_detail`);
          debugDetailSaved = true;
        }

        if (pdfPath && !documents.length) {
          documents = [
            {
              doc_type: docType || "receipt_like",
              doc_url: receiptUrl,
              pdf_path: pdfPath,
              total_yen: docTotalYen,
              pdf_head_only_applied: false,
              primary: true,
            },
          ];
        }
        if (orderTotalYen != null) {
          order.total_yen = orderTotalYen;
        }

        const row = {
          order_id: order.order_id,
          order_date: order.order_date,
          total_yen: order.total_yen,
          order_total_yen: order.total_yen,
          item_name: order.item_name || null,
          payment_method: order.payment_method || null,
          receipt_name: order.receipt_name || receiptName || null,
          receipt_name_applied: Boolean(order.receipt_name_applied),
          source: "amazon",
          detail_url: order.detail_url,
          receipt_url: receiptUrl,
          pdf_path: pdfPath,
          doc_type: docType,
          doc_total_yen: docTotalYen,
          billing_total_yen: billingTotalYen,
          invoice_total_sum_yen: invoiceTotalSumYen,
          total_source: totalSource,
          total_conflict: totalConflict,
          doc_count: documents.length,
          documents,
          pdf_head_only_applied: Boolean(pdfHeadOnlyApplied),
          document_type: deriveAmazonDocumentType({
            documents,
            docType,
            status,
          }),
          split_invoice: splitInvoice,
          status,
          error_reason: errorReason,
          error_detail: errorDetail || null,
          history_only_flow: true,
        };
        if (status === "gift_card") {
          row.include = false;
          row.gift_card = true;
        }
        if (status === "no_receipt") {
          row.include = false;
        }
        outStream.write(JSON.stringify(row) + "\n");

        if (!pdfPath) {
          failedOrders.push({
            order_id: order.order_id || null,
            status,
            error_reason: errorReason || null,
          });
        }
        current.stage = "done";
      }

      const next = page.locator("a", { hasText: "次へ" }).first();
      if ((await next.count()) === 0) break;
      const disabled = await next.getAttribute("aria-disabled");
      if (disabled === "true") break;
      await next.click();
      await page.waitForLoadState("networkidle").catch(() => {});
    }

    // Ensure buffered JSONL is flushed.
    await new Promise((resolve) => {
      outStream.end(() => resolve(true));
    }).catch(() => {});

    const summary = computeCoverageSummary({
      monthlyOrdersTotal,
      pdfSaved,
      noReceipt,
      failedOrders,
    });
    const resultData = {
      ...summary,
      min_pdf_success_rate: minPdfSuccessRate,
      history_only_receipt_flow: true,
      out_jsonl: outJsonl,
      out_pdfs_dir: outPdfsDir,
    };
    if (summary.coverage < minPdfSuccessRate) {
      console.error(JSON.stringify({ status: "failed", data: resultData }));
    }
    assertCoverageThreshold(summary, minPdfSuccessRate);

    console.log(JSON.stringify({ status: "success", data: resultData }));
  } catch (e) {
    if (debugDir) await writeDebug(page, debugDir, "fatal");
    throw e;
  } finally {
    heartbeat.stop();
    try {
      outStream.end();
    } catch {
      // ignore
    }
    await context.close().catch(() => {});
    if (pdfContext !== context) await pdfContext.close().catch(() => {});
    await browser.close().catch(() => {});
    if (pdfBrowser !== browser) await pdfBrowser.close().catch(() => {});
  }
}

export {
  applyAmazonHeadOnlyMask,
  assessAmazonReceiptPageText,
  assertCoverageThreshold,
  buildAmazonDocumentPlan,
  clearAmazonHeadOnlyMask,
  extractAmazonPaymentMethodFromText,
  classifyAmazonDocumentCandidate,
  chooseAmazonOrderTotal,
  isAmazonNoReceiptPaymentMethod,
  normalizeAmazonPaymentMethodText,
  deriveAmazonDocumentType,
  computeCoverageSummary,
  detectAmazonReceiptCutoff,
  detectAmazonReceiptCutoffFromBlocks,
  extractOrderDateFromText,
  extractOrderIdFromText,
  extractTotalFromText,
  extractSummaryTotalsFromText,
  extractOrderIdFromUrl,
  normalizeAmazonOrderErrorReason,
  saveReceiptPdf,
};

const isMainModule = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMainModule) {
  main().catch((err) => {
    console.error(String(err && err.stack ? err.stack : err));
    process.exit(1);
  });
}

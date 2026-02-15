#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";
import { ensureDir, locatorVisible, parseArgs, safeFilePart, writeDebug } from "./mjs_common.mjs";

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
      const now = Date.now();
      if (now - lastLogAt < 20000) return;
      lastLogAt = now;
      const elapsed = formatElapsedMs(now - startedAt);
      const state = buildState ? buildState() : {};
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
  return { stop: () => clearInterval(interval), startedAt };
}

function normalizeRakutenOrderError(rawError) {
  const msg = String(rawError || "").trim();
  if (!msg) return { code: "unknown_error", detail: null };
  // Prefer stable reason codes in error_reason; keep raw detail separately.
  if (msg.includes("AUTH_REQUIRED")) return { code: "auth_required", detail: msg };
  if (msg.includes("net::")) return { code: "network_error", detail: msg };
  if (msg.toLowerCase().includes("timeout")) return { code: "timeout", detail: msg };
  if (msg.startsWith("rakuten_") || msg.startsWith("books_")) return { code: msg, detail: null };
  return { code: "unknown_error", detail: msg };
}

function normalizeText(s) {
  return String(s || "")
    .replace(/[０-９]/g, (d) => String.fromCharCode(d.charCodeAt(0) - 0xfee0))
    .replace(/[，,]/g, ",")
    .replace(/[￥¥]/g, "円")
    .replace(/[／]/g, "/")
    .replace(/[－–—]/g, "-")
    .replace(/[（]/g, "(")
    .replace(/[）]/g, ")")
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeTextLines(s) {
  return String(s || "")
    .replace(/[０-９]/g, (d) => String.fromCharCode(d.charCodeAt(0) - 0xfee0))
    .replace(/[，,]/g, ",")
    .replace(/[￥¥]/g, "円")
    .replace(/[／]/g, "/")
    .replace(/[－–—]/g, "-")
    .replace(/[（]/g, "(")
    .replace(/[）]/g, ")")
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .replace(/\r/g, "");
}

function isLowConfidenceItemName(value) {
  const text = normalizeTextLines(String(value || "")).replace(/\s+/g, " ").trim();
  if (!text) return true;
  if (/^\d{4}[-/]/.test(text)) return true;
  if (/^\d{4}\D+\d{1,2}\D+\d{1,2}/.test(text)) return true;
  if (/^\d{4}.*?\/\s*[￥¥]?\d/.test(text)) return true;
  return false;
}

function extractRakutenBooksItemNameFromText(textRaw) {
  const lines = normalizeTextLines(textRaw)
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  if (!lines.length) return null;

  let headerIndex = lines.findIndex(
    (line) => line.includes("商品コード") && line.includes("商品名") && (line.includes("数量") || line.includes("金額"))
  );
  if (headerIndex < 0) {
    headerIndex = lines.findIndex((line) => line.includes("商品明細"));
  }
  if (headerIndex < 0) return null;

  const stopTokens = ["合計金額", "消費税額", "支払額", "利用明細", "注文番号", "領収書"];
  const names = [];
  const seen = new Set();
  for (const line of lines.slice(headerIndex + 1)) {
    if (stopTokens.some((token) => line.includes(token))) {
      if (names.length) break;
      continue;
    }
    let candidate = line;
    candidate = candidate.replace(/^\d{8,13}\s*/, "");
    candidate = candidate.replace(/\s+\d+\s+[\d,]+(?:円)?\s+[\d,]+(?:円)?$/, "");
    candidate = candidate.replace(/\s+\d+\s+[\d,]+(?:円)?$/, "");
    candidate = candidate.replace(/\s+/g, " ").trim().replace(/^[\-・\s]+|[\-・\s]+$/g, "");
    if (!candidate) continue;
    if (/^[\d,円]+$/.test(candidate)) continue;
    if (seen.has(candidate)) continue;
    seen.add(candidate);
    names.push(candidate);
    if (names.length >= 3) break;
  }
  return names.length ? names.join(" / ") : null;
}

function yenToInt(s) {
  if (s == null) return null;
  const normalized = String(s).replace(/[，,]/g, "").replace(/[円\s]/g, "");
  const m = normalized.match(/-?\d+/);
  return m ? Number.parseInt(m[0], 10) : null;
}

function parseJapaneseDate(s, fallbackYear) {
  if (!s) return null;
  const t = normalizeText(s).trim();
  let m = t.match(/(\d{4})[/-](\d{1,2})[/-](\d{1,2})/);
  if (m) return { y: +m[1], m: +m[2], d: +m[3] };
  m = t.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);
  if (m) return { y: +m[1], m: +m[2], d: +m[3] };
  m = t.match(/(\d{1,2})月(\d{1,2})日/);
  if (m && fallbackYear) return { y: +fallbackYear, m: +m[1], d: +m[2] };
  return null;
}

function extractFieldFromText(text, labels) {
  const t = normalizeTextLines(text);
  const lines = t
    .split(/\n|<br\s*\/?>/i)
    .map((l) => l.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const label of labels) {
      if (label.test(line)) {
        const after = line.replace(label, "").replace(/[:：]/g, "").trim();
        if (after) return after;
        if (i + 1 < lines.length) return lines[i + 1].trim();
      }
    }
  }
  const m = t.match(labels[0]);
  if (m && m[1]) return String(m[1]).trim();
  return null;
}

function extractTotalFromText(text) {
  if (!text) return null;
  const t = normalizeText(text);
  const patterns = [
    /合計\s*[:：]?\s*([0-9,]+)\s*円/,
    /お支払い金額\s*[:：]?\s*([0-9,]+)\s*円/,
    /請求金額\s*[:：]?\s*([0-9,]+)\s*円/,
    /注文合計\s*[:：]?\s*([0-9,]+)\s*円/,
  ];
  for (const p of patterns) {
    const m = t.match(p);
    if (m) return yenToInt(m[1]);
  }
  const all = [...t.matchAll(/([0-9][0-9,]*)\s*円/g)];
  if (all.length) return yenToInt(all[all.length - 1][1]);
  return null;
}

function parseOrderDateFromUrl(url) {
  if (!url) return null;
  const m = String(url).match(/order_number=\d{5,}-([0-9]{8})-/);
  if (!m) return null;
  const y = m[1].slice(0, 4);
  const mo = m[1].slice(4, 6);
  const d = m[1].slice(6, 8);
  return `${y}-${mo}-${d}`;
}

function readExistingProcessed(outJsonl) {
  if (!outJsonl || !fs.existsSync(outJsonl)) return { detailUrls: new Set(), orderIds: new Set() };
  const content = fs.readFileSync(outJsonl, "utf-8");
  const lines = content.split(/\r?\n/).filter((l) => l.trim().length);
  const detailUrls = new Set();
  const orderIds = new Set();
  for (const line of lines) {
    try {
      const obj = JSON.parse(line);
      if (obj.detail_url) detailUrls.add(String(obj.detail_url));
      if (obj.order_id) orderIds.add(String(obj.order_id));
    } catch {
      // ignore
    }
  }
  return { detailUrls, orderIds };
}

function isRakutenLoginUrl(url) {
  return /login|signin|auth|id\.rakuten\.co\.jp/i.test(url || "");
}

async function isRakutenLoginPage(page) {
  const url = page.url();
  if (isRakutenLoginUrl(url)) return true;
  const user = page.locator("input[name='u'], input[name*='user' i], input[type='email']");
  if (await locatorVisible(user)) return true;
  const pass = page.locator("input[type='password']");
  if (await locatorVisible(pass)) return true;
  const signIn = page.locator("button, input[type='submit']", { hasText: /login|signin|sign in/i });
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
    if (!(await isRakutenLoginPage(page))) {
      return;
    }
  }
  throw new Error(`AUTH_REQUIRED: ${label} (timeout waiting for manual login)`);
}


async function ensureAuthenticated(page, authHandoff, label) {
  if (!(await isRakutenLoginPage(page))) return;
  if (!authHandoff) {
    throw new Error(`AUTH_REQUIRED: ${label} (storage_state expired)`);
  }
  await waitForUserAuth(page, label);
  await page.waitForLoadState("networkidle").catch(() => {});
  if (await isRakutenLoginPage(page)) {
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

async function isReceiptNameLocked(page) {
  const lockText = page.locator("text=宛名の変更はできません");
  if ((await lockText.count()) > 0) return true;
  const input = await findReceiptNameInput(page);
  if (!input) return false;
  try {
    const disabled = await input.isDisabled();
    const readonly = await input.getAttribute("readonly");
    if (disabled || readonly != null) return true;
  } catch {
    // ignore
  }
  return false;
}

async function applyReceiptName(page, receiptName) {
  const name = (receiptName || "").trim();
  if (!name) return false;

  if (await isReceiptNameLocked(page)) return false;

  const label = page.locator("text=領収書").first();
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

  let hasExisting = false;
  try {
    const existing = await input.inputValue();
    if (existing && String(existing).trim()) hasExisting = true;
  } catch {
    // ignore
  }

  if (!hasExisting) {
    try {
      const disabled = await input.isDisabled().catch(() => false);
      const readonly = await input.getAttribute("readonly");
      if (disabled || readonly != null) return false;
    } catch {
      // ignore
    }

    try {
      await input.fill(name);
    } catch {
      return false;
    }
  }

  const save = page
    .locator(
      "button, input[type='submit'], input[type='button'], a, input[value*='領収書'], input[value*='発行']",
      { hasText: /保存|更新|適用|登録|発行|領収書/ }
    )
    .first();
  if ((await save.count()) > 0) {
    await save.click().catch(() => {});
    // 楽天の確認カードは networkidle 前に出ることがあるため、先に即時処理する。
    const confirmed = await acceptIssueConfirm(page, 3200);
    if (!confirmed) {
      await page.waitForLoadState("domcontentloaded", { timeout: 1500 }).catch(() => {});
      await acceptIssueConfirm(page, 1200);
    }
    await page.waitForLoadState("networkidle", { timeout: 2500 }).catch(() => {});
  }
  return true;
}


async function applyReceiptNameWithFallback(page, primary, fallback) {
  const existing = await readReceiptNameValue(page);
  if (await isReceiptNameLocked(page)) {
    return { applied: false, name: existing };
  }
  if (existing) {
    return { applied: false, name: existing };
  }
  if (await applyReceiptName(page, primary)) {
    return { applied: true, name: (primary || "").trim() };
  }
  if (fallback && (await applyReceiptName(page, fallback))) {
    return { applied: true, name: (fallback || "").trim() };
  }
  return { applied: false, name: existing };
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

async function saveReceiptPdf(page, outPdfPath) {
  await page.emulateMedia({ media: "print" });
  await page.pdf({ path: outPdfPath, format: "A4", printBackground: true });
}

function isDirectRakutenDownloadUrl(rawUrl) {
  const url = String(rawUrl || "").trim();
  if (!url) return false;
  try {
    const u = new URL(url);
    const lower = `${u.pathname}${u.search}`.toLowerCase();
    if (u.pathname.toLowerCase().endsWith(".pdf")) return true;
    if (lower.includes("act=order_invoice") || lower.includes("act=order_receipt")) return true;
    if (lower.includes("/mypage/delivery/receiptprint")) return true;
    if (lower.includes("receiptdownload") || lower.includes("download")) return true;
    return false;
  } catch {
    return false;
  }
}

function extractDirectDownloadUrlsFromHtml(htmlRaw, baseUrlRaw) {
  const html = String(htmlRaw || "");
  if (!html) return [];

  let baseUrl = String(baseUrlRaw || "").trim();
  try {
    // Validate and normalize base URL once.
    baseUrl = new URL(baseUrl).toString();
  } catch {
    baseUrl = "";
  }

  const candidates = new Set();
  const urlPatterns = [
    /(?:href|src|action)\s*=\s*["']([^"']+)["']/gi,
    /\b(?:window\.open|location\.href|location\.replace)\s*\(\s*["']([^"']+)["']/gi,
    /["']([^"']*(?:receiptdownload|download|\.pdf)[^"']*)["']/gi,
  ];
  for (const re of urlPatterns) {
    let match = null;
    while ((match = re.exec(html)) !== null) {
      const raw = String(match[1] || "").trim();
      if (!raw || raw.startsWith("javascript:") || raw.startsWith("#")) continue;
      if (!isDirectRakutenDownloadUrl(raw) && !/receiptprint/i.test(raw)) continue;
      try {
        const resolved = baseUrl ? new URL(raw, baseUrl).toString() : new URL(raw).toString();
        candidates.add(resolved);
      } catch {
        // ignore invalid candidate URLs
      }
    }
  }
  return [...candidates];
}

async function saveReceiptFromDirectUrl(context, receiptUrl, outPdfPath, timeoutMs, seenUrls = new Set()) {
  if (!isDirectRakutenDownloadUrl(receiptUrl)) return false;
  if (seenUrls.has(receiptUrl)) return false;
  seenUrls.add(receiptUrl);

  let response = null;
  try {
    response = await context.request.get(receiptUrl, {
      timeout: timeoutMs,
      failOnStatusCode: false,
    });
  } catch {
    response = null;
  }
  if (response && response.ok()) {
    const body = await response.body().catch(() => null);
    if (body && body.length >= 4 && body.subarray(0, 4).toString("ascii") === "%PDF") {
      fs.writeFileSync(outPdfPath, body);
      if (!fileLooksLikePdf(outPdfPath)) {
        throw new Error("rakuten_downloaded_file_not_pdf");
      }
      return true;
    }
    const bodyText = body ? body.toString("utf-8") : "";
    const nestedUrls = extractDirectDownloadUrlsFromHtml(bodyText, String(response.url?.() || receiptUrl));
    for (const nestedUrl of nestedUrls) {
      const nestedSaved = await saveReceiptFromDirectUrl(context, nestedUrl, outPdfPath, timeoutMs, seenUrls);
      if (nestedSaved) return true;
    }
  }

  const tempPage = await context.newPage();
  try {
    const downloadPromise = context.waitForEvent("download", { timeout: timeoutMs }).catch(() => null);
    await tempPage.goto(receiptUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
    const dl = await downloadPromise;
    if (!dl) return false;
    await dl.saveAs(outPdfPath);
    if (!fileLooksLikePdf(outPdfPath)) {
      throw new Error("rakuten_downloaded_file_not_pdf");
    }
    return true;
  } finally {
    await tempPage.close().catch(() => {});
  }
}

function assessRakutenReceiptPageText(textRaw) {
  const text = normalizeText(textRaw);
  const lower = text.toLowerCase();
  if (!text || text.length < 20) {
    return { ok: false, reason: "rakuten_receipt_page_empty_or_too_short" };
  }
  const strongReceiptSignals = [
    "楽天ブックス 領収書発行",
    "領収書発行",
    "receiptinputform",
    "receiptprint",
  ];
  if (strongReceiptSignals.some((k) => text.includes(k) || lower.includes(String(k).toLowerCase()))) {
    return { ok: true, reason: null };
  }
  const wrongPageKeywords = [
    "注文商品のキャンセル、数量の変更はできますか",
    "個数変更・キャンセル",
    "キャンセル処理完了",
    "キャンセルする",
  ];
  for (const keyword of wrongPageKeywords) {
    if (text.includes(keyword) || lower.includes(String(keyword).toLowerCase())) {
      return { ok: false, reason: `rakuten_receipt_invalid_page:${keyword}` };
    }
  }
  const receiptSignals = ["領収書", "請求書", "購入明細", "receipt", "invoice"];
  if (!receiptSignals.some((k) => text.includes(k) || lower.includes(String(k).toLowerCase()))) {
    return { ok: false, reason: "rakuten_receipt_page_missing_signal" };
  }
  return { ok: true, reason: null };
}

function normalizedPaymentMethodText(value) {
  return normalizeTextLines(String(value || "")).replace(/\s+/g, " ").trim();
}

function shouldDowngradeRakutenReceiptError(reasonRaw, detailUrlRaw) {
  const reason = String(reasonRaw || "");
  if (!reason) return false;
  const isBooksOrder = /books\.rakuten\.co\.jp/i.test(String(detailUrlRaw || ""));
  if (!isBooksOrder) return false;
  // Keep downgrade narrow for known non-fatal pages only.
  if (reason === "rakuten_receipt_invalid_page:books_status_page") return true;
  // books FAQ indicates the receipt flow is not available for the order.
  if (reason === "rakuten_receipt_invalid_page:books_faq_page") return true;
  if (reason === "rakuten_receipt_page_missing_signal") return true;
  if (reason === "books_receipt_print_not_ready") return true;
  if (reason === "books_receipt_print_timeout") return true;
  return false;
}

function isRakutenNoReceiptPaymentMethod(paymentMethodRaw) {
  const documentType = classifyRakutenReceiptDocumentType(paymentMethodRaw);
  return documentType === "invoice" || documentType === "unsupported";
}

function classifyRakutenReceiptDocumentType(paymentMethodRaw) {
  const normalized = normalizeTextLines(String(paymentMethodRaw || "")).trim();
  if (!normalized) return "receipt";
  const compact = normalized.replace(/[\s._()\-\/]/g, "").toLowerCase();

  // Rakuten payment types that are documented as invoice-first:
  // - 代引き/代金引換
  // - 請求書払い / ショッピングクレジット / ローン系
  // - kobo/ダウンロード商品
  const invoiceSignals = [
    "代引",
    "代金引換",
    "cashondelivery",
    "cod",
    "collectondelivery",
    "請求書払い",
    "請求書",
    "ショッピングクレジット",
    "オートローン",
    "ローン",
    "リース",
    "alipay",
    "kobo",
    "デジタル版",
    "電子版",
    "download",
    "digital",
  ];
  const invoiceSignalsNormalized = invoiceSignals.map((s) => normalizeTextLines(s).replace(/\s+/g, "").toLowerCase());
  if (invoiceSignalsNormalized.some((signal) => compact.includes(signal))) return "invoice";

  return "receipt";
}

function isRakutenBooksReceiptInputUrl(rawUrl) {
  const lower = String(rawUrl || "").toLowerCase();
  return lower.includes("books.rakuten.co.jp/mypage/delivery/receiptinput");
}

function isRakutenBooksReceiptPrintUrl(rawUrl) {
  const lower = String(rawUrl || "").toLowerCase();
  return lower.includes("books.rakuten.co.jp/mypage/delivery/receiptprint");
}

function assessRakutenReceiptContext({ url, title, pageAction, messageCode, requireBooksPrint = false }) {
  const rawUrl = String(url || "");
  const normalizedTitle = normalizeText(title || "");
  const normalizedPageAction = String(pageAction || "").trim().toLowerCase();
  const normalizedMessageCode = String(messageCode || "").trim().toUpperCase();
  const lowerUrl = rawUrl.toLowerCase();

  if (lowerUrl.includes("books.rakuten.co.jp/mypage/delivery/status")) {
    return { ok: false, reason: "rakuten_receipt_invalid_page:books_status_page" };
  }
  if (lowerUrl.includes("books.faq.rakuten.net")) {
    return { ok: false, reason: "rakuten_receipt_invalid_page:books_faq_page" };
  }
  if (isRakutenBooksReceiptPrintUrl(rawUrl)) {
    return { ok: true, reason: null };
  }
  if (isRakutenBooksReceiptInputUrl(rawUrl)) {
    if (requireBooksPrint) {
      return { ok: false, reason: "rakuten_receipt_invalid_page:books_receipt_input_page" };
    }
    return { ok: true, reason: null };
  }

  if (/act=detail_page_view/i.test(rawUrl)) {
    return { ok: false, reason: "rakuten_receipt_invalid_page:detail_page_view_url" };
  }
  if (normalizedPageAction === "detail_page_view") {
    return { ok: false, reason: "rakuten_receipt_invalid_page:detail_page_view_state" };
  }
  if (normalizedTitle.includes("購入履歴詳細")) {
    return { ok: false, reason: "rakuten_receipt_invalid_page:title_purchase_history_detail" };
  }
  if (normalizedMessageCode === "ORDER_INVOICE_DOWNLOAD" && normalizedPageAction === "detail_page_view") {
    return { ok: false, reason: "rakuten_receipt_invalid_page:invoice_download_not_opened" };
  }
  return { ok: true, reason: null };
}

async function assertRakutenReceiptPage(page, options = {}) {
  const requireBooksPrint = Boolean(options && options.requireBooksPrint);
  const pageTitle = await page.title().catch(() => "");
  const pageUrl = page.url();
  const state = await page
    .evaluate(() => {
      const s = window.__INITIAL_STATE__;
      if (!s || typeof s !== "object") return null;
      return {
        pageAction: s.requestParams?.pageAction || "",
        messageCode: s.orderData?.orderReceipt?.messageCode || "",
      };
    })
    .catch(() => null);
  const byContext = assessRakutenReceiptContext({
    url: pageUrl,
    title: pageTitle,
    pageAction: state?.pageAction || "",
    messageCode: state?.messageCode || "",
    requireBooksPrint,
  });
  if (!byContext.ok) {
    throw new Error(byContext.reason || "rakuten_receipt_invalid_page");
  }
  if (requireBooksPrint && isRakutenBooksReceiptInputUrl(pageUrl)) {
    throw new Error("rakuten_receipt_invalid_page:books_receipt_input_page");
  }

  const bodyText = await page.innerText("body").catch(() => "");
  const byText = assessRakutenReceiptPageText(bodyText);
  if (byText.ok) return;

  const booksReceiptLikely = await page
    .evaluate(() => {
      const hasBooksHost = /books\.rakuten\.co\.jp/i.test(window.location.hostname);
      if (!hasBooksHost) return { likely: false, isInput: false, isPrint: false };
      const pathname = String(window.location.pathname || "").toLowerCase();
      const isInput = pathname.includes("/mypage/delivery/receiptinput");
      const isPrint = pathname.includes("/mypage/delivery/receiptprint");
      if (isInput || isPrint) return { likely: true, isInput, isPrint };
      if (document.querySelector("#receiptInputForm")) return { likely: true, isInput: true, isPrint: false };
      if (document.querySelector("#receiptInputFormButton")) return { likely: true, isInput: true, isPrint: false };
      if (document.querySelector("input[name='receiptSubmit']")) return { likely: true, isInput: true, isPrint: false };
      const title = String(document.title || "");
      if (title.includes("領収書")) return { likely: true, isInput: false, isPrint: false };
      return { likely: false, isInput: false, isPrint: false };
    })
    .catch(() => ({ likely: false, isInput: false, isPrint: false }));
  if (booksReceiptLikely.likely) {
    if (requireBooksPrint && booksReceiptLikely.isInput && !booksReceiptLikely.isPrint) {
      throw new Error("rakuten_receipt_invalid_page:books_receipt_input_page");
    }
    return;
  }
  throw new Error(byText.reason || "rakuten_receipt_invalid_page");
}

async function applyRakutenBooksReceiptName(page, primaryName, fallbackName) {
  if (!isRakutenBooksReceiptInputUrl(page.url())) {
    return { applied: false, name: null };
  }
  const input = page.locator("#receiptInputForm input[name='customerName'], input[name='customerName']").first();
  if ((await input.count()) === 0 || !(await input.isVisible().catch(() => false))) {
    return { applied: false, name: null };
  }
  const existing = String(await input.inputValue().catch(() => "")).trim();
  if (existing) {
    return { applied: false, name: existing };
  }
  const target = String(primaryName || "").trim() || String(fallbackName || "").trim();
  if (!target) {
    return { applied: false, name: null };
  }
  try {
    await input.fill(target);
    return { applied: true, name: target };
  } catch {
    return { applied: false, name: null };
  }
}

async function saveRakutenBooksReceiptFromInputViaRequest(
  page,
  outPdfPath,
  timeoutMs = 15000,
  orderId = "unknown",
  stage = ""
) {
  if (!isRakutenBooksReceiptInputUrl(page.url())) return false;

  const formPayload = await page
    .evaluate(() => {
      const form =
        document.querySelector("#receiptInputForm") || document.querySelector("form[action*='receiptPrint']");
      if (!form) return null;
      const action = String(form.getAttribute("action") || "./receiptPrint");
      const method = String(form.getAttribute("method") || "POST").toUpperCase();
      const data = {};
      const fd = new FormData(form);
      for (const [key, value] of fd.entries()) {
        if (typeof value === "string") data[String(key)] = value;
      }
      return { action, method, data };
    })
    .catch(() => null);
  if (!formPayload || formPayload.method !== "POST") return false;

  const actionUrl = new URL(formPayload.action || "./receiptPrint", page.url()).toString();
  let response = null;
  try {
    response = await page.context().request.post(actionUrl, {
      timeout: timeoutMs,
      failOnStatusCode: false,
      headers: { referer: page.url() },
      form: formPayload.data || {},
    });
  } catch {
    response = null;
  }
  if (!response) {
    console.error(`[rakuten] order ${orderId} books direct post request failed stage=${stage} action=${actionUrl}`);
    return false;
  }
  if (!response.ok()) {
    const responseStatus = Number(response.status?.() || 0);
    const responseUrl = String(response.url?.() || actionUrl);
    const responseContentType = String(response.headers?.()["content-type"] || "");
    console.error(
      `[rakuten] order ${orderId} books direct post bad status stage=${stage} status=${responseStatus} content_type=${responseContentType} response_url=${responseUrl}`
    );
    return false;
  }

  const responseStatus = Number(response.status?.() || 0);
  const responseUrl = String(response.url?.() || actionUrl);
  const responseContentType = String(response.headers?.()["content-type"] || "");

  const body = await response.body().catch(() => null);
  if (!body || body.length < 4 || body.subarray(0, 4).toString("ascii") !== "%PDF") {
    const prefixHex = body && body.length > 0 ? body.subarray(0, Math.min(body.length, 16)).toString("hex") : "";
    console.error(
      `[rakuten] order ${orderId} books direct post no pdf stage=${stage} status=${responseStatus} content_type=${responseContentType} response_url=${responseUrl} body_prefix_hex=${prefixHex}`
    );
    return false;
  }
  fs.writeFileSync(outPdfPath, body);
  if (!fileLooksLikePdf(outPdfPath)) {
    return false;
  }
  return true;
}

function assessRakutenBooksReceiptPrintTransition({ url, pathnameHint, title }) {
  const rawUrl = String(url || "");
  if (isRakutenBooksReceiptPrintUrl(rawUrl)) {
    return { ok: true, reason: "books_receipt_print_url" };
  }
  const normalizedPathname = String(pathnameHint || "").toLowerCase();
  if (normalizedPathname.includes("/mypage/delivery/receiptprint")) {
    return { ok: true, reason: "books_receipt_print_pathname" };
  }
  const normalizedTitle = normalizeText(title || "").toLowerCase();
  const hasReceiptTitle = normalizedTitle.includes("receipt") || normalizedTitle.includes("invoice");
  if (!isRakutenBooksReceiptInputUrl(rawUrl) && hasReceiptTitle) {
    return { ok: true, reason: "books_receipt_title_non_input_url" };
  }
  return { ok: false, reason: "books_receipt_print_not_ready" };
}

async function waitForRakutenBooksReceiptPrintTransition(page, timeoutMs = 15000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const currentUrl = page.url();
    const currentTitle = await page.title().catch(() => "");
    const pathnameHint = await page
      .evaluate(() => String(window.location?.pathname || ""))
      .catch(() => "");
    const state = assessRakutenBooksReceiptPrintTransition({
      url: currentUrl,
      pathnameHint,
      title: currentTitle,
    });
    if (state.ok) {
      return { ok: true, reason: state.reason, url: currentUrl };
    }

    await page.waitForLoadState("domcontentloaded", { timeout: 1200 }).catch(() => {});
    await page.waitForLoadState("networkidle", { timeout: 1000 }).catch(() => {});
    await page.waitForTimeout(180);
  }
  return { ok: false, reason: "books_receipt_print_timeout", url: page.url() };
}

async function withSoftTimeout(promise, timeoutMs) {
  return Promise.race([promise, new Promise((resolve) => setTimeout(() => resolve(null), Math.max(0, timeoutMs)))]);
}

async function resolveRakutenBooksPrintCandidatePage(candidatePage, timeoutMs = 9000) {
  if (!candidatePage || candidatePage.isClosed()) {
    return { ok: false, reason: "books_candidate_missing", page: null, url: "" };
  }
  await candidatePage.waitForLoadState("domcontentloaded", { timeout: 6000 }).catch(() => {});
  await candidatePage.waitForLoadState("networkidle", { timeout: 3000 }).catch(() => {});
  const transition = await waitForRakutenBooksReceiptPrintTransition(candidatePage, timeoutMs);
  if (!transition.ok) {
    return { ok: false, reason: transition.reason, page: candidatePage, url: transition.url || candidatePage.url() };
  }
  return { ok: true, reason: transition.reason, page: candidatePage, url: transition.url || candidatePage.url() };
}

async function forceSubmitRakutenBooksReceiptInSameTab(page) {
  return page
    .evaluate(() => {
      const form =
        document.querySelector("#receiptInputForm") || document.querySelector("form[action*='receiptPrint']");
      if (!form) return { ok: false, mode: "missing_form" };
      const previousTarget = String(form.getAttribute("target") || "");
      form.setAttribute("target", "_self");
      if (typeof form.submit === "function") {
        form.submit();
        return { ok: true, mode: "form_submit_self", previousTarget };
      }
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
        return { ok: true, mode: "request_submit_self", previousTarget };
      }
      return { ok: false, mode: "submit_unavailable" };
    })
    .catch(() => ({ ok: false, mode: "submit_eval_error" }));
}

async function openRakutenBooksReceiptPrintPage(page, orderId = "unknown", timeoutMs = 15000) {
  if (isRakutenBooksReceiptPrintUrl(page.url())) {
    return { opened: true, page, download: null, source: "already_print" };
  }
  if (!isRakutenBooksReceiptInputUrl(page.url())) {
    return { opened: false, page, download: null, source: "not_input_page" };
  }
  await page.waitForLoadState("domcontentloaded", { timeout: 5000 }).catch(() => {});

  const inputReady = await page
    .locator("#receiptInputForm, form[action*='receiptPrint'], #receiptInputFormButton, input[name='receiptSubmit']")
    .first()
    .waitFor({ state: "attached", timeout: 7000 })
    .then(() => true)
    .catch(() => false);
  if (!inputReady) {
    console.error(`[rakuten] order ${orderId} books receipt form missing on receiptInput`);
    return { opened: false, page, download: null, source: "input_form_missing" };
  }

  const context = page.context();
  const startedAt = Date.now();
  const popupPromise = page.waitForEvent("popup", { timeout: timeoutMs }).catch(() => null);
  const contextPagePromise = context.waitForEvent("page", { timeout: timeoutMs }).catch(() => null);
  const downloadPromise = context.waitForEvent("download", { timeout: timeoutMs }).catch(() => null);

  const selfSubmit = await forceSubmitRakutenBooksReceiptInSameTab(page);
  if (selfSubmit.ok) {
    const selfTransition = await waitForRakutenBooksReceiptPrintTransition(page, Math.min(15000, timeoutMs));
    if (selfTransition.ok) {
      console.error(
        `[rakuten] order ${orderId} books self-submit mode=${selfSubmit.mode} transition_ok=true reason=${
          selfTransition.reason
        } current=${String(selfTransition.url || page.url())}`
      );
      return { opened: true, page, download: null, source: "same_tab_forced_self" };
    }
    console.error(
      `[rakuten] order ${orderId} books self-submit mode=${selfSubmit.mode} transition_ok=false reason=${selfTransition.reason} current=${String(
        selfTransition.url || page.url()
      )}`
    );
  } else {
    console.error(`[rakuten] order ${orderId} books self-submit skipped mode=${selfSubmit.mode}`);
  }

  let submitResult = { ok: false, mode: "unknown" };
  const submitButton = page.locator("#receiptInputFormButton, input[name='receiptSubmit']").first();
  if ((await submitButton.count()) > 0 && (await submitButton.isVisible().catch(() => false))) {
    try {
      await submitButton.click({ timeout: 8000 });
      submitResult = { ok: true, mode: "locator_click" };
    } catch {
      submitResult = { ok: false, mode: "locator_click_failed" };
    }
  }
  if (!submitResult.ok) {
    submitResult = await page
      .evaluate(() => {
        const submitButton =
          document.querySelector("#receiptInputFormButton") || document.querySelector("input[name='receiptSubmit']");
        const form =
          (submitButton && submitButton.form) ||
          document.querySelector("#receiptInputForm") ||
          document.querySelector("form[action*='receiptPrint']");
        if (submitButton && typeof submitButton.click === "function") {
          submitButton.click();
          return { ok: true, mode: "button_click_eval" };
        }
        if (!form) return { ok: false, mode: "missing_form_after_wait" };
        if (typeof form.requestSubmit === "function") {
          form.requestSubmit();
          return { ok: true, mode: "request_submit" };
        }
        form.submit();
        return { ok: true, mode: "form_submit_fallback" };
      })
      .catch(() => ({ ok: false, mode: "submit_eval_error" }));
  }

  const submitTriggered = Boolean(submitResult && submitResult.ok);
  const submitMode = submitResult?.mode || "unknown";

  const quickTransition = await waitForRakutenBooksReceiptPrintTransition(page, Math.min(9000, timeoutMs));
  if (quickTransition.ok) {
    console.error(
      `[rakuten] order ${orderId} books receipt submit_triggered=${String(submitTriggered)} mode=${submitMode} transition_ok=true reason=${
        quickTransition.reason
      } current=${String(quickTransition.url || page.url())}`
    );
    return { opened: true, page, download: null, source: "same_tab_quick" };
  }

  const earlyPopup = await withSoftTimeout(popupPromise, 2500);
  if (earlyPopup && !earlyPopup.isClosed()) {
    const popupTransition = await resolveRakutenBooksPrintCandidatePage(earlyPopup, Math.min(9000, timeoutMs));
    if (popupTransition.ok && popupTransition.page) {
      console.error(
        `[rakuten] order ${orderId} books receipt submit_triggered=${String(
          submitTriggered
        )} mode=${submitMode} transition_ok=true reason=${popupTransition.reason} popup_current=${String(
          popupTransition.url || popupTransition.page.url()
        )}`
      );
      return { opened: true, page: popupTransition.page, download: null, source: "popup_early" };
    }
    console.error(
      `[rakuten] order ${orderId} books popup transition failed reason=${popupTransition.reason} popup_current=${String(
        popupTransition.url || earlyPopup.url()
      )}`
    );
  }

  const earlyContextPage = await withSoftTimeout(contextPagePromise, 1200);
  if (earlyContextPage && earlyContextPage !== page && !earlyContextPage.isClosed()) {
    const contextTransition = await resolveRakutenBooksPrintCandidatePage(earlyContextPage, Math.min(9000, timeoutMs));
    if (contextTransition.ok && contextTransition.page) {
      console.error(
        `[rakuten] order ${orderId} books receipt context_page transition_ok=true reason=${contextTransition.reason} current=${String(
          contextTransition.url || contextTransition.page.url()
        )}`
      );
      return { opened: true, page: contextTransition.page, download: null, source: "context_page_early" };
    }
  }

  const earlyDownload = await withSoftTimeout(downloadPromise, 1200);
  if (earlyDownload) {
    console.error(`[rakuten] order ${orderId} books receipt captured direct download`);
    return { opened: true, page, download: earlyDownload, source: "download_early" };
  }

  const elapsedMs = Date.now() - startedAt;
  const remainingMs = Math.max(1200, timeoutMs - elapsedMs);
  const transition = await waitForRakutenBooksReceiptPrintTransition(page, remainingMs);
  if (transition.ok) {
    console.error(
      `[rakuten] order ${orderId} books receipt submit_triggered=${String(submitTriggered)} mode=${submitMode} transition_ok=true reason=${
        transition.reason
      } current=${String(transition.url || page.url())}`
    );
    return { opened: true, page, download: null, source: "same_tab_late" };
  }

  const latePopup = earlyPopup || (await withSoftTimeout(popupPromise, 1200));
  if (latePopup && !latePopup.isClosed()) {
    const popupTransition = await resolveRakutenBooksPrintCandidatePage(latePopup, 6000);
    if (popupTransition.ok && popupTransition.page) {
      console.error(
        `[rakuten] order ${orderId} books receipt submit_triggered=${String(
          submitTriggered
        )} mode=${submitMode} transition_ok=true reason=${popupTransition.reason} popup_current=${String(
          popupTransition.url || popupTransition.page.url()
        )}`
      );
      return { opened: true, page: popupTransition.page, download: null, source: "popup_late" };
    }
  }

  const lateContextPage = earlyContextPage || (await withSoftTimeout(contextPagePromise, 1200));
  if (lateContextPage && lateContextPage !== page && !lateContextPage.isClosed()) {
    const contextTransition = await resolveRakutenBooksPrintCandidatePage(lateContextPage, 6000);
    if (contextTransition.ok && contextTransition.page) {
      console.error(
        `[rakuten] order ${orderId} books receipt context_page transition_ok=true reason=${contextTransition.reason} current=${String(
          contextTransition.url || contextTransition.page.url()
        )}`
      );
      return { opened: true, page: contextTransition.page, download: null, source: "context_page_late" };
    }
  }

  const lateDownload = earlyDownload || (await withSoftTimeout(downloadPromise, 1200));
  if (lateDownload) {
    console.error(`[rakuten] order ${orderId} books receipt captured direct download`);
    return { opened: true, page, download: lateDownload, source: "download_late" };
  }

  console.error(
    `[rakuten] order ${orderId} books receipt submit_triggered=${String(submitTriggered)} mode=${submitMode} transition_ok=${String(
      transition.ok
    )} reason=${transition.reason} current=${String(transition.url || page.url())}`
  );
  return { opened: false, page, download: null, source: "transition_timeout" };
}

async function waitForRakutenBooksReceiptInputOrPrint(page, timeoutMs = 15000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const currentUrl = String(page.url() || "");
    if (isRakutenBooksReceiptInputUrl(currentUrl) || isRakutenBooksReceiptPrintUrl(currentUrl)) {
      return { ok: true, url: currentUrl };
    }
    await page.waitForLoadState("domcontentloaded", { timeout: 1200 }).catch(() => {});
    await page.waitForLoadState("networkidle", { timeout: 1000 }).catch(() => {});
    await page.waitForTimeout(160);
  }
  return { ok: false, url: String(page.url() || "") };
}

async function reopenRakutenBooksReceiptFromDetail(
  page,
  detailUrl,
  orderId = "unknown",
  authHandoff = false,
  timeoutMs = 15000
) {
  const targetDetailUrl = String(detailUrl || "").trim();
  if (!targetDetailUrl || !/books\.rakuten\.co\.jp/i.test(targetDetailUrl)) {
    return false;
  }
  console.error(`[rakuten] order ${orderId} books fallback: reopen via detail page`);
  await page.goto(targetDetailUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await ensureAuthenticated(page, authHandoff, "Rakuten books detail page");

  const receiptAction = await findReceiptAction(page);
  if (!receiptAction) {
    console.error(`[rakuten] order ${orderId} books fallback: receipt action not found on detail`);
    return false;
  }

  const baseUrl = page.url();
  const href = await receiptAction.getAttribute("href");
  const onclick = await receiptAction.getAttribute("onclick");
  const actionScript = buildReceiptActionScript(href, onclick);

  await installWindowOpenCapture(page);
  await receiptAction.click().catch(() => {});
  const primaryConfirmed = await acceptIssueConfirm(page, 5000);
  if (!primaryConfirmed && actionScript) {
    const invoked = await invokeReceiptActionScript(page, actionScript);
    console.error(`[rakuten] order ${orderId} books fallback action_script_invoked=${String(invoked)}`);
    if (invoked) {
      await acceptIssueConfirm(page, 3500);
    }
  }

  let transition = await waitForRakutenBooksReceiptInputOrPrint(page, timeoutMs);
  if (transition.ok) return true;

  const captured = await consumeCapturedWindowOpenUrl(page, baseUrl);
  if (captured) {
    await page.goto(captured, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
    await page.waitForLoadState("networkidle", { timeout: 12000 }).catch(() => {});
    transition = await waitForRakutenBooksReceiptInputOrPrint(page, 6000);
    if (transition.ok) return true;
  }

  console.error(
    `[rakuten] order ${orderId} books fallback failed current=${String(page.url() || "")} last=${String(transition.url || "")}`
  );
  return false;
}

const confirmClickGuard = new WeakMap();

async function findIssueConfirmButton(scope) {
  const candidates = [
    scope.locator("button, a", { hasText: /^この宛名で発行します$/ }).first(),
    scope.locator("button, a", { hasText: /^OK$/ }).first(),
    scope.locator("button, a", { hasText: /^はい$/ }).first(),
    scope.locator("button, a", { hasText: /^発行する$/ }).first(),
    scope.locator("button, a", { hasText: /^発行$/ }).first(),
    scope.locator("input[type='button'][value='OK'], input[type='submit'][value='OK']").first(),
    scope.locator("input[type='button'][value='はい'], input[type='submit'][value='はい']").first(),
    scope.locator("input[type='button'][value*='この宛名で発行します'], input[type='submit'][value*='この宛名で発行します']").first(),
    scope.locator("input[type='button'][value*='発行'], input[type='submit'][value*='発行']").first(),
  ];
  for (const locator of candidates) {
    if ((await locator.count()) === 0) continue;
    if (!(await locator.isVisible().catch(() => false))) continue;
    return locator;
  }
  return null;
}

async function acceptIssueConfirm(page, timeoutMs = 1800) {
  const start = Date.now();
  const selectors = ["この宛名で発行します", "宛名の変更はできません", "一度発行したあとは"];
  while (Date.now() - start < timeoutMs) {
    const dialogs = page.locator(
      "[role='dialog'], [aria-modal='true'], .modal, .MuiDialog-root, [class*='popup-container'][class*='show'], [class*='dialog--'][class*='show']"
    );
    const dialogCount = await dialogs.count();
    for (let i = 0; i < dialogCount; i++) {
      const dialog = dialogs.nth(i);
      if (!(await dialog.isVisible().catch(() => false))) continue;
      const dialogText = normalizeText(await dialog.innerText().catch(() => ""));
      const hit = selectors.find((s) => dialogText.includes(s));
      if (!hit) continue;
      const confirmButton = await findIssueConfirmButton(dialog);
      if (!confirmButton) continue;
      const signature = `${page.url()}|dialog|${hit}`;
      const guard = confirmClickGuard.get(page);
      if (guard && guard.signature === signature && Date.now() - guard.at < 900) {
        return true;
      }
      await confirmButton.click().catch(() => {});
      confirmClickGuard.set(page, { signature, at: Date.now() });
      await page.waitForTimeout(120);
      return true;
    }

    for (const text of selectors) {
      const label = page.locator(`text=${text}`).first();
      if ((await label.count()) > 0 && (await label.isVisible().catch(() => false))) {
        const container = label.locator("xpath=ancestor::*[self::div or self::section or self::dialog][1]");
        const confirmButton = await findIssueConfirmButton(container);
        if (confirmButton) {
          const signature = `${page.url()}|${text}`;
          const guard = confirmClickGuard.get(page);
          if (!(guard && guard.signature === signature && Date.now() - guard.at < 900)) {
            await confirmButton.click().catch(() => {});
            confirmClickGuard.set(page, { signature, at: Date.now() });
            await page.waitForTimeout(120);
            return true;
          }
        }
      }
    }

    await page.waitForTimeout(80);
  }
  return false;
}

async function isReceiptIssuePage(page) {
  const candidates = [
    "領収書発行",
    "領収書・請求書",
    "楽天ブックス 領収書発行",
    "宛名",
  ];
  for (const text of candidates) {
    const loc = page.locator(`text=${text}`).first();
    if ((await loc.count()) > 0 && (await loc.isVisible().catch(() => false))) {
      return true;
    }
  }
  const btn = page.locator("button, input[type='submit'], input[type='button'], a", { hasText: /領収書発行|発行/ }).first();
  if ((await btn.count()) > 0 && (await btn.isVisible().catch(() => false))) return true;
  const input = page.locator("input[placeholder*='宛名'], textarea[placeholder*='宛名'], input[name*='name' i]").first();
  if ((await input.count()) > 0 && (await input.isVisible().catch(() => false))) return true;
  return false;
}

async function waitForReceiptUrl(page, baseUrl, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await acceptIssueConfirm(page, 250);
    const url = page.url();
    const normalized = normalizeReceiptUrlCandidate(url, baseUrl);
    if (normalized) return normalized;
    if (url && url !== baseUrl && (await isReceiptIssuePage(page))) return url;
    await page.waitForTimeout(220);
  }
  return null;
}

async function withTimeout(promise, timeoutMs, label) {
  let timeoutId;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error(`TIMEOUT:${label}`)), timeoutMs);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timeoutId);
  }
}

async function extractPaymentMethodFromDom(page) {
  const labelText = "支払い方法";
  const text = await page.evaluate((labelText) => {
    const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
    const candidates = Array.from(
      document.querySelectorAll("dt,th,div,section,td,span,label,strong,p")
    );
    const label = candidates.find((el) => norm(el.textContent) === labelText);
    if (!label) return null;
    const base = label.closest("dt,th,div,section,td") || label;
    const next = base.nextElementSibling;
    let target = next || base;
    let text = norm(target.textContent);
    if (!text || text === labelText) {
      const parent = base.parentElement;
      if (parent) {
        const dd = parent.querySelector("dd,td,div");
        if (dd) text = norm(dd.textContent);
      }
    }
    if (!text) return null;
    text = text.replace(labelText, "").trim();
    return text || null;
  }, labelText);
  if (!text) return null;
  return normalizeTextLines(text)
    .split(/\n/)
    .map((l) => l.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join(" / ");
}

async function extractItemNamesFromDom(page) {
  const labelText = "商品名";
  let nameFromLabel = null;
  try {
    nameFromLabel = await page.evaluate((labelText) => {
      const candidates = Array.from(document.querySelectorAll("th,dt,div,span,label"));
      const label = candidates.find((el) => (el.textContent || "").trim() === labelText);
      if (!label) return null;
      const row = label.closest("tr,dl,div");
      if (row) {
        const cell = row.querySelector("td,dd,div");
        if (cell) return (cell.textContent || "").trim();
      }
      if (label.nextElementSibling) return (label.nextElementSibling.textContent || "").trim();
      return null;
    }, labelText);
  } catch {
    nameFromLabel = null;
  }
  if (nameFromLabel) {
    const cleaned = normalizeTextLines(nameFromLabel).replace(/\s+/g, " ").trim();
    if (cleaned) return cleaned;
  }

  const selectors = [
    "a[href*='/item/']",
    "a[href*='/product/']",
    ".item-name",
    ".itemTitle",
  ];
  const blacklist = [
    "注文",
    "領収書",
    "請求",
    "返品",
    "ヘルプ",
    "お問い合わせ",
    "詳細",
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
      const t = normalizeTextLines(raw).replace(/\s+/g, " ").trim();
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

  if (out.length) return out.join(" / ");

  let html = "";
  try {
    html = await page.content();
  } catch {
    html = "";
  }
  if (html) {
    const matches = [...html.matchAll(/itemName\"\\s*:\\s*\"(.*?)\"/g)];
    for (const m of matches) {
      const raw = m[1] || "";
      const t = normalizeTextLines(raw).replace(/\\s+/g, " ").trim();
      if (!t) continue;
      if (t.length < 3 || t.length > 160) continue;
      const lower = t.toLowerCase();
      if (lower.includes("order") || lower.includes("invoice") || lower.includes("help")) continue;
      if (blacklist.some((b) => t.includes(b))) continue;
      if (seen.has(t)) continue;
      seen.add(t);
      out.push(t);
      if (out.length >= 3) break;
    }
  }

  return out.length ? out.join(" / ") : null;
}

function normalizeReceiptUrlCandidate(rawHref, baseUrl) {
  const raw = String(rawHref || "").trim();
  if (!raw) return null;
  const lower = raw.toLowerCase();
  if (raw === ":" || raw === "#" || lower.startsWith("javascript:") || lower === "void(0)") {
    return null;
  }
  try {
    if (raw.startsWith("http://") || raw.startsWith("https://")) {
      if (raw === baseUrl) return null;
      if (raw.includes("act=detail_page_view")) return null;
      return raw;
    }
    if (raw.startsWith("/")) {
      const resolved = new URL(raw, baseUrl).toString();
      if (resolved === baseUrl) return null;
      if (resolved.includes("act=detail_page_view")) return null;
      return resolved;
    }
    const resolved = new URL(raw, baseUrl).toString();
    if (!resolved || resolved === baseUrl) return null;
    if (resolved.includes("act=detail_page_view")) return null;
    return resolved;
  } catch {
    return null;
  }
}

async function installWindowOpenCapture(page) {
  await page
    .evaluate(() => {
      if (window.__axOpenCaptureInstalled) return;
      const originalOpen = window.open ? window.open.bind(window) : null;
      window.__axOpenCaptureInstalled = true;
      window.__axOpenCalls = [];
      window.open = function (...args) {
        try {
          const first = args.length > 0 ? String(args[0] || "") : "";
          const target = args.length > 1 ? String(args[1] || "") : "";
          window.__axOpenCalls.push({ url: first, target, at: Date.now() });
        } catch {
          // ignore
        }
        if (typeof originalOpen === "function") {
          return originalOpen(...args);
        }
        return null;
      };
    })
    .catch(() => {});
}

async function consumeCapturedWindowOpenUrl(page, baseUrl) {
  const calls = await page
    .evaluate(() => {
      const list = Array.isArray(window.__axOpenCalls) ? window.__axOpenCalls.slice() : [];
      window.__axOpenCalls = [];
      return list;
    })
    .catch(() => []);
  if (!Array.isArray(calls) || calls.length === 0) return null;

  for (let i = calls.length - 1; i >= 0; i -= 1) {
    const raw = String(calls[i]?.url || "").trim();
    const normalized = normalizeReceiptUrlCandidate(raw, baseUrl);
    if (!normalized) continue;
    if (!/act=(order_invoice|order_receipt)/i.test(normalized)) continue;
    return normalized;
  }
  return null;
}

function buildReceiptActionScript(rawHref, rawOnclick) {
  const candidates = [rawHref, rawOnclick]
    .map((v) => String(v || "").trim())
    .filter(Boolean);
  for (const candidate of candidates) {
    if (candidate.toLowerCase().startsWith("javascript:")) {
      const code = candidate.slice("javascript:".length).trim();
      if (code) return code;
      continue;
    }
    if (/postReceipt\s*\(/i.test(candidate)) {
      return candidate;
    }
  }
  return null;
}

async function invokeReceiptActionScript(page, actionScript) {
  const script = String(actionScript || "").trim();
  if (!script) return false;
  return page
    .evaluate((code) => {
      try {
        // Some Rakuten pages expose receipt actions as inline script snippets.
        // Executing the same snippet is safer than introducing additional clicks.
        const fn = new Function(code);
        fn.call(window);
        return true;
      } catch {
        try {
          (0, eval)(code);
          return true;
        } catch {
          return false;
        }
      }
    }, script)
    .catch(() => false);
}

function fileLooksLikePdf(filePath) {
  try {
    const fd = fs.openSync(filePath, "r");
    try {
      const buf = Buffer.alloc(4);
      const read = fs.readSync(fd, buf, 0, 4, 0);
      return read === 4 && buf.toString("ascii") === "%PDF";
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    return false;
  }
}

async function capturePopupReceiptSource(popup, parentPage, baseUrl, timeoutMs, orderId = "unknown") {
  const start = Date.now();
  let lastCheckedBodyAt = 0;
  while (Date.now() - start < timeoutMs) {
    if (popup.isClosed()) return { page: null, url: null };

    await acceptIssueConfirm(parentPage, 220).catch(() => {});
    await acceptIssueConfirm(popup, 220).catch(() => {});

    const normalizedUrl = normalizeReceiptUrlCandidate(popup.url(), baseUrl);
    if (normalizedUrl) {
      return { page: popup, url: normalizedUrl };
    }

    const now = Date.now();
    if (now - lastCheckedBodyAt > 650) {
      lastCheckedBodyAt = now;
      const bodyText = await popup.innerText("body").catch(() => "");
      if (bodyText) {
        const checked = assessRakutenReceiptPageText(bodyText);
        if (checked.ok) {
          console.error(`[rakuten] order ${orderId} popup ready without navigated URL`);
          return { page: popup, url: null };
        }
      }
    }

    await popup.waitForLoadState("domcontentloaded", { timeout: 800 }).catch(() => {});
    await popup.waitForTimeout(140);
  }
  return { page: popup.isClosed() ? null : popup, url: null };
}

async function buildDirectReceiptUrl(page, primaryName, fallbackName) {
  const context = await page
    .evaluate(() => {
      const state = window.__INITIAL_STATE__;
      if (!state || typeof state !== "object") return null;
      const requestParams = state.requestParams && typeof state.requestParams === "object" ? state.requestParams : {};
      const orderData = state.orderData && typeof state.orderData === "object" ? state.orderData : {};
      const flags = orderData.flags && typeof orderData.flags === "object" ? orderData.flags : {};
      const orderReceipt = orderData.orderReceipt && typeof orderData.orderReceipt === "object" ? orderData.orderReceipt : {};
      const invoiceStatus = orderReceipt.invoiceStatus && typeof orderReceipt.invoiceStatus === "object" ? orderReceipt.invoiceStatus : {};

      const shopId =
        requestParams.shopId != null ? String(requestParams.shopId) : orderData.shopId != null ? String(orderData.shopId) : "";
      const orderNumber =
        requestParams.orderNumber != null
          ? String(requestParams.orderNumber)
          : orderData.orderNumber != null
            ? String(orderData.orderNumber)
            : "";
      const email = requestParams.email != null ? String(requestParams.email) : "";
      return {
        isGuestOrder: Boolean(flags.isGuestOrder),
        isOrderInvoice: Boolean(flags.isOrderInvoice),
        shopId,
        orderNumber,
        email,
        receiptName: invoiceStatus.receiptName != null ? String(invoiceStatus.receiptName) : "",
      };
    })
    .catch(() => null);

  if (!context || !context.shopId || !context.orderNumber) return null;
  const base = new URL("/purchase-history/", page.url()).toString();
  const params = new URLSearchParams();
  params.set("lang", "ja");
  params.set("shop_id", context.shopId);
  params.set("order_number", context.orderNumber);
  params.set("act", context.isOrderInvoice ? "order_invoice" : "order_receipt");
  params.set("page", context.isGuestOrder ? "search" : "myorder");
  const nameKey = context.isOrderInvoice ? "receipt_name" : "name";
  const preferredName =
    (String(primaryName || "").trim() || String(fallbackName || "").trim() || String(context.receiptName || "").trim());
  if (preferredName) {
    params.set(nameKey, preferredName);
  }
  if (context.isGuestOrder && context.email) {
    params.set("email", context.email);
  }
  params.set("from_member_detail_page", "true");
  return `${base}?${params.toString()}`;
}

async function extractDetailLinks(page) {
  const links = page.locator("a[href]");
  const n = await links.count();
  const out = [];
  for (let i = 0; i < n; i++) {
    const el = links.nth(i);
    const href = await el.getAttribute("href");
    if (!href) continue;
    const text = normalizeText(await el.innerText().catch(() => ""));
    const url = href.startsWith("/") ? new URL(href, page.url()).toString() : href;
    if (/order/i.test(url) && /詳細|注文/.test(text)) {
      out.push(url);
      continue;
    }
    if (/order/i.test(url) && /detail|history|orderId|order_id|order-id/i.test(url)) {
      out.push(url);
    }
  }
  return out;
}

function parseLooseYen(value) {
  if (value == null) return null;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    return Math.trunc(value);
  }
  const text = String(value).replace(/[^\d-]/g, "");
  if (!text) return null;
  const parsed = Number.parseInt(text, 10);
  return Number.isNaN(parsed) ? null : parsed;
}

function normalizeOrderDateFromText(raw, fallbackYear) {
  const text = normalizeText(String(raw || ""));
  if (!text) return null;
  const parts = parseJapaneseDate(text, fallbackYear);
  if (!parts) return null;
  return `${String(parts.y).padStart(4, "0")}-${String(parts.m).padStart(2, "0")}-${String(parts.d).padStart(2, "0")}`;
}

async function extractOrderDetailFromInitialState(page, fallbackYear) {
  const stateSummary = await page
    .evaluate(() => {
      const s = window.__INITIAL_STATE__;
      if (!s || typeof s !== "object") return null;
      const orderData = s.orderData && typeof s.orderData === "object" ? s.orderData : {};
      const orderSummary = orderData.orderSummary && typeof orderData.orderSummary === "object" ? orderData.orderSummary : {};
      const itemObject = orderData.itemObject && typeof orderData.itemObject === "object" ? orderData.itemObject : {};
      const paymentInfoModel =
        orderData.paymentInfoModel && typeof orderData.paymentInfoModel === "object" ? orderData.paymentInfoModel : {};
      const requestParams = s.requestParams && typeof s.requestParams === "object" ? s.requestParams : {};

      const itemList = Array.isArray(itemObject.itemList) ? itemObject.itemList : [];
      const itemNames = [];
      for (const it of itemList) {
        if (!it || typeof it !== "object") continue;
        const name = String(it.itemName || "").trim();
        if (!name) continue;
        if (!itemNames.includes(name)) itemNames.push(name);
        if (itemNames.length >= 3) break;
      }

      return {
        orderId: String(orderSummary.orderNumber || requestParams.orderNumber || "").trim(),
        orderDateRaw: String(orderSummary.orderCreationDate || "").trim(),
        totalCandidates: [
          orderSummary.totalPrice,
          orderSummary.totalOrderAmount,
          itemObject.totalOrderAmount,
          itemObject.paymentAmount,
        ],
        itemNames,
        paymentMethod: String(paymentInfoModel.paymentMethodName || "").trim(),
      };
    })
    .catch(() => null);

  if (!stateSummary) return null;
  let totalYen = null;
  for (const candidate of stateSummary.totalCandidates || []) {
    const parsed = parseLooseYen(candidate);
    if (parsed != null) {
      totalYen = parsed;
      break;
    }
  }
  const orderDate = normalizeOrderDateFromText(stateSummary.orderDateRaw, fallbackYear);
  const itemName =
    Array.isArray(stateSummary.itemNames) && stateSummary.itemNames.length
      ? stateSummary.itemNames.map((name) => normalizeTextLines(name).replace(/\s+/g, " ").trim()).filter(Boolean).join(" / ")
      : null;
  return {
    orderId: stateSummary.orderId || null,
    orderDate,
    totalYen,
    itemName: itemName || null,
    paymentMethod: stateSummary.paymentMethod || null,
  };
}

async function parseOrderDetail(page, fallbackYear, detailUrl) {
  const raw = await page.innerText("body").catch(() => "");
  const text = normalizeText(raw);
  const stateDetail = await extractOrderDetailFromInitialState(page, fallbackYear);

  const idMatch = text.match(/注文番号\s*[:：]?\s*([0-9-]{6,})/);
  const orderId = stateDetail?.orderId || (idMatch ? idMatch[1] : null) || detailUrl.match(/order_number=([^&]+)/)?.[1] || null;

  const dateMatch =
    text.match(/注文日(?:時刻)?\s*[:：]?\s*([0-9/年月日 ()]+?)(?:\s|$)/) ||
    text.match(/購入日\s*[:：]?\s*([0-9/年月日 ()]+?)(?:\s|$)/);
  const dateParts = dateMatch ? parseJapaneseDate(dateMatch[1], fallbackYear) : null;
  let orderDate =
    stateDetail?.orderDate ||
    (dateParts
      ? `${String(dateParts.y).padStart(4, "0")}-${String(dateParts.m).padStart(2, "0")}-${String(dateParts.d).padStart(2, "0")}`
      : null);
  if (!orderDate) {
    orderDate = parseOrderDateFromUrl(detailUrl || page.url());
  }

  let totalYen = stateDetail?.totalYen ?? null;
  if (totalYen == null) {
    totalYen = extractTotalFromText(text);
  }
  const itemName = stateDetail?.itemName || (await extractItemNamesFromDom(page));
  const paymentMethod =
    stateDetail?.paymentMethod ||
    (await extractPaymentMethodFromDom(page)) ||
    extractFieldFromText(raw, [/お支払い方法|支払い方法|お支払方法/]) ||
    extractFieldFromText(raw, [/支払方法|決済方法/]);

  return { orderId, orderDate, totalYen, paymentMethod, itemName };
}

async function findReceiptAction(page) {
  const primaryButtons = [
    page.locator("button", { hasText: /^発行する$/ }).first(),
    page.locator("button", { hasText: /領収書発行|発行/ }).first(),
    page.locator("input[type='button'][value*='発行'], input[type='submit'][value*='発行']").first(),
  ];
  for (const btn of primaryButtons) {
    if ((await btn.count()) > 0 && (await btn.isVisible().catch(() => false))) return btn;
  }

  const section = page.locator("text=領収書").first();
  if ((await section.count()) > 0) {
    const container = section.locator("xpath=ancestor::*[self::section or self::div][1]");
    const buttonLike = container
      .locator(
        "button, input[type='button'], input[type='submit'], a",
        { hasText: /発行|表示|印刷|ダウンロード|領収書|請求書|購入明細/ }
      )
      .first();
    if ((await buttonLike.count()) > 0) return buttonLike;
  }
  const labels = ["領収書", "領収書を発行", "領収書発行", "購入明細", "請求書", "発行する", "表示する", "印刷", "ダウンロード", "Receipt", "Invoice"];
  for (const label of labels) {
    const a = page.locator("button, input[type='button'], input[type='submit'], a", { hasText: label }).first();
    if ((await a.count()) > 0) return a;
  }
  return null;
}

async function main() {
  const args = parseArgs(process.argv);
  const storageState = args["storage-state"];
  const ordersUrl = args["orders-url"] || "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order";
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

  const attachAutoDialog = (p) => {
    p.on("dialog", async (dialog) => {
      try {
        await dialog.accept();
      } catch {
        // ignore
      }
    });
  };
  attachAutoDialog(page);
  context.on("page", attachAutoDialog);
  if (pdfContext !== context) {
    pdfContext.on("page", attachAutoDialog);
  }

  let detailUrls = [];
  try {
    await page.goto(ordersUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    await ensureAuthenticated(page, authHandoff, "Rakuten order list");

    const seen = new Set();
    for (let pageNo = 1; pageNo <= 50; pageNo++) {
      await page.waitForTimeout(200);
      const links = await extractDetailLinks(page);
      for (const url of links) {
        if (!seen.has(url)) {
          seen.add(url);
          detailUrls.push(url);
        }
      }

      const next = page.locator("a", { hasText: "次へ" }).first();
      if ((await next.count()) === 0) break;
      const disabled = await next.getAttribute("aria-disabled");
      if (disabled === "true") break;
      await next.click().catch(() => {});
      await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    }

    if (detailUrls.length === 0 && debugDir) {
      await writeDebug(page, debugDir, "orders_page_empty");
    }

    const existing = readExistingProcessed(outJsonl);
    const outStream = fs.createWriteStream(outJsonl, { flags: existing.detailUrls.size ? "a" : "w" });
    let pdfSaved = 0;
    let noReceipt = 0;
    let included = 0;
    let filtered = 0;
    let errorCount = 0;
    let inMonthOrders = 0;
    let processed = 0;
    const current = { orderId: "", stage: "", detailUrl: "" };
    const heartbeat = createHeartbeat("rakuten", () => ({
      processed,
      total: detailUrls.length,
      in_month: inMonthOrders,
      pdf_saved: pdfSaved,
      no_receipt: noReceipt,
      errors: errorCount,
      current_order: current.orderId || "-",
      stage: current.stage || "-",
    }));

    const ymPrefix = `${year}-${String(month).padStart(2, "0")}-`;
    for (const detailUrl of detailUrls) {
      if (existing.detailUrls.has(detailUrl)) continue;
      processed += 1;
      current.detailUrl = detailUrl;
      current.orderId = "";
      current.stage = "start";
      let status = "ok";
      let receiptUrl = null;
      let pdfPath = null;
      let paymentMethod = null;
      let itemName = null;
      let include = true;
      let filteredReason = null;
      let orderId = null;
      let orderDate = null;
      let totalYen = null;
      let receiptNameApplied = false;
      let appliedName = null;
      let errorReason = null;
      let errorDetail = null;
      let paymentDocumentType = "receipt";

      try {
        current.stage = "open_detail";
        console.error(`[rakuten] order start detail=${detailUrl}`);
        const dateFromUrl = parseOrderDateFromUrl(detailUrl);
        if (dateFromUrl && !dateFromUrl.startsWith(ymPrefix)) {
          status = "out_of_month";
          include = false;
          orderDate = dateFromUrl;
          orderId = detailUrl.match(/order_number=([^&]+)/)?.[1] || null;
          filtered += 1;
          const record = {
            order_id: orderId,
            order_date: orderDate,
            total_yen: totalYen,
            payment_method: paymentMethod,
            document_type: paymentDocumentType,
            include,
            filtered_reason: "out_of_month",
            receipt_name: appliedName || receiptName || null,
            receipt_name_applied: receiptNameApplied,
            source: "rakuten",
            detail_url: detailUrl,
            receipt_url: receiptUrl,
            pdf_path: pdfPath,
            status,
          };
          outStream.write(JSON.stringify(record) + "\n");
          continue;
        }

        await page.goto(detailUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
        await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
        await ensureAuthenticated(page, authHandoff, "Rakuten order detail");

        const parsed = await parseOrderDetail(page, year, detailUrl);
        orderId = parsed.orderId;
        orderDate = parsed.orderDate;
        totalYen = parsed.totalYen;
        paymentMethod = parsed.paymentMethod;
        itemName = parsed.itemName;
        paymentDocumentType = classifyRakutenReceiptDocumentType(paymentMethod);
        current.orderId = orderId || "unknown";
        current.stage = "detail_parsed";

        if (orderDate) {
          const m = Number.parseInt(orderDate.slice(5, 7), 10);
          if (m !== month) {
            status = "out_of_month";
            include = false;
          }
        } else {
          status = "unknown_date";
          include = false;
        }

        if (include) {
          inMonthOrders += 1;
          let preApplied = await applyReceiptNameWithFallback(page, receiptName, receiptNameFallback);
          if (preApplied.applied) {
            receiptNameApplied = true;
          }
          if (preApplied.name) {
            appliedName = preApplied.name;
          }
          const allowDirectFallback = /books\.rakuten\.co\.jp/i.test(detailUrl || "");
          const directReceiptUrl = allowDirectFallback
            ? await buildDirectReceiptUrl(page, receiptName, receiptNameFallback)
            : null;
          if (directReceiptUrl) {
            console.error(`[rakuten] order ${orderId || "unknown"} direct receipt url prepared`);
          }

          const noReceiptByPaymentMethod = isRakutenNoReceiptPaymentMethod(paymentMethod);
          if (noReceiptByPaymentMethod) {
            status = "no_receipt";
            include = false;
            noReceipt += 1;
            errorReason = "no_receipt_payment_method";
            errorDetail = `payment_method=${normalizedPaymentMethodText(paymentMethod)}`;
            console.error(
              `[rakuten] order ${orderId || "unknown"} no receipt by payment method: ${String(paymentMethod || "")}`
            );
          }
          const receiptAction = include ? await findReceiptAction(page) : null;
          if (!receiptAction) {
            if (include && directReceiptUrl) {
              receiptUrl = directReceiptUrl;
              console.error(`[rakuten] order ${orderId || "unknown"} no receipt action, fallback to direct receipt url`);
            } else {
              if (include) {
                status = "no_receipt";
                noReceipt += 1;
                console.error(`[rakuten] order ${orderId || "unknown"} no receipt action`);
              }
            }
          } else {
            const isBooksDetail = /books\.rakuten\.co\.jp/i.test(String(detailUrl || ""));
            // Rakuten Books has an extra receiptInput -> receiptPrint flow and can take longer
            // when fallback/reopen logic is needed.
            const receiptTimeoutMs = isBooksDetail ? 90 * 1000 : 30 * 1000;
            const baseUrl = page.url();
            const href = await receiptAction.getAttribute("href");
            const onclick = await receiptAction.getAttribute("onclick");
            const actionScript = buildReceiptActionScript(href, onclick);
            receiptUrl = normalizeReceiptUrlCandidate(href, baseUrl);
            let receiptPopup = null;
            let receiptDownload = null;
            console.error(
              `[rakuten] order ${orderId || "unknown"} receipt action href=${String(href || "")} onclick=${String(
                onclick || ""
              )} normalized=${String(receiptUrl || "")}`
            );
            if (!receiptUrl) {
              let popupCaptured = null;
              let downloadCaptured = null;
              await installWindowOpenCapture(page);
              page
                .waitForEvent("popup", { timeout: receiptTimeoutMs })
                .then((p) => {
                  popupCaptured = p;
                  return p;
                })
                .catch(() => null);
              context
                .waitForEvent("download", { timeout: receiptTimeoutMs })
                .then((d) => {
                  downloadCaptured = d;
                  return d;
                })
                .catch(() => null);

              await receiptAction.click().catch(() => {});
              console.error(`[rakuten] order ${orderId || "unknown"} clicked receipt action on detail page`);
              const primaryConfirmed = await acceptIssueConfirm(page, 5000);
              console.error(`[rakuten] order ${orderId || "unknown"} confirm_primary=${String(primaryConfirmed)}`);
              const openCapturedPrimary = await consumeCapturedWindowOpenUrl(page, baseUrl);
              if (openCapturedPrimary && !receiptUrl) {
                receiptUrl = openCapturedPrimary;
                console.error(`[rakuten] order ${orderId || "unknown"} captured window.open url=${receiptUrl}`);
              }

              if (!primaryConfirmed && actionScript) {
                const invoked = await invokeReceiptActionScript(page, actionScript);
                console.error(`[rakuten] order ${orderId || "unknown"} action_script_invoked=${String(invoked)}`);
                if (invoked) {
                  await acceptIssueConfirm(page, 4000);
                  const openCapturedInvoked = await consumeCapturedWindowOpenUrl(page, baseUrl);
                  if (openCapturedInvoked && !receiptUrl) {
                    receiptUrl = openCapturedInvoked;
                    console.error(`[rakuten] order ${orderId || "unknown"} captured window.open url after invoke=${receiptUrl}`);
                  }
                }
              }

              const startAt = Date.now();
              while (Date.now() - startAt < receiptTimeoutMs) {
                if (!receiptPopup && popupCaptured) {
                  receiptPopup = popupCaptured;
                }
                if (!receiptDownload && downloadCaptured) {
                  receiptDownload = downloadCaptured;
                  console.error(`[rakuten] order ${orderId || "unknown"} download captured`);
                }

                if (receiptPopup && !receiptPopup.isClosed()) {
                  const source = await capturePopupReceiptSource(receiptPopup, page, baseUrl, 1000, orderId || "unknown");
                  receiptPopup = source.page || receiptPopup;
                  receiptUrl = source.url || receiptUrl;
                  const popupCurrentUrl = receiptPopup && !receiptPopup.isClosed() ? receiptPopup.url() : "closed";
                  console.error(
                    `[rakuten] order ${orderId || "unknown"} popup url=${popupCurrentUrl} normalized=${String(receiptUrl || "")}`
                  );
                }

                if (!receiptUrl) {
                  const maybe = normalizeReceiptUrlCandidate(page.url(), baseUrl);
                  if (maybe) {
                    receiptUrl = maybe;
                  }
                }
                if (!receiptUrl) {
                  const openCapturedLoop = await consumeCapturedWindowOpenUrl(page, baseUrl);
                  if (openCapturedLoop) {
                    receiptUrl = openCapturedLoop;
                    console.error(`[rakuten] order ${orderId || "unknown"} captured window.open url in loop=${receiptUrl}`);
                  }
                }

                if (receiptUrl || receiptDownload) {
                  break;
                }
                await acceptIssueConfirm(page, 260);
                await page.waitForTimeout(180);
              }

              const hasOpenPopup = Boolean(receiptPopup && !receiptPopup.isClosed());
              if (!receiptUrl && !hasOpenPopup && !receiptDownload) {
                receiptUrl = await waitForReceiptUrl(page, baseUrl, 5000);
                console.error(`[rakuten] order ${orderId || "unknown"} waitForReceiptUrl result=${String(receiptUrl || "")}`);
              }

              if (!receiptUrl && directReceiptUrl) {
                receiptUrl = directReceiptUrl;
                console.error(`[rakuten] order ${orderId || "unknown"} fallback to direct receipt url`);
              }
            }

            const hasReceiptSource = Boolean(receiptUrl || (receiptPopup && !receiptPopup.isClosed()) || receiptDownload);
            if (!hasReceiptSource) {
              status = "error";
              include = false;
              const currentUrl = page.url();
              errorReason = "receipt_timeout";
              errorDetail = `detail_url=${detailUrl}, current_url=${currentUrl}`;
              console.error(`[rakuten] receipt timeout: ${orderId || "unknown"} detail=${detailUrl} current=${currentUrl}`);
              if (debugDir) {
                await writeDebug(page, debugDir, `order_${safeFilePart(orderId || "unknown")}_timeout`);
              }
            } else {
              const ymd = orderDate || `${year}-??-??`;
              const total = totalYen ?? "unknown";
              const fileName = `${safeFilePart(ymd)}_rakuten_${safeFilePart(orderId || "unknown")}_${safeFilePart(total)}.pdf`;
              const plannedPdfPath = path.join(outPdfsDir, fileName);

              try {
                if (receiptDownload) {
                  await withTimeout(
                    (async () => {
                      await receiptDownload.saveAs(plannedPdfPath);
                    })(),
                    receiptTimeoutMs,
                    "receipt_download_save"
                  );
                  if (!fileLooksLikePdf(plannedPdfPath)) {
                    throw new Error("rakuten_downloaded_file_not_pdf");
                  }
                  pdfPath = plannedPdfPath;
                } else {
                  if (receiptUrl && isDirectRakutenDownloadUrl(receiptUrl)) {
                    const saved = await saveReceiptFromDirectUrl(context, receiptUrl, plannedPdfPath, receiptTimeoutMs);
                    if (saved) {
                      pdfPath = plannedPdfPath;
                    } else {
                      throw new Error("rakuten_direct_download_not_saved");
                    }
                  } else {
                    const usingPopup = Boolean(receiptPopup && !receiptPopup.isClosed());
                    // Rakuten Books receiptInput/receiptPrint intermittently fails in headless context
                  // ("注文・配送状況の確認エラー"), so keep that flow on the visible context page.
                  const booksDetailFlow = /books\.rakuten\.co\.jp/i.test(String(detailUrl || ""));
                  if (booksDetailFlow && !usingPopup) {
                    console.error(`[rakuten] order ${orderId || "unknown"} books using visible context page`);
                  }
                  const needsNewPage = !usingPopup && pdfContext !== context && !booksDetailFlow;
                  const createdPdfPage = needsNewPage ? await pdfContext.newPage() : null;
                  let pdfPage = usingPopup ? receiptPopup : createdPdfPage || page;
                  try {
                    await withTimeout(
                      (async () => {
                        if (receiptUrl) {
                          const shouldNavigate = !usingPopup || pdfPage.url() !== receiptUrl;
                          if (shouldNavigate) {
                            await pdfPage.goto(receiptUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
                            await pdfPage.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
                          }
                        }
                        await ensureAuthenticated(pdfPage, authHandoff, "Rakuten receipt page");
                        await acceptIssueConfirm(pdfPage, 1200);
                        const booksFlowCandidate =
                          isRakutenBooksReceiptInputUrl(receiptUrl || pdfPage.url()) ||
                          isRakutenBooksReceiptPrintUrl(receiptUrl || pdfPage.url()) ||
                          /books\.rakuten\.co\.jp\/mypage\/delivery\/status/i.test(String(detailUrl || ""));

                        const booksNameResult = await applyRakutenBooksReceiptName(pdfPage, receiptName, receiptNameFallback);
                        if (booksNameResult.applied) receiptNameApplied = true;
                        if (!appliedName && booksNameResult.name) appliedName = booksNameResult.name;

                        let booksSavedAsPdf = false;

                        let booksPrintResult = { opened: false, page: pdfPage, download: null, source: "skipped_after_post" };
                        if (!booksSavedAsPdf) {
                          booksPrintResult = await openRakutenBooksReceiptPrintPage(
                            pdfPage,
                            orderId || "unknown",
                            Math.min(30000, receiptTimeoutMs)
                          );
                          if (!booksPrintResult.opened && booksFlowCandidate) {
                            const reopened = await reopenRakutenBooksReceiptFromDetail(
                              pdfPage,
                              detailUrl,
                              orderId || "unknown",
                              authHandoff,
                              30000
                            );
                            console.error(`[rakuten] order ${orderId || "unknown"} books fallback_reopen=${String(reopened)}`);
                            if (reopened) {
                              const retryBooksNameResult = await applyRakutenBooksReceiptName(
                                pdfPage,
                                receiptName,
                                receiptNameFallback
                              );
                              if (retryBooksNameResult.applied) receiptNameApplied = true;
                              if (!appliedName && retryBooksNameResult.name) appliedName = retryBooksNameResult.name;
                              booksPrintResult = await openRakutenBooksReceiptPrintPage(
                                pdfPage,
                                orderId || "unknown",
                                Math.min(30000, receiptTimeoutMs)
                              );
                            }
                          }
                        }
                        if (booksPrintResult.page && booksPrintResult.page !== pdfPage) {
                          if (createdPdfPage && pdfPage === createdPdfPage && !createdPdfPage.isClosed()) {
                            await createdPdfPage.close().catch(() => {});
                          }
                          pdfPage = booksPrintResult.page;
                          if (pdfPage !== page) {
                            receiptPopup = pdfPage;
                          }
                        }
                        if (booksPrintResult.download) {
                          await booksPrintResult.download.saveAs(plannedPdfPath);
                          if (!fileLooksLikePdf(plannedPdfPath)) {
                            throw new Error("rakuten_books_downloaded_file_not_pdf");
                          }
                          const dlUrl = booksPrintResult.download.url ? String(booksPrintResult.download.url() || "") : "";
                          if (dlUrl) receiptUrl = dlUrl;
                          booksSavedAsPdf = true;
                          console.error(
                            `[rakuten] order ${orderId || "unknown"} books receipt saved via download source=${String(
                              booksPrintResult.source || ""
                            )}`
                          );
                        }
                        if (booksPrintResult.opened) {
                          receiptUrl = pdfPage.url();
                          console.error(
                            `[rakuten] order ${orderId || "unknown"} books receipt print url=${String(receiptUrl || "")}`
                          );
                          await ensureAuthenticated(pdfPage, authHandoff, "Rakuten books receipt print page");
                          await acceptIssueConfirm(pdfPage, 1200);
                        }
                        if (booksFlowCandidate && isLowConfidenceItemName(itemName)) {
                          const booksReceiptText = await pdfPage.innerText("body").catch(() => "");
                          const booksItemName = extractRakutenBooksItemNameFromText(booksReceiptText);
                          if (booksItemName) {
                            itemName = booksItemName;
                            console.error(
                              `[rakuten] order ${orderId || "unknown"} books item_name captured from receipt text`
                            );
                          }
                        }
                        if (
                          !booksSavedAsPdf &&
                          booksFlowCandidate &&
                          booksPrintResult.opened &&
                          receiptUrl &&
                          isDirectRakutenDownloadUrl(receiptUrl)
                        ) {
                          console.error(
                            `[rakuten] order ${orderId || "unknown"} books try direct save from receiptPrint url`
                          );
                          const savedFromReceiptPrintUrl = await saveReceiptFromDirectUrl(
                            context,
                            receiptUrl,
                            plannedPdfPath,
                            Math.min(receiptTimeoutMs, 15000)
                          );
                          if (!savedFromReceiptPrintUrl) {
                            throw new Error("rakuten_books_receiptprint_direct_download_not_saved");
                          }
                          booksSavedAsPdf = true;
                          console.error(
                            `[rakuten] order ${orderId || "unknown"} books receipt saved via direct receiptPrint url`
                          );
                        }
                        if (!booksSavedAsPdf && booksFlowCandidate && !booksPrintResult.opened) {
                          console.error(
                            `[rakuten] order ${orderId || "unknown"} books try direct post from receiptInput (late)`
                          );
                          const posted = await saveRakutenBooksReceiptFromInputViaRequest(
                            pdfPage,
                            plannedPdfPath,
                            Math.min(receiptTimeoutMs, 10000),
                            orderId || "unknown",
                            "late"
                          );
                          if (posted) {
                            booksSavedAsPdf = true;
                            receiptUrl = receiptUrl || String(pdfPage.url() || "");
                            console.error(`[rakuten] order ${orderId || "unknown"} books receipt saved via direct post (late)`);
                          } else {
                            console.error(
                              `[rakuten] order ${orderId || "unknown"} books direct post (late) returned no pdf`
                            );
                          }
                        }
                        if (booksSavedAsPdf) {
                          return;
                        }
                        if (booksFlowCandidate) {
                          throw new Error("rakuten_books_receipt_direct_download_required");
                        }
                        await assertRakutenReceiptPage(pdfPage, { requireBooksPrint: booksFlowCandidate });
                        if (totalYen == null) {
                          const t = await extractTotalFromText(await pdfPage.innerText("body").catch(() => ""));
                          if (t != null) totalYen = t;
                        }
                        let nameResult = await applyReceiptNameWithFallback(pdfPage, receiptName, receiptNameFallback);
                        const locked = await isReceiptNameLocked(pdfPage);
                        if (!nameResult.applied && receiptName && !locked) {
                          // Do not block automation with interactive prompt. Keep running and capture state.
                        }
                        receiptNameApplied = receiptNameApplied || Boolean(nameResult.applied);
                        if (!appliedName && nameResult.name) appliedName = nameResult.name;
                        await acceptIssueConfirm(pdfPage, 1200);
                        await assertRakutenReceiptPage(pdfPage, { requireBooksPrint: booksFlowCandidate });
                        await saveReceiptPdf(pdfPage, plannedPdfPath);
                      })(),
                      receiptTimeoutMs,
                      "receipt_pdf"
                    );
                  } finally {
                    if (createdPdfPage && !createdPdfPage.isClosed()) await createdPdfPage.close().catch(() => {});
                  }
                  pdfPath = plannedPdfPath;
                  }
                }
                pdfSaved += 1;
              } finally {
                if (receiptPopup && !receiptPopup.isClosed()) {
                  await receiptPopup.close().catch(() => {});
                }
              }
            }
          }
        } else {
          filtered += 1;
        }
      } catch (e) {
        const raw = String(e?.message || e || "");
        const normalized = normalizeRakutenOrderError(raw);
        if (include && shouldDowngradeRakutenReceiptError(normalized.code, detailUrl)) {
          status = "no_receipt";
          errorReason = normalized.code;
          if (!errorDetail && normalized.detail) errorDetail = normalized.detail;
          noReceipt += 1;
          console.error(
            `[rakuten] order ${orderId || "unknown"} downgraded error to no_receipt reason=${normalized.code}`
          );
          current.stage = "no_receipt";
        } else {
          status = "error";
          errorReason = normalized.code;
          if (!errorDetail && normalized.detail) errorDetail = normalized.detail;
          errorCount += 1;
          if (debugDir) await writeDebug(page, debugDir, `order_${safeFilePart(orderId || "unknown")}_error`);
          current.stage = "error";
        }
      }

      if (include && status === "ok") included += 1;
      const record = {
        order_id: orderId,
        order_date: orderDate,
        total_yen: totalYen,
        item_name: itemName || null,
        payment_method: paymentMethod,
        document_type: paymentDocumentType,
        include,
        filtered_reason: filteredReason,
        receipt_name: appliedName || receiptName || null,
        receipt_name_applied: receiptNameApplied,
        source: "rakuten",
        detail_url: detailUrl,
        receipt_url: receiptUrl,
        pdf_path: pdfPath,
        status,
        error_reason: errorReason,
        error_detail: errorDetail || null,
      };
      outStream.write(JSON.stringify(record) + "\n");
    }

    outStream.end();
    console.log(
      JSON.stringify({
        status: errorCount > 0 ? "failed" : "success",
        data: {
          orders_total: detailUrls.length,
          in_month_orders: inMonthOrders,
          included,
          filtered,
          error_count: errorCount,
          pdf_saved: pdfSaved,
          no_receipt: noReceipt,
          out_jsonl: outJsonl,
          out_pdfs_dir: outPdfsDir,
        },
      })
    );
    if (errorCount > 0) {
      throw new Error(`RAKUTEN_DOWNLOAD_ERRORS error_count=${errorCount} in_month_orders=${inMonthOrders} pdf_saved=${pdfSaved}`);
    }
  } catch (e) {
    if (debugDir) await writeDebug(page, debugDir, "fatal");
    throw e;
  } finally {
    try {
      heartbeat.stop();
    } catch {
      // ignore
    }
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
  assessRakutenReceiptContext,
  assessRakutenReceiptPageText,
  assessRakutenBooksReceiptPrintTransition,
  extractRakutenBooksItemNameFromText,
  isRakutenNoReceiptPaymentMethod,
  classifyRakutenReceiptDocumentType,
  isRakutenBooksReceiptInputUrl,
  isRakutenBooksReceiptPrintUrl,
  isDirectRakutenDownloadUrl,
  normalizeReceiptUrlCandidate,
  shouldDowngradeRakutenReceiptError,
};

const isMainModule = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMainModule) {
  main().catch((err) => {
    console.error(String(err && err.stack ? err.stack : err));
    process.exit(1);
  });
}

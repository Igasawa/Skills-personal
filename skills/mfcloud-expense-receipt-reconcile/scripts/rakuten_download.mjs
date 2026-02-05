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

function isRakutenLoginUrl(url) {
  return /login|signin|auth|id\.rakuten\.co\.jp/i.test(url || "");
}


async function locatorVisible(locator) {
  try {
    if ((await locator.count()) === 0) return false;
    return await locator.first().isVisible();
  } catch {
    return false;
  }
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
    await page.waitForTimeout(200);
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
    await acceptIssueConfirm(page, 2500);
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

async function acceptIssueConfirm(page, timeoutMs = 1200) {
  const start = Date.now();
  const selectors = ["この宛名で発行します", "宛名の変更はできません", "一度発行したあとは"];
  while (Date.now() - start < timeoutMs) {
    const dialog = page.locator("[role='dialog'], .modal, .MuiDialog-root").first();
    if ((await dialog.count()) > 0 && (await dialog.isVisible().catch(() => false))) {
      const btn = dialog
        .locator("button, input[type='button'], input[type='submit'], a", { hasText: /OK|はい|発行/ })
        .first();
      if ((await btn.count()) > 0) {
        await btn.click().catch(() => {});
        await page.waitForTimeout(200);
        return true;
      }
    }
    for (const text of selectors) {
      const label = page.locator(`text=${text}`).first();
      if ((await label.count()) > 0 && (await label.isVisible().catch(() => false))) {
        const container = label.locator("xpath=ancestor::*[self::div or self::section or self::dialog][1]");
        const ok = container
          .locator("button, input[type='button'], input[type='submit'], a", { hasText: /OK|はい|発行/ })
          .first();
        if ((await ok.count()) > 0) {
          await ok.click().catch(() => {});
          await page.waitForTimeout(200);
          return true;
        }
        const okGlobal = page
          .locator("button, input[type='button'], input[type='submit'], a", { hasText: /OK|はい|発行/ })
          .first();
        if ((await okGlobal.count()) > 0) {
          await okGlobal.click().catch(() => {});
          await page.waitForTimeout(200);
          return true;
        }
      }
    }
    await page.waitForTimeout(200);
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
    await acceptIssueConfirm(page, 200);
    if (await isReceiptIssuePage(page)) return page.url();
    const url = page.url();
    if (url && url !== baseUrl) return url;
    await page.waitForTimeout(500);
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

async function parseOrderDetail(page, fallbackYear, detailUrl) {
  const raw = await page.innerText("body").catch(() => "");
  const text = normalizeText(raw);

  const idMatch = text.match(/注文番号\s*[:：]?\s*([0-9-]{6,})/);
  const orderId = idMatch ? idMatch[1] : null;

  const dateMatch =
    text.match(/注文日(?:時刻)?\s*[:：]?\s*([0-9/年月日 ()]+?)(?:\s|$)/) ||
    text.match(/購入日\s*[:：]?\s*([0-9/年月日 ()]+?)(?:\s|$)/);
  const dateParts = dateMatch ? parseJapaneseDate(dateMatch[1], fallbackYear) : null;
  let orderDate = dateParts
    ? `${String(dateParts.y).padStart(4, "0")}-${String(dateParts.m).padStart(2, "0")}-${String(dateParts.d).padStart(2, "0")}`
    : null;
  if (!orderDate) {
    orderDate = parseOrderDateFromUrl(detailUrl || page.url());
  }

  const totalYen = extractTotalFromText(text);
  const itemName = await extractItemNamesFromDom(page);
  const paymentMethod =
    (await extractPaymentMethodFromDom(page)) ||
    extractFieldFromText(raw, [/お支払い方法|支払い方法|お支払方法/]) ||
    extractFieldFromText(raw, [/支払方法|決済方法/]);

  return { orderId, orderDate, totalYen, paymentMethod, itemName };
}

async function findReceiptAction(page) {
  const section = page.locator("text=領収書").first();
  if ((await section.count()) > 0) {
    const container = section.locator("xpath=ancestor::*[self::section or self::div][1]");
    const btn = container.locator("a,button", { hasText: /発行|表示|印刷|ダウンロード|領収書|請求書|購入明細/ }).first();
    if ((await btn.count()) > 0) return btn;
  }
  const labels = ["領収書", "領収書を発行", "領収書発行", "購入明細", "請求書", "発行する", "表示する", "印刷", "ダウンロード", "Receipt", "Invoice"];
  for (const label of labels) {
    const a = page.locator("a,button", { hasText: label }).first();
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

    const ymPrefix = `${year}-${String(month).padStart(2, "0")}-`;
    for (const detailUrl of detailUrls) {
      if (existing.detailUrls.has(detailUrl)) continue;
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

      try {
        const dateFromUrl = parseOrderDateFromUrl(detailUrl);
        if (dateFromUrl && !dateFromUrl.startsWith(ymPrefix)) {
          status = "out_of_month";
          include = false;
          orderDate = dateFromUrl;
          orderId = detailUrl.match(/order_number=([^&]+)/)?.[1] || null;
          const record = {
            order_id: orderId,
            order_date: orderDate,
            total_yen: totalYen,
            payment_method: paymentMethod,
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
          let preApplied = await applyReceiptNameWithFallback(page, receiptName, receiptNameFallback);
          if (preApplied.applied) {
            receiptNameApplied = true;
          }
          if (preApplied.name) {
            appliedName = preApplied.name;
          }

          const receiptAction = await findReceiptAction(page);
          if (!receiptAction) {
            status = "no_receipt";
            noReceipt += 1;
          } else {
            const receiptTimeoutMs = 20 * 1000;
            let href = await receiptAction.getAttribute("href");
            if (href && href.startsWith("javascript")) href = null;
            receiptUrl = href ? (href.startsWith("/") ? new URL(href, page.url()).toString() : href) : null;
            if (!receiptUrl) {
              const baseUrl = page.url();
              const popupPromise = page.waitForEvent("popup", { timeout: 8000 }).catch(() => null);
              await receiptAction.click().catch(() => {});
              await acceptIssueConfirm(page, 1200);
              const popup = await popupPromise;
              if (popup) {
                await popup.waitForLoadState("domcontentloaded", { timeout: 15000 }).catch(() => {});
                receiptUrl = popup.url();
                await popup.close().catch(() => {});
              } else {
                await page.waitForTimeout(300);
                receiptUrl = (await isReceiptIssuePage(page)) ? page.url() : page.url();
              }
              if (!receiptUrl || receiptUrl === baseUrl) {
                receiptUrl = await waitForReceiptUrl(page, baseUrl, receiptTimeoutMs);
              }
            }

            if (!receiptUrl) {
              status = "error";
              include = false;
              errorReason = "receipt_timeout";
              console.error(`[rakuten] receipt timeout: ${orderId || "unknown"}`);
            } else {
            const ymd = orderDate || `${year}-??-??`;
            const total = totalYen ?? "unknown";
            const fileName = `${safeFilePart(ymd)}_rakuten_${safeFilePart(orderId || "unknown")}_${safeFilePart(total)}.pdf`;
            pdfPath = path.join(outPdfsDir, fileName);

            const pdfPage = pdfContext === context ? page : await pdfContext.newPage();
            try {
              await withTimeout(
                (async () => {
                  if (pdfContext !== context) {
                    await pdfPage.goto(receiptUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
                    await pdfPage.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
                  }
                  await ensureAuthenticated(pdfPage, authHandoff, "Rakuten receipt page");
                  await acceptIssueConfirm(pdfPage, 1200);
                  if (totalYen == null) {
                    const t = await extractTotalFromText(await pdfPage.innerText("body").catch(() => ""));
                    if (t != null) totalYen = t;
                  }
                  let nameResult = await applyReceiptNameWithFallback(pdfPage, receiptName, receiptNameFallback);
                  const locked = await isReceiptNameLocked(pdfPage);
                  if (!nameResult.applied && receiptName && authHandoff && !locked) {
                    await promptUserReceiptName(pdfPage);
                    const manualValue = await readReceiptNameValue(pdfPage);
                    if (manualValue) nameResult = { applied: true, name: manualValue };
                  }
                  receiptNameApplied = Boolean(nameResult.applied);
                  if (nameResult.name) appliedName = nameResult.name;
                  await acceptIssueConfirm(pdfPage, 1200);
                  await saveReceiptPdf(pdfPage, pdfPath);
                })(),
                receiptTimeoutMs,
                "receipt_pdf"
              );
            } finally {
              if (pdfContext !== context) await pdfPage.close().catch(() => {});
            }
            pdfSaved += 1;
            }
          }
        } else {
          filtered += 1;
        }
      } catch (e) {
        status = "error";
        errorReason = String(e?.message || e);
        if (debugDir) await writeDebug(page, debugDir, `order_${safeFilePart(orderId || "unknown")}_error`);
      }

      if (include && status === "ok") included += 1;
      const record = {
        order_id: orderId,
        order_date: orderDate,
        total_yen: totalYen,
        item_name: itemName || null,
        payment_method: paymentMethod,
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
      };
      outStream.write(JSON.stringify(record) + "\n");
    }

    outStream.end();
    console.log(
      JSON.stringify({
        status: "success",
        data: {
          orders_total: detailUrls.length,
          included,
          filtered,
          pdf_saved: pdfSaved,
          no_receipt: noReceipt,
          out_jsonl: outJsonl,
          out_pdfs_dir: outPdfsDir,
        },
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

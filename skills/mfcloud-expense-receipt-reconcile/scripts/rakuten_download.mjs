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

async function isRakutenLoginPage(page) {
  const url = page.url();
  if (isRakutenLoginUrl(url)) return true;
  const user = page.locator("input[name='u'], input[name*='user' i], input[type='email']");
  if ((await user.count()) > 0) return true;
  const pass = page.locator("input[type='password']");
  if ((await pass.count()) > 0) return true;
  const signIn = page.locator("button, input[type='submit']", { hasText: /ログイン|サインイン|Sign in/i }).first();
  if ((await signIn.count()) > 0) return true;
  return false;
}

async function waitForUserAuth(page, label) {
  if (!process.stdin || !process.stdin.isTTY) {
    throw new Error(`AUTH_REQUIRED: ${label} (non-interactive)`);
  }
  console.error(`[AUTH_REQUIRED] ${label}`);
  console.error("ブラウザでログインを完了したら、このウィンドウでEnterを押してください。");
  await page.bringToFront().catch(() => {});
  await new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once("data", () => resolve());
  });
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

  const save = page.locator("button, input[type='submit'], a", { hasText: /保存|更新|適用|登録|発行/ }).first();
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

async function saveReceiptPdf(page, outPdfPath) {
  await page.emulateMedia({ media: "print" });
  await page.pdf({ path: outPdfPath, format: "A4", printBackground: true });
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

function matchAllowlist(paymentMethod, allowlist) {
  if (!allowlist || allowlist.length === 0) return { allowed: false, reason: "allowlist_not_configured" };
  if (!paymentMethod) return { allowed: false, reason: "payment_method_unknown" };
  const pm = paymentMethod.toLowerCase();
  for (const a of allowlist) {
    if (!a) continue;
    if (pm.includes(String(a).toLowerCase())) return { allowed: true, reason: null };
  }
  return { allowed: false, reason: "payment_method_not_allowed" };
}

async function parseOrderDetail(page, fallbackYear) {
  const raw = await page.innerText("body").catch(() => "");
  const text = normalizeText(raw);

  const idMatch = text.match(/注文番号\s*[:：]?\s*([0-9-]{6,})/);
  const orderId = idMatch ? idMatch[1] : null;

  const dateMatch =
    text.match(/注文日(?:時刻)?\s*[:：]?\s*([0-9/年月日 ()]+?)(?:\s|$)/) ||
    text.match(/購入日\s*[:：]?\s*([0-9/年月日 ()]+?)(?:\s|$)/);
  const dateParts = dateMatch ? parseJapaneseDate(dateMatch[1], fallbackYear) : null;
  const orderDate = dateParts
    ? `${String(dateParts.y).padStart(4, "0")}-${String(dateParts.m).padStart(2, "0")}-${String(dateParts.d).padStart(2, "0")}`
    : null;

  const totalYen = extractTotalFromText(text);
  const paymentMethod =
    extractFieldFromText(raw, [/お支払い方法|支払い方法|お支払方法/]) ||
    extractFieldFromText(raw, [/支払方法|決済方法/]);

  return { orderId, orderDate, totalYen, paymentMethod };
}

async function findReceiptLink(page) {
  const labels = ["領収書", "領収書を発行", "領収書発行", "購入明細", "Receipt", "Invoice"];
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
  const receiptName = args["receipt-name"] ? String(args["receipt-name"]) : "";
  const receiptNameFallback = args["receipt-name-fallback"] ? String(args["receipt-name-fallback"]) : "";
  const authHandoff = Boolean(args["auth-handoff"]);
  const allowPaymentMethods = args["allow-payment-methods"]
    ? String(args["allow-payment-methods"])
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
    : [];

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

  let detailUrls = [];
  try {
    await page.goto(ordersUrl, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});
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
      await page.waitForLoadState("networkidle").catch(() => {});
    }

    if (detailUrls.length === 0 && debugDir) {
      await writeDebug(page, debugDir, "orders_page_empty");
    }

    const lines = [];
    let pdfSaved = 0;
    let noReceipt = 0;
    let included = 0;
    let filtered = 0;

    for (const detailUrl of detailUrls) {
      let status = "ok";
      let receiptUrl = null;
      let pdfPath = null;
      let paymentMethod = null;
      let include = true;
      let filteredReason = null;
      let orderId = null;
      let orderDate = null;
      let totalYen = null;
      let receiptNameApplied = false;
      let appliedName = null;

      try {
        await page.goto(detailUrl, { waitUntil: "domcontentloaded" });
        await page.waitForLoadState("networkidle").catch(() => {});
        await ensureAuthenticated(page, authHandoff, "Rakuten order detail");

        const parsed = await parseOrderDetail(page, year);
        orderId = parsed.orderId;
        orderDate = parsed.orderDate;
        totalYen = parsed.totalYen;
        paymentMethod = parsed.paymentMethod;

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
          const allow = matchAllowlist(paymentMethod, allowPaymentMethods);
          include = allow.allowed;
          filteredReason = allow.reason;
          if (!include) {
            status = "filtered_payment_method";
          }
        }

        if (include) {
          const receiptLink = await findReceiptLink(page);
          if (!receiptLink) {
            status = "no_receipt";
            noReceipt += 1;
          } else {
            let href = await receiptLink.getAttribute("href");
            if (href && href.startsWith("javascript")) href = null;
            receiptUrl = href ? (href.startsWith("/") ? new URL(href, page.url()).toString() : href) : null;
            if (!receiptUrl) {
              const popupPromise = page.waitForEvent("popup").catch(() => null);
              await receiptLink.click().catch(() => {});
              const popup = await popupPromise;
              if (popup) {
                await popup.waitForLoadState("domcontentloaded").catch(() => {});
                receiptUrl = popup.url();
                await popup.close().catch(() => {});
              } else {
                await page.waitForTimeout(300);
                receiptUrl = page.url();
              }
            }

            const ymd = orderDate || `${year}-??-??`;
            const total = totalYen ?? "unknown";
            const fileName = `${safeFilePart(ymd)}_rakuten_${safeFilePart(orderId || "unknown")}_${safeFilePart(total)}.pdf`;
            pdfPath = path.join(outPdfsDir, fileName);

            const pdfPage = pdfContext === context ? page : await pdfContext.newPage();
            try {
              if (pdfContext !== context) {
                await pdfPage.goto(receiptUrl, { waitUntil: "domcontentloaded" });
                await pdfPage.waitForLoadState("networkidle").catch(() => {});
              }
              await ensureAuthenticated(pdfPage, authHandoff, "Rakuten receipt page");
              if (totalYen == null) {
                const t = await extractTotalFromText(await pdfPage.innerText("body").catch(() => ""));
                if (t != null) totalYen = t;
              }
              const nameResult = await applyReceiptNameWithFallback(pdfPage, receiptName, receiptNameFallback);
              receiptNameApplied = Boolean(nameResult.applied);
              if (nameResult.applied) appliedName = nameResult.name;
              await saveReceiptPdf(pdfPage, pdfPath);
            } finally {
              if (pdfContext !== context) await pdfPage.close().catch(() => {});
            }
            pdfSaved += 1;
          }
        } else {
          filtered += 1;
        }
      } catch (e) {
        status = "error";
        if (debugDir) await writeDebug(page, debugDir, `order_${safeFilePart(orderId || "unknown")}_error`);
      }

      if (include && status === "ok") included += 1;

      lines.push(
        JSON.stringify({
          order_id: orderId,
          order_date: orderDate,
          total_yen: totalYen,
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
        })
      );
    }

    fs.writeFileSync(outJsonl, lines.join("\n") + (lines.length ? "\n" : ""), "utf-8");
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

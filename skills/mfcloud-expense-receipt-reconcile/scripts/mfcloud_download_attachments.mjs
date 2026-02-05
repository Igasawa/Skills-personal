#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";
import { ensureDir, parseArgs, safeFilePart, writeDebug } from "./mjs_common.mjs";

function parseDateLike(s) {
  if (!s) return null;
  const t = String(s).trim().replace(/\//g, "-");
  const m = t.match(/(20\d{2})-(\d{1,2})-(\d{1,2})/);
  if (m) return `${m[1]}-${String(+m[2]).padStart(2, "0")}-${String(+m[3]).padStart(2, "0")}`;
  const m2 = t.match(/(20\d{2})年(\d{1,2})月(\d{1,2})日/);
  if (m2) return `${m2[1]}-${String(+m2[2]).padStart(2, "0")}-${String(+m2[3]).padStart(2, "0")}`;
  return null;
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

function readJsonl(filePath) {
  const content = fs.readFileSync(filePath, "utf-8");
  const lines = content.split(/\r?\n/).filter((l) => l.trim().length);
  return lines.map((l) => JSON.parse(l));
}

function isLoginUrl(url) {
  return /sign[_-]?in|login|auth/i.test(url || "");
}

async function isLoginPage(page) {
  const url = page.url();
  if (isLoginUrl(url)) return true;
  const email = page.locator("input[type='email'], input[name*='email' i]");
  if ((await email.count()) > 0) return true;
  const password = page.locator("input[type='password']");
  if ((await password.count()) > 0) return true;
  const signIn = page.locator("button, input[type='submit']", { hasText: /ログイン|サインイン|Sign in/i }).first();
  if ((await signIn.count()) > 0) return true;
  return false;
}

async function waitForUserAuth(page, label) {
  console.error(`[AUTH_REQUIRED] ${label}`);
  await page.bringToFront().catch(() => {});
  if (!process.stdin || !process.stdin.isTTY) {
    const timeoutMs = 15 * 60 * 1000;
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      await page.waitForTimeout(1000);
      if (!(await isLoginPage(page))) {
        return;
      }
    }
    throw new Error(`AUTH_REQUIRED: ${label} (timeout waiting for manual login)`);
  }
  console.error("Please complete login in the browser, then press Enter here.");
  await new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once("data", () => resolve());
  });
}


async function ensureAuthenticated(page, authHandoff, label) {
  if (!(await isLoginPage(page))) return;
  if (!authHandoff) {
    throw new Error(`AUTH_REQUIRED: ${label} (storage_state expired)`);
  }
  await waitForUserAuth(page, label);
  await page.waitForLoadState("networkidle").catch(() => {});
  if (await isLoginPage(page)) {
    throw new Error(`AUTH_REQUIRED: ${label} (still on login page)`);
  }
}

async function collectDownloadCandidates(page) {
  const candidates = await page.evaluate(() => {
    const items = [];
    const anchors = Array.from(document.querySelectorAll("a[href]"));
    for (const a of anchors) {
      const href = a.getAttribute("href") || "";
      const text = (a.textContent || "").trim();
      items.push({ href, text });
    }
    return items;
  });
  const out = [];
  for (const c of candidates) {
    const text = normalizeText(c.text);
    const href = c.href || "";
    if (!href) continue;
    if (/(pdf|jpg|jpeg|png)(\?|$)/i.test(href)) {
      out.push({ href, reason: "file_extension", text });
      continue;
    }
    if (/download|ダウンロード|証憑|添付|領収書/i.test(text)) {
      out.push({ href, reason: "text_match", text });
      continue;
    }
    if (/download|receipt|attachment|evidence/i.test(href)) {
      out.push({ href, reason: "href_match", text });
    }
  }
  return out;
}

async function tryDownloadFromButtons(page, outDir, prefix, debugDir) {
  const downloads = [];
  const buttons = page.locator("a,button", { hasText: /ダウンロード|download/i });
  const count = await buttons.count();
  for (let i = 0; i < count; i++) {
    const btn = buttons.nth(i);
    try {
      const dlPromise = page.waitForEvent("download", { timeout: 8000 }).catch(() => null);
      await btn.click({ timeout: 5000 }).catch(() => {});
      const dl = await dlPromise;
      if (!dl) continue;
      const suggested = dl.suggestedFilename();
      const fileName = `${prefix}_${safeFilePart(suggested || `attachment_${i + 1}`)}`;
      const outPath = path.join(outDir, fileName);
      await dl.saveAs(outPath);
      downloads.push({ path: outPath, suggested });
    } catch (e) {
      if (debugDir) await writeDebug(page, debugDir, `download_button_${i + 1}_error`);
    }
  }
  return downloads;
}

async function tryDownloadFromLinks(page, outDir, prefix, debugDir) {
  const downloads = [];
  const candidates = await collectDownloadCandidates(page);
  const seen = new Set();
  for (const c of candidates) {
    const url = c.href.startsWith("/") ? new URL(c.href, page.url()).toString() : c.href;
    if (seen.has(url)) continue;
    seen.add(url);
    try {
      const dlPromise = page.waitForEvent("download", { timeout: 8000 }).catch(() => null);
      await page.goto(url, { waitUntil: "domcontentloaded" }).catch(() => {});
      const dl = await dlPromise;
      if (!dl) continue;
      const suggested = dl.suggestedFilename();
      const fileName = `${prefix}_${safeFilePart(suggested || "attachment")}`;
      const outPath = path.join(outDir, fileName);
      await dl.saveAs(outPath);
      downloads.push({ path: outPath, suggested });
    } catch (e) {
      if (debugDir) await writeDebug(page, debugDir, `download_link_error`);
    }
  }
  return downloads;
}

async function main() {
  const args = parseArgs(process.argv);
  const storageState = args["storage-state"];
  const expensesJsonl = args["expenses-jsonl"];
  const outJsonl = args["out-jsonl"];
  const outDir = args["out-dir"];
  const debugDir = args["debug-dir"];
  const headed = args.headed !== false;
  const slowMoMs = Number.parseInt(args["slow-mo-ms"] || "0", 10);
  const year = Number.parseInt(args.year, 10);
  const month = Number.parseInt(args.month, 10);
  const authHandoff = Boolean(args["auth-handoff"]);

  if (!storageState) throw new Error("Missing --storage-state");
  if (!expensesJsonl) throw new Error("Missing --expenses-jsonl");
  if (!outJsonl) throw new Error("Missing --out-jsonl");
  if (!outDir) throw new Error("Missing --out-dir");
  if (!year || !month) throw new Error("Missing --year/--month");

  ensureDir(path.dirname(outJsonl));
  ensureDir(outDir);
  if (debugDir) ensureDir(debugDir);

  const expenses = readJsonl(expensesJsonl);
  const ymPrefix = `${year}-${String(month).padStart(2, "0")}-`;
  const targets = expenses.filter((e) => {
    const d = parseDateLike(e.use_date || e.date);
    if (!d || !d.startsWith(ymPrefix)) return false;
    return Boolean(e.detail_url);
  });

  const browser = await chromium.launch({ headless: !headed, slowMo: slowMoMs });
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  const lines = [];
  let downloaded = 0;
  let noAttachment = 0;

  try {
    for (const exp of targets) {
      const expenseId = String(exp.expense_id || exp.id || "");
      const useDate = parseDateLike(exp.use_date || exp.date);
      const detailUrl = exp.detail_url;
      let status = "ok";
      let filePaths = [];

      try {
        await page.goto(detailUrl, { waitUntil: "domcontentloaded" });
        await page.waitForLoadState("networkidle").catch(() => {});
        await ensureAuthenticated(page, authHandoff, "MF Cloud expense detail");

        const prefix = `${safeFilePart(useDate || "unknown")}_${safeFilePart(expenseId || "expense")}`;
        let dl = await tryDownloadFromButtons(page, outDir, prefix, debugDir ? path.join(debugDir, "buttons") : null);
        if (dl.length === 0) {
          dl = await tryDownloadFromLinks(page, outDir, prefix, debugDir ? path.join(debugDir, "links") : null);
        }
        if (dl.length === 0) {
          status = "no_attachment";
          noAttachment += 1;
        } else {
          downloaded += dl.length;
          filePaths = dl.map((d) => d.path);
        }
      } catch (e) {
        status = "error";
        if (debugDir) await writeDebug(page, debugDir, `expense_${safeFilePart(expenseId || "unknown")}_error`);
      }

      lines.push(
        JSON.stringify({
          expense_id: expenseId || null,
          use_date: useDate,
          detail_url: detailUrl,
          source: "mfcloud",
          status,
          files: filePaths,
        })
      );
    }

    fs.writeFileSync(outJsonl, lines.join("\n") + (lines.length ? "\n" : ""), "utf-8");
    console.log(
      JSON.stringify({
        status: "success",
        data: { expenses_total: targets.length, downloaded, no_attachment: noAttachment, out_jsonl: outJsonl, out_dir: outDir },
      })
    );
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});

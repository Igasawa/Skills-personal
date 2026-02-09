#!/usr/bin/env node
import fs from "node:fs";
import process from "node:process";
import { chromium } from "playwright";
import { ensureDir, parseArgs, writeDebug } from "./mjs_common.mjs";

function readFilesJson(path) {
  const raw = JSON.parse(fs.readFileSync(path, "utf-8"));
  if (!raw || typeof raw !== "object") return [];
  const files = Array.isArray(raw.files) ? raw.files : [];
  const out = [];
  for (const file of files) {
    const p = String(file || "").trim();
    if (!p) continue;
    out.push(p);
  }
  return out;
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
      if (!(await isLoginPage(page))) return;
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
  if (!authHandoff) throw new Error(`AUTH_REQUIRED: ${label} (storage_state expired)`);
  await waitForUserAuth(page, label);
  await page.waitForLoadState("networkidle").catch(() => {});
  if (await isLoginPage(page)) throw new Error(`AUTH_REQUIRED: ${label} (still on login page)`);
}

async function firstVisible(locator, maxCount = 10) {
  const count = Math.min(await locator.count(), maxCount);
  for (let i = 0; i < count; i++) {
    const item = locator.nth(i);
    if (await item.isVisible().catch(() => false)) return item;
  }
  return null;
}

async function openBulkUploadPage(page, transactionsUrl) {
  await page.goto(transactionsUrl, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});

  const bulkItemLocator = page.locator("a:has-text('領収書一括アップロード'), button:has-text('領収書一括アップロード')");
  let bulkItem = await firstVisible(bulkItemLocator, 8);
  if (!bulkItem) {
    const newRegister = await firstVisible(
      page.locator("button:has-text('新規登録'), a:has-text('新規登録'), [role='button']:has-text('新規登録')"),
      8
    );
    if (newRegister) {
      await newRegister.click({ timeout: 10000, force: true }).catch(() => {});
      await page.waitForTimeout(500);
    }
    bulkItem = await firstVisible(bulkItemLocator, 12);
  }

  if (bulkItem) {
    await Promise.all([
      page.waitForURL(/operator_input\/new/i, { timeout: 15000 }).catch(() => null),
      bulkItem.click({ timeout: 10000, force: true }),
    ]);
  } else {
    await page.goto("https://expense.moneyforward.com/operator_input/new", { waitUntil: "domcontentloaded" });
  }
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function selectOcrMode(page) {
  const ok = await page
    .evaluate(() => {
      const normalize = (value) => String(value || "").replace(/\s+/g, "");
      const selects = Array.from(document.querySelectorAll("select"));
      if (!selects.length) return false;
      let targetSelect = null;
      for (const sel of selects) {
        const contextText = normalize(sel.closest("tr, div, section, form")?.textContent || "");
        const ownText = normalize(sel.getAttribute("name") || "") + normalize(sel.id || "");
        if (contextText.includes("領収書処理種別") || ownText.includes("operator_input_type")) {
          targetSelect = sel;
          break;
        }
      }
      if (!targetSelect) targetSelect = selects[0];
      const options = Array.from(targetSelect.options || []);
      const targetOption = options.find((option) => String(option.textContent || "").includes("OCR入力"));
      if (!targetOption) return false;
      targetSelect.value = targetOption.value;
      targetSelect.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })
    .catch(() => false);
  if (!ok) throw new Error("ocr_mode_select_not_found");
}

async function attachFiles(page, files) {
  let fileInput = page.locator("input[type='file']").first();
  if ((await fileInput.count()) === 0) {
    const chooseButton = await firstVisible(
      page.locator("button:has-text('ファイルを選択'), label:has-text('ファイルを選択'), a:has-text('ファイルを選択')"),
      6
    );
    if (chooseButton) {
      await chooseButton.click({ timeout: 8000, force: true }).catch(() => {});
      await page.waitForTimeout(400);
    }
    fileInput = page.locator("input[type='file']").first();
  }
  if ((await fileInput.count()) === 0) throw new Error("file_input_not_found");
  await fileInput.setInputFiles(files);
}

async function clickSend(page) {
  const sendButton = await firstVisible(
    page.locator("button:has-text('送信'), input[type='submit'][value='送信'], input[type='button'][value='送信']"),
    8
  );
  if (!sendButton) throw new Error("send_button_not_found");
  await sendButton.click({ timeout: 10000, force: true });
}

async function waitForUploadFeedback(page, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const successVisible = await page
      .locator("text=アップロード, text=送信完了, text=受け付けました, text=登録しました")
      .first()
      .isVisible()
      .catch(() => false);
    if (successVisible) return "message";
    await page.waitForTimeout(300);
  }
  return "timeout";
}

async function main() {
  const args = parseArgs(process.argv);
  const storageState = String(args["storage-state"] || "");
  const transactionsUrl = String(args["transactions-url"] || "https://expense.moneyforward.com/transactions");
  const filesJson = String(args["files-json"] || "");
  const debugDir = args["debug-dir"] ? String(args["debug-dir"]) : "";
  const authHandoff = Boolean(args["auth-handoff"]);
  const headed = args.headed !== false;
  const slowMoMs = Number.parseInt(String(args["slow-mo-ms"] || "0"), 10);

  if (!storageState) throw new Error("Missing --storage-state");
  if (!filesJson) throw new Error("Missing --files-json");
  if (!fs.existsSync(filesJson)) throw new Error(`files manifest not found: ${filesJson}`);
  const allFiles = readFilesJson(filesJson).filter((filePath) => fs.existsSync(filePath));
  const queuedCount = allFiles.length;
  if (queuedCount === 0) {
    console.log(
      JSON.stringify({
        status: "success",
        data: {
          queued_count: 0,
          submitted_count: 0,
          submitted_files: [],
          submit_feedback: "no_files",
          transactions_url: transactionsUrl,
        },
      })
    );
    return;
  }

  if (debugDir) ensureDir(debugDir);
  const browser = await chromium.launch({ headless: !headed, slowMo: slowMoMs });
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  try {
    await openBulkUploadPage(page, transactionsUrl);
    await ensureAuthenticated(page, authHandoff, "MF Cloud transactions");
    await selectOcrMode(page);
    await attachFiles(page, allFiles);
    await clickSend(page);
    const submitFeedback = await waitForUploadFeedback(page, 20000);

    console.log(
      JSON.stringify({
        status: "success",
        data: {
          queued_count: queuedCount,
          submitted_count: queuedCount,
          submitted_files: allFiles,
          submit_feedback: submitFeedback,
          final_url: page.url(),
          transactions_url: transactionsUrl,
        },
      })
    );
  } catch (err) {
    if (debugDir) await writeDebug(page, debugDir, "mf_bulk_upload_failed").catch(() => {});
    throw err;
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});

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

async function openImportPage(page, importUrl) {
  await page.goto(importUrl, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function attachFiles(page, files) {
  let fileInput = page.locator("input[type='file']").first();
  if ((await fileInput.count()) === 0) {
    const chooseButton = await firstVisible(
      page.locator("button:has-text('ファイルを選択'), label:has-text('ファイルを選択'), a:has-text('ファイルを選択')"),
      8
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

async function clickImport(page) {
  const submitButton = await firstVisible(
    page.locator(
      [
        "button:has-text('インポート')",
        "button:has-text('取り込み')",
        "button:has-text('取込')",
        "button:has-text('アップロード')",
        "button:has-text('実行')",
        "button:has-text('次へ')",
        "input[type='submit'][value='インポート']",
        "input[type='submit'][value='取り込み']",
        "input[type='submit'][value='取込']",
      ].join(", ")
    ),
    10
  );
  if (!submitButton) throw new Error("csv_import_submit_button_not_found");
  await submitButton.click({ timeout: 10000, force: true });
}

async function waitForImportFeedback(page, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const successVisible = await page
      .locator("text=インポート完了, text=取り込み完了, text=取込完了, text=読み込み完了, text=登録しました")
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
  const importUrl = String(args["import-url"] || "https://expense.moneyforward.com/import_transactions/new");
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
          import_url: importUrl,
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
    await openImportPage(page, importUrl);
    await ensureAuthenticated(page, authHandoff, "MF Cloud transport CSV import");
    await attachFiles(page, allFiles);
    await clickImport(page);
    const submitFeedback = await waitForImportFeedback(page, 20000);

    console.log(
      JSON.stringify({
        status: "success",
        data: {
          queued_count: queuedCount,
          submitted_count: queuedCount,
          submitted_files: allFiles,
          submit_feedback: submitFeedback,
          final_url: page.url(),
          import_url: importUrl,
        },
      })
    );
  } catch (err) {
    if (debugDir) await writeDebug(page, debugDir, "mf_csv_import_failed").catch(() => {});
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

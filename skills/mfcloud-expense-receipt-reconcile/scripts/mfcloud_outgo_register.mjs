#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";
import { ensureDir, parseArgs, safeFilePart, writeDebug } from "./mjs_common.mjs";

function nowIso() {
  return new Date().toISOString();
}

function truncateString(value, maxLen = 400) {
  const s = String(value || "");
  if (s.length <= maxLen) return s;
  return `${s.slice(0, maxLen)}...`;
}

function appendJsonl(filePath, payload) {
  if (!filePath) return;
  try {
    ensureDir(path.dirname(filePath));
    fs.appendFileSync(filePath, `${JSON.stringify(payload)}\n`, "utf-8");
  } catch (err) {
    // Never fail the run because logging failed.
    console.error(`[mf_draft] audit_jsonl_write_failed path=${filePath} err=${String(err && err.message ? err.message : err)}`);
  }
}

function normalizeDraftError(message) {
  const m = String(message || "");
  if (!m) return { reason: "unknown_error", detail: "" };

  const direct = [
    "matching_row_not_found",
    "expense_editor_not_opened",
    "edit_register_button_not_found",
    "create_button_not_found",
    "editor_not_closed_after_create",
    "ocr_checkbox_not_checked",
    "ocr_checkbox_not_found",
    "file_input_not_found",
    "filechooser_not_opened",
    "receipt_file_attach_failed",
  ];
  for (const code of direct) {
    if (m.includes(code)) return { reason: code, detail: m };
  }

  if (m.startsWith("receipt_pdf_not_found:")) return { reason: "receipt_pdf_not_found", detail: m };
  if (m.startsWith("report json not found:")) return { reason: "report_json_not_found", detail: m };
  if (m.includes("AUTH_REQUIRED")) return { reason: "auth_required", detail: m };

  return { reason: "unclassified_error", detail: m };
}

function normalizeText(s) {
  return String(s || "")
    .replace(/[０-９]/g, (d) => String.fromCharCode(d.charCodeAt(0) - 0xfee0))
    .replace(/[，]/g, ",")
    .replace(/[／]/g, "/")
    .replace(/[－–—]/g, "-")
    .replace(/[（]/g, "(")
    .replace(/[）]/g, ")")
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function parseAnyDate(s) {
  const t = normalizeText(s);
  const m = t.match(/(20\d{2})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})/);
  if (!m) return null;
  return `${m[1]}-${String(Number.parseInt(m[2], 10)).padStart(2, "0")}-${String(Number.parseInt(m[3], 10)).padStart(2, "0")}`;
}

function parseAnyAmountYen(s) {
  const t = normalizeText(s);
  const amountMatches = [...t.matchAll(/([0-9][0-9,]*)\D{0,3}円/g)];
  if (amountMatches.length) {
    const last = amountMatches[amountMatches.length - 1]?.[1] || "";
    const n = Number.parseInt(String(last).replace(/[,\s]/g, ""), 10);
    return Number.isFinite(n) ? n : null;
  }
  const loose = t.match(/([0-9][0-9,]{2,})/g);
  if (loose && loose.length) {
    const n = Number.parseInt(String(loose[loose.length - 1]).replace(/[,\s]/g, ""), 10);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function normalizeToken(token) {
  return normalizeText(token).toLowerCase();
}

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const EDITOR_SUBMIT_SELECTOR = [
  "button:has-text('作成する')",
  "button:has-text('更新する')",
  "button:has-text('作成')",
  "button:has-text('更新')",
  "input[type='submit'][value='作成する']",
  "input[type='submit'][value='更新する']",
  "input[type='submit'][value='作成']",
  "input[type='submit'][value='更新']",
  "input[type='button'][value='作成する']",
  "input[type='button'][value='更新する']",
  "input[type='button'][value='作成']",
  "input[type='button'][value='更新']",
].join(", ");

function editorSubmitLocator(scope) {
  return scope.locator(EDITOR_SUBMIT_SELECTOR).first();
}

async function hasAnyReceiptAlreadyAttached(editorRoot) {
  // Prefer a conservative signal to avoid false positives.
  // Many MF tenants show a filename label that stays as "未選択/選択されていません" when no receipt is attached.
  const filenameLabel = editorRoot.locator(".js-receipt-preview__filename, .receipt-preview__filename").first();
  const labelText = await filenameLabel.textContent().catch(() => "");
  const normalized = String(labelText || "").trim();
  if (!normalized) return { ok: false, method: "no_label_text" };
  const placeholders = ["選択されていません", "未選択", "選択してください"];
  for (const token of placeholders) {
    if (normalized.includes(token)) return { ok: false, method: "placeholder_label" };
  }
  return { ok: true, method: "filename_label", filename: normalized };
}

async function isExpenseEditorOpen(page) {
  // Bootstrap modal (expense report edit page) uses a different structure than outgo_input.
  const bootstrapModal = page.locator("#modal-transaction-edit, .js-ex-transaction-edit-modal").first();
  const bootstrapVisible = await bootstrapModal.isVisible().catch(() => false);
  if (bootstrapVisible) return true;

  const titleVisible = await page.locator("text=経費登録").first().isVisible().catch(() => false);
  if (titleVisible) return true;

  // Some tenants/pages label the action buttons differently (e.g. 作成/更新).
  const submitVisible = await editorSubmitLocator(page).isVisible().catch(() => false);
  if (!submitVisible) return false;

  // Reduce false positives by requiring an editor-specific element as well.
  const attachVisible = await page.locator("text=領収書を添付").first().isVisible().catch(() => false);
  return attachVisible;
}

function keywordsForVendor(vendor, memo) {
  const source = [vendor || "", memo || ""].join(" ").replace(/[^\p{L}\p{N}\s&+._-]/gu, " ");
  const parts = source.split(/\s+/).map((x) => x.trim()).filter(Boolean);
  const uniq = [];
  const seen = new Set();
  for (const p of parts) {
    const n = normalizeToken(p);
    if (!n || n.length < 2 || seen.has(n)) continue;
    seen.add(n);
    uniq.push(n);
    if (uniq.length >= 6) break;
  }
  return uniq;
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

function loadTargets(reportJsonPath, year, month) {
  const raw = JSON.parse(fs.readFileSync(reportJsonPath, "utf-8"));
  const rows = Array.isArray(raw?.rows) ? raw.rows : [];
  const byExpense = new Map();
  const preSkipped = [];
  const ymPrefix = `${year}-${String(month).padStart(2, "0")}-`;
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    if (String(row.row_type || "") !== "candidate") continue;
    const expenseId = String(row.mf_expense_id || "").trim();
    if (!expenseId) continue;
    const rank = Number.parseInt(String(row.rank || "9999"), 10);
    if (!Number.isFinite(rank) || rank <= 0) continue;
    const useDate = String(row.mf_use_date || "").trim() || null;
    if (useDate && !useDate.startsWith(ymPrefix)) continue;
    const pdfPath = String(row.pdf_path || "").trim();
    const resolvedPdfPath = pdfPath ? path.resolve(pdfPath) : "";
    if (!resolvedPdfPath || !fs.existsSync(resolvedPdfPath)) {
      preSkipped.push({
        mf_expense_id: expenseId,
        status: "skipped",
        reason: "pdf_not_found",
        pdf_path: resolvedPdfPath || pdfPath || null,
      });
      continue;
    }
    const item = {
      mf_expense_id: expenseId,
      mf_use_date: useDate,
      mf_amount_yen: Number.isFinite(Number(row.mf_amount_yen)) ? Number(row.mf_amount_yen) : null,
      mf_vendor: String(row.mf_vendor || "").trim(),
      mf_memo: String(row.mf_memo || "").trim(),
      order_id: String(row.order_id || "").trim() || null,
      order_source: String(row.order_source || "").trim() || null,
      order_date: String(row.order_date || "").trim() || null,
      order_total_yen: Number.isFinite(Number(row.total_yen)) ? Number(row.total_yen) : null,
      rank,
      pdf_path: resolvedPdfPath,
    };
    const current = byExpense.get(expenseId);
    if (!current || rank < current.rank) byExpense.set(expenseId, item);
  }
  const targets = Array.from(byExpense.values()).sort((a, b) => {
    const da = String(a.mf_use_date || "");
    const db = String(b.mf_use_date || "");
    if (da !== db) return da.localeCompare(db);
    return String(a.mf_expense_id).localeCompare(String(b.mf_expense_id));
  });
  return { targets, preSkipped };
}

async function tableRows(page) {
  const selectors = ["table tbody tr", ".table tbody tr", "[role='row']"];
  for (const sel of selectors) {
    const rows = page.locator(sel);
    if ((await rows.count()) > 0) return rows;
  }
  return page.locator("table tbody tr");
}

async function scoreRow(row, target) {
  const text = normalizeText(await row.innerText().catch(() => ""));
  if (!text) return { score: -1, text };
  const amount = parseAnyAmountYen(text);
  const date = parseAnyDate(text);
  if (target.mf_amount_yen != null && amount !== target.mf_amount_yen) return { score: -1, text, amount, date };
  let score = 0;
  if (target.mf_amount_yen != null && amount === target.mf_amount_yen) score += 100;
  if (target.mf_use_date && date === target.mf_use_date) score += 40;
  else if (target.mf_use_date && date) score -= 15;
  const vendorKeys = keywordsForVendor(target.mf_vendor, target.mf_memo);
  const rowText = normalizeToken(text);
  let keywordHits = 0;
  for (const key of vendorKeys) {
    if (rowText.includes(key)) keywordHits += 1;
  }
  score += Math.min(24, keywordHits * 4);
  if (target.order_id && text.includes(target.order_id)) score += 16;
  if (text.includes("編集登録")) score += 8;
  return { score, text, amount, date };
}

async function findBestTargetRow(page, target) {
  const rows = await tableRows(page);
  const count = Math.min(await rows.count(), 250);
  let best = null;
  for (let i = 0; i < count; i++) {
    const row = rows.nth(i);
    const result = await scoreRow(row, target);
    if (result.score < 0) continue;
    if (!best || result.score > best.score) best = { ...result, index: i, row };
  }
  return best;
}

async function waitForEditorOpen(page, timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await isExpenseEditorOpen(page)) return;
    await page.waitForTimeout(200);
  }
  throw new Error("expense_editor_not_opened");
}

async function waitForEditorClose(page, timeoutMs = 20000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const open = await isExpenseEditorOpen(page);
    if (!open) return true;
    await page.waitForTimeout(300);
  }
  return false;
}

async function clickEditRegister(row) {
  const selectors = [
    "button:has-text('編集登録')",
    "a:has-text('編集登録')",
    "input[type='button'][value='編集登録']",
    "button:has-text('詳細')",
    "a:has-text('詳細')",
    "input[type='button'][value='詳細']",
    "button:has-text('編集')",
    "a:has-text('編集')",
  ];
  for (const sel of selectors) {
    const btn = row.locator(sel).first();
    if ((await btn.count()) === 0) continue;
    await btn.click({ timeout: 8000 });
    return sel;
  }
  throw new Error("edit_register_button_not_found");
}

async function resolveEditorRoot(page) {
  const createButton = page.locator(EDITOR_SUBMIT_SELECTOR);
  const bootstrapModal = page.locator("#modal-transaction-edit, .js-ex-transaction-edit-modal").first();
  if (await bootstrapModal.isVisible().catch(() => false)) return bootstrapModal;

  const candidates = [
    page.locator("div[role='dialog']").filter({ has: createButton }).first(),
    page.locator(".ReactModal__Content").filter({ has: createButton }).first(),
    page.locator("form").filter({ has: createButton }).first(),
  ];
  for (const root of candidates) {
    if ((await root.count()) === 0) continue;
    const visible = await root.isVisible().catch(() => false);
    if (visible) return root;
  }
  return page.locator("body");
}

async function firstVisible(locator, maxCount = 12) {
  const count = Math.min(await locator.count(), maxCount);
  for (let i = 0; i < count; i++) {
    const item = locator.nth(i);
    if (await item.isVisible().catch(() => false)) return item;
  }
  return null;
}

async function waitForReceiptAttachUiReady(page, editorRoot, timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    // The receipt uploader exists even if the input itself is visually hidden.
    const input = editorRoot.locator("#ex_transaction_mf_file_content, input[type='file']").first();
    const inputReady = (await input.count()) > 0;

    // Some pages keep a loading backdrop inside the editor.
    const loading = editorRoot.locator("#js-ex-loading-for-modal").first();
    const loadingVisible = (await loading.count()) > 0 && (await loading.isVisible().catch(() => false));

    if (inputReady && !loadingVisible) return;
    await page.waitForTimeout(200);
  }
}

async function waitForReceiptAttached(page, editorRoot, expectedFileName, timeoutMs = 15000) {
  const fileNamePattern = new RegExp(escapeRegExp(expectedFileName), "i");
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const fileNameVisible = await page.getByText(fileNamePattern).first().isVisible().catch(() => false);

    const filenameLabel = editorRoot.locator(".js-receipt-preview__filename, .receipt-preview__filename").first();
    const labelText = await filenameLabel.textContent().catch(() => "");
    const normalizedLabelText = String(labelText || "").trim();
    const labelUpdated =
      Boolean(normalizedLabelText) && !normalizedLabelText.includes("選択されていません") && !normalizedLabelText.includes("未選択");

    // When MF shows an inline filename error, fail fast.
    const filenameError = await editorRoot
      .locator(".js-filename-error-container:not(.hidden), .js-filename-error-container.error:not(.hidden)")
      .first()
      .textContent()
      .catch(() => "");
    if (String(filenameError || "").trim()) return { ok: false, method: "filename_error" };

    const fileInfo = await editorRoot
      .evaluate((root, expectedLower) => {
        const norm = (value) => String(value || "").toLowerCase();
        const inputs = Array.from(root.querySelectorAll("input[type='file']")).filter((input) => input && input.files);
        const files = inputs.flatMap((input) => Array.from(input.files || []));
        const any = files.length > 0;
        const expected = files.some((file) => norm(file?.name).includes(expectedLower));
        return { any, expected };
      }, String(expectedFileName || "").toLowerCase())
      .catch(() => ({ any: false, expected: false }));

    if (fileNameVisible) return { ok: true, method: "filename_visible" };
    if (labelUpdated) return { ok: true, method: "filename_label" };
    if (fileInfo.expected) return { ok: true, method: "editor_input_expected" };
    if (fileInfo.any) return { ok: true, method: "editor_input_any" };
    await page.waitForTimeout(250);
  }
  return { ok: false, method: "timeout" };
}

async function attachReceiptViaDropdown(page, editorRoot, resolved) {
  const menuButton = await firstVisible(
    editorRoot.locator("#file-upload-menu, button, a", { hasText: /領収書を添付/ })
  );
  if (menuButton) {
    await menuButton.click({ timeout: 8000, force: true }).catch(() => {});
    await page.waitForTimeout(150);
  }

  const label = await firstVisible(
    editorRoot.locator("label[for='ex_transaction_mf_file_content'], button, a, li, div, span", { hasText: /ファイルから選択/ })
  );
  if (!label) return false;

  const chooserPromise = page.waitForEvent("filechooser", { timeout: 5000 }).catch(() => null);
  await label.click({ timeout: 8000, force: true }).catch(() => {});
  const chooser = await chooserPromise;
  if (!chooser) return false;
  await chooser.setFiles(resolved);
  return true;
}

async function attachReceiptFile(page, pdfPath) {
  const resolved = path.resolve(pdfPath);
  if (!fs.existsSync(resolved)) throw new Error(`receipt_pdf_not_found: ${resolved}`);
  const expectedFileName = path.basename(resolved);
  const editorRoot = await resolveEditorRoot(page);

  // The bootstrap modal is sometimes considered "open" before the receipt uploader is ready.
  await waitForReceiptAttachUiReady(page, editorRoot, 20000).catch(() => {});

  const attempts = [];
  attempts.push(async () => {
    const receiptInput = editorRoot
      .locator("#ex_transaction_mf_file_content:not([disabled]), input[name='ex_transaction[mf_file][content]']:not([disabled])")
      .first();
    const directInput =
      (await receiptInput.count()) > 0 ? receiptInput : editorRoot.locator("input[type='file']:not([disabled])").first();
    if ((await directInput.count()) === 0) throw new Error("file_input_not_found");
    await directInput.setInputFiles(resolved);
    // Some tenant UIs appear to rely on a bubbling event.
    await editorRoot
      .evaluate((root) => {
        const input = root.querySelector("#ex_transaction_mf_file_content");
        if (!input) return false;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      })
      .catch(() => {});
    return "editor_direct_input";
  });

  attempts.push(async () => {
    const ok = await attachReceiptViaDropdown(page, editorRoot, resolved);
    if (!ok) throw new Error("filechooser_not_opened");
    return "dropdown_filechooser";
  });

  let lastErr = null;
  for (const attempt of attempts) {
    try {
      const attachMethod = await attempt();
      const attached = await waitForReceiptAttached(page, editorRoot, expectedFileName, 30000);
      if (!attached.ok) {
        throw new Error(`receipt_file_attach_not_confirmed:${attachMethod || "unknown"}:${attached.method}`);
      }
      return { attachMethod: attachMethod || "unknown", verifyMethod: attached.method };
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error("receipt_file_attach_failed");
}

async function ensureOcrChecked(page) {
  const byLabel = page.locator("label:has-text('OCR入力') input[type='checkbox']").first();
  if ((await byLabel.count()) > 0) {
    if (!(await byLabel.isChecked())) await byLabel.check({ force: true });
    if (!(await byLabel.isChecked())) throw new Error("ocr_checkbox_not_checked");
    return "label";
  }
  const byAttr = page.locator("input[type='checkbox'][id*='ocr' i], input[type='checkbox'][name*='ocr' i]").first();
  if ((await byAttr.count()) > 0) {
    if (!(await byAttr.isChecked())) await byAttr.check({ force: true });
    if (!(await byAttr.isChecked())) throw new Error("ocr_checkbox_not_checked");
    return "attr";
  }
  const checked = await page
    .evaluate(() => {
      const labels = Array.from(document.querySelectorAll("label"));
      for (const label of labels) {
        if (!(label.textContent || "").includes("OCR入力")) continue;
        let input = label.querySelector("input[type='checkbox']");
        if (!input && label.htmlFor) input = document.getElementById(label.htmlFor);
        if (!input) continue;
        if (!input.checked) input.click();
        return Boolean(input.checked);
      }
      return false;
    })
    .catch(() => false);
  if (!checked) throw new Error("ocr_checkbox_not_found");
  return "eval";
}

async function clickCreate(page) {
  const editorRoot = await resolveEditorRoot(page);
  const createButton = editorSubmitLocator(editorRoot);
  if ((await createButton.count()) === 0) throw new Error("create_button_not_found");
  await createButton.click({ timeout: 10000 });
  const closed = await waitForEditorClose(page, 20000);
  if (!closed) throw new Error("editor_not_closed_after_create");
}

async function closeEditorBestEffort(page) {
  // Bootstrap modal close (expense report edit page)
  const bootstrapModal = page.locator("#modal-transaction-edit, .js-ex-transaction-edit-modal").first();
  if (await bootstrapModal.isVisible().catch(() => false)) {
    const closeCandidates = [
      "[data-dismiss='modal']",
      "#modal-close-btn",
      ".js-modal-close-button",
      "button:has-text('閉じる')",
      "button:has-text('キャンセル')",
    ];
    for (const sel of closeCandidates) {
      const el = bootstrapModal.locator(sel).first();
      if ((await el.count()) === 0) continue;
      await el.click({ timeout: 2000 }).catch(() => {});
      await page.waitForTimeout(150);
      if (!(await bootstrapModal.isVisible().catch(() => false))) return;
    }
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(150);
    if (!(await bootstrapModal.isVisible().catch(() => false))) return;
  }

  const closeCandidates = [
    "button[aria-label='閉じる']",
    "button:has-text('閉じる')",
    "a:has-text('閉じる')",
    ".modal .close",
    ".ReactModal__Content button[aria-label='close']",
  ];
  for (const sel of closeCandidates) {
    const el = page.locator(sel).first();
    if ((await el.count()) === 0) continue;
    await el.click({ timeout: 2000 }).catch(() => {});
    await page.waitForTimeout(200);
  }

  // Always try Esc as last resort.
  await page.keyboard.press("Escape").catch(() => {});
  await waitForEditorClose(page, 3000).catch(() => {});
}

async function main() {
  const args = parseArgs(process.argv);
  const storageState = args["storage-state"];
  const outgoUrl = args["outgo-url"];
  const reportJson = args["report-json"];
  const outJson = args["out-json"];
  const auditJsonl = args["audit-jsonl"] ? String(args["audit-jsonl"]) : "";
  const debugDir = args["debug-dir"];
  const headed = args.headed !== false;
  const slowMoMs = Number.parseInt(String(args["slow-mo-ms"] || "0"), 10);
  const year = Number.parseInt(String(args.year || "0"), 10);
  const month = Number.parseInt(String(args.month || "0"), 10);
  const authHandoff = Boolean(args["auth-handoff"]);

  if (!storageState) throw new Error("Missing --storage-state");
  if (!outgoUrl) throw new Error("Missing --outgo-url");
  if (!reportJson) throw new Error("Missing --report-json");
  if (!outJson) throw new Error("Missing --out-json");
  if (!year || !month) throw new Error("Missing --year/--month");
  if (!fs.existsSync(reportJson)) throw new Error(`report json not found: ${reportJson}`);

  ensureDir(path.dirname(outJson));
  if (debugDir) ensureDir(debugDir);
  if (auditJsonl) ensureDir(path.dirname(auditJsonl));

  const { targets, preSkipped } = loadTargets(reportJson, year, month);
  const results = [...preSkipped];
  if (targets.length === 0) {
    const payload = {
      status: "success",
      data: {
        out_json: outJson,
        audit_jsonl: auditJsonl || null,
        targets_total: 0,
        attempted: 0,
        created: 0,
        skipped: preSkipped.length,
        failed: 0,
        results,
      },
    };
    fs.writeFileSync(outJson, JSON.stringify(payload, null, 2), "utf-8");
    console.log(JSON.stringify(payload));
    return;
  }

  const browser = await chromium.launch({ headless: !headed, slowMo: slowMoMs });
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  let created = 0;
  let failed = 0;
  let attempted = 0;
  let skippedAlreadyAttached = 0;
  const runStartedAt = Date.now();
  let lastHeartbeatAt = 0;
  try {
    await page.goto(outgoUrl, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});
    await ensureAuthenticated(page, authHandoff, "MF Cloud outgo_input");

    for (let i = 0; i < targets.length; i++) {
      const target = targets[i];
      const safeId = safeFilePart(target.mf_expense_id || `idx_${i + 1}`);
      attempted += 1;
      let stage = "start";

      appendJsonl(auditJsonl, {
        ts: nowIso(),
        action: "target_start",
        mf_expense_id: target.mf_expense_id,
        mf_use_date: target.mf_use_date || null,
        mf_amount_yen: target.mf_amount_yen ?? null,
        mf_vendor: target.mf_vendor || null,
        mf_memo: target.mf_memo || null,
        order_id: target.order_id || null,
        order_source: target.order_source || null,
        order_date: target.order_date || null,
        order_total_yen: target.order_total_yen ?? null,
        pdf_path: target.pdf_path || null,
        idx: i + 1,
        total: targets.length,
      });

      console.error(
        `[mf_draft] start ${target.mf_expense_id} date=${target.mf_use_date || "unknown"} amount=${target.mf_amount_yen ?? "unknown"}`
      );
      try {
        if (Date.now() - lastHeartbeatAt > 20000) {
          lastHeartbeatAt = Date.now();
          console.error(
            `[mf_draft] progress idx=${i + 1}/${targets.length} attempted=${attempted} created=${created} failed=${failed} skipped=${preSkipped.length + skippedAlreadyAttached} elapsed_s=${Math.round(
              (Date.now() - runStartedAt) / 1000
            )}`
          );
        }

        await ensureAuthenticated(page, authHandoff, "MF Cloud outgo_input");
        await page.bringToFront().catch(() => {});
        await page.waitForLoadState("domcontentloaded").catch(() => {});

        stage = "find_matching_row";
        const best = await findBestTargetRow(page, target);
        if (!best || !best.row || best.score < 100) {
          throw new Error("matching_row_not_found");
        }
        appendJsonl(auditJsonl, {
          ts: nowIso(),
          action: "matching_row_found",
          mf_expense_id: target.mf_expense_id,
          row_score: best.score,
          row_date: best.date || null,
          row_amount_yen: best.amount ?? null,
          row_preview: truncateString(best.text, 180),
        });

        stage = "open_editor";
        const clickSel = await clickEditRegister(best.row);
        await waitForEditorOpen(page, 15000);

        // If a receipt is already attached on MF, do not re-attach.
        // This prevents duplicate attachments when the extraction/reconcile input is stale or MF UI detection is imperfect.
        stage = "check_already_attached";
        const editorRoot = await resolveEditorRoot(page);
        const alreadyAttached = await hasAnyReceiptAlreadyAttached(editorRoot);
        if (alreadyAttached.ok) {
          skippedAlreadyAttached += 1;
          results.push({
            mf_expense_id: target.mf_expense_id,
            status: "skipped",
            reason: "already_has_receipt",
            stage,
            row_score: best.score,
            row_date: best.date || null,
            row_amount_yen: best.amount ?? null,
            pdf_path: target.pdf_path,
            click_selector: clickSel,
            detected: { method: alreadyAttached.method, filename: alreadyAttached.filename || null },
            order_id: target.order_id || null,
          });
          appendJsonl(auditJsonl, {
            ts: nowIso(),
            action: "target_skipped",
            mf_expense_id: target.mf_expense_id,
            reason: "already_has_receipt",
            stage,
            row_score: best.score,
            row_date: best.date || null,
            row_amount_yen: best.amount ?? null,
            click_selector: clickSel,
            detected: { method: alreadyAttached.method, filename: alreadyAttached.filename || null },
          });
          console.error(`[mf_draft] skipped ${target.mf_expense_id} reason=already_has_receipt`);
          await closeEditorBestEffort(page);
          await page.waitForTimeout(300);
          continue;
        }

        stage = "attach_receipt";
        const attachResult = await attachReceiptFile(page, target.pdf_path);
        stage = "ensure_ocr";
        const ocrMethod = await ensureOcrChecked(page);
        stage = "click_create";
        await clickCreate(page);
        created += 1;
        results.push({
          mf_expense_id: target.mf_expense_id,
          status: "created",
          stage,
          row_score: best.score,
          row_date: best.date || null,
          row_amount_yen: best.amount ?? null,
          pdf_path: target.pdf_path,
          click_selector: clickSel,
          attach_method: attachResult.attachMethod,
          attach_verify: attachResult.verifyMethod,
          ocr_method: ocrMethod,
          order_id: target.order_id || null,
        });
        appendJsonl(auditJsonl, {
          ts: nowIso(),
          action: "target_created",
          mf_expense_id: target.mf_expense_id,
          stage,
          row_score: best.score,
          row_date: best.date || null,
          row_amount_yen: best.amount ?? null,
          pdf_path: target.pdf_path,
          click_selector: clickSel,
          attach_method: attachResult.attachMethod,
          attach_verify: attachResult.verifyMethod,
          ocr_method: ocrMethod,
          order_id: target.order_id || null,
        });
        console.error(`[mf_draft] created ${target.mf_expense_id}`);
        await page.waitForTimeout(600);
      } catch (err) {
        failed += 1;
        const message = String(err && err.message ? err.message : err);
        const normalized = normalizeDraftError(message);
        results.push({
          mf_expense_id: target.mf_expense_id,
          status: "failed",
          reason: normalized.reason,
          detail: normalized.detail,
          stage,
          pdf_path: target.pdf_path,
          order_id: target.order_id || null,
        });
        appendJsonl(auditJsonl, {
          ts: nowIso(),
          action: "target_failed",
          mf_expense_id: target.mf_expense_id,
          reason: normalized.reason,
          detail: truncateString(normalized.detail, 800),
          stage,
          pdf_path: target.pdf_path || null,
          order_id: target.order_id || null,
        });
        console.error(`[mf_draft] failed ${target.mf_expense_id} reason=${normalized.reason} detail=${message}`);
        if (debugDir) {
          await writeDebug(page, debugDir, `mf_draft_${safeId}_failed`).catch(() => {});
        }
        await closeEditorBestEffort(page);
      }
    }
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }

  const summary = {
    status: failed > 0 ? "partial_success" : "success",
    data: {
      out_json: outJson,
      audit_jsonl: auditJsonl || null,
      // Treat "already has receipt" as out-of-scope for creation (user confirmed no mis-attachments by others).
      targets_total: Math.max(0, targets.length - skippedAlreadyAttached),
      attempted,
      created,
      skipped: preSkipped.length + skippedAlreadyAttached,
      skipped_already_has_receipt: skippedAlreadyAttached,
      failed,
      results,
    },
  };
  fs.writeFileSync(outJson, JSON.stringify(summary, null, 2), "utf-8");
  console.log(JSON.stringify(summary));
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});

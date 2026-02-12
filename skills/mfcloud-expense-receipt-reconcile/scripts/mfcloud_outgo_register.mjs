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
    "validation_failed",
    "ocr_checkbox_not_checked",
    "ocr_checkbox_not_found",
    "file_input_not_found",
    "filechooser_not_opened",
    "receipt_file_attach_failed",
    "overwrite_confirm_unresolved",
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
  // Some tenants keep a filename-like label even when not attached.
  // Treat filename text alone as untrusted; require an additional strong signal.
  const inspected = await editorRoot
    .evaluate((root) => {
      const txt = (v) => String(v || "").replace(/\s+/g, " ").trim();
      const placeholders = ["選択されていません", "未選択", "選択してください"];

      const filenameNode = root.querySelector(".js-receipt-preview__filename, .receipt-preview__filename");
      const filename = txt(filenameNode?.textContent || "");
      const hasFilename = Boolean(filename) && !placeholders.some((p) => filename.includes(p));

      const isStrongDeleteText = (v) => /削除|解除|取り消し|取消|remove|delete|clear/i.test(txt(v));
      const isStrongDownloadText = (v) => /ダウンロード|download|証憑|添付|領収書/i.test(txt(v));

      const regions = Array.from(
        root.querySelectorAll(
          [
            ".js-receipt-preview",
            ".receipt-preview",
            "[class*='receipt']",
            "[id*='receipt']",
            "[class*='attachment']",
            "[id*='attachment']",
          ].join(", ")
        )
      );
      const scanRoots = regions.length ? regions : [root];

      let hasDeleteControl = false;
      let hasEvidenceLink = false;
      for (const scope of scanRoots) {
        const controls = Array.from(scope.querySelectorAll("button, a, input[type='button'], input[type='submit']"));
        for (const el of controls) {
          const text = txt(el.textContent || el.getAttribute("value") || "");
          const href = txt(el.getAttribute("href") || el.getAttribute("data-url") || el.getAttribute("data-href") || "");
          if (isStrongDeleteText(text)) hasDeleteControl = true;
          if (isStrongDownloadText(text) || /mf_file|attachment|download|receipt|evidence/i.test(href)) {
            hasEvidenceLink = true;
          }
        }
      }

      const hiddenInputs = Array.from(root.querySelectorAll("input[type='hidden']"));
      const hasHiddenFileId = hiddenInputs.some((el) => {
        const name = txt(el.getAttribute("name") || "");
        const id = txt(el.id || "");
        const key = `${name} ${id}`.toLowerCase();
        if (!/(mf_file|receipt|attachment|evidence)/i.test(key)) return false;
        if (/content/i.test(key)) return false;
        const value = txt(el.getAttribute("value") || "");
        return Boolean(value) && value !== "0";
      });

      return {
        filename: filename || null,
        hasFilename,
        hasDeleteControl,
        hasEvidenceLink,
        hasHiddenFileId,
      };
    })
    .catch(() => ({
      filename: null,
      hasFilename: false,
      hasDeleteControl: false,
      hasEvidenceLink: false,
      hasHiddenFileId: false,
    }));

  const strongSignals = [];
  if (inspected.hasHiddenFileId) strongSignals.push("hidden_file_id");
  if (inspected.hasDeleteControl) strongSignals.push("delete_control");
  if (inspected.hasEvidenceLink) strongSignals.push("evidence_link");

  if (inspected.hasFilename && strongSignals.length > 0) {
    return {
      ok: true,
      method: `filename+${strongSignals.join("+")}`,
      filename: inspected.filename || null,
      signals: strongSignals,
    };
  }
  if (inspected.hasHiddenFileId) {
    return {
      ok: true,
      method: "hidden_file_id",
      filename: inspected.filename || null,
      signals: strongSignals,
    };
  }
  if (inspected.hasFilename) {
    return {
      ok: false,
      method: "filename_only_untrusted",
      filename: inspected.filename || null,
      signals: strongSignals,
    };
  }
  return {
    ok: false,
    method: "no_attachment_signal",
    filename: inspected.filename || null,
    signals: strongSignals,
  };
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
      match_strategy: String(row.match_strategy || "").trim() || "amount_date_exact",
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

function isOverwritePromptText(text) {
  const t = normalizeText(text);
  if (!t) return false;
  if (/内容.*上書き.*しますか/.test(t)) return true;
  if (/修正候補/.test(t) && /上書き/.test(t)) return true;
  if (/上書き/.test(t) && /(内容|候補|入力|反映)/.test(t)) return true;
  return false;
}

async function findOverwriteConfirmButton(scope) {
  if (!scope || typeof scope.locator !== "function") return null;
  const candidates = [
    scope.locator("button, a", { hasText: /^はい$/ }).first(),
    scope.locator("button, a", { hasText: /^ok$/i }).first(),
    scope.locator("button, a", { hasText: /上書き|保存|実行|更新|続行|確認|反映/ }).first(),
    scope.locator("input[type='button'][value='はい'], input[type='submit'][value='はい']").first(),
    scope.locator("input[type='button'][value='OK' i], input[type='submit'][value='OK' i]").first(),
    scope.locator("input[type='button'][value*='上書き'], input[type='submit'][value*='上書き']").first(),
    scope.locator("input[type='button'][value*='更新'], input[type='submit'][value*='更新']").first(),
  ];
  for (const locator of candidates) {
    if ((await locator.count()) === 0) continue;
    if (!(await locator.isVisible().catch(() => false))) continue;
    return locator;
  }
  return null;
}

async function findVisibleOverwritePrompt(page, maxCount = 14) {
  const containers = page.locator(
    [
      "[role='dialog']",
      "[aria-modal='true']",
      ".modal",
      ".MuiDialog-root",
      ".ReactModal__Content",
      ".swal2-popup",
      ".toast",
      "[class*='toast']",
      "[class*='notification']",
      "[class*='confirm']",
    ].join(", ")
  );
  const count = Math.min(await containers.count().catch(() => 0), maxCount);
  for (let i = 0; i < count; i++) {
    const container = containers.nth(i);
    if (!(await container.isVisible().catch(() => false))) continue;
    const text = normalizeText(await container.innerText().catch(() => ""));
    if (!isOverwritePromptText(text)) continue;
    return { container, text, source: "container" };
  }

  const labels = [
    page.getByText(/内容.*上書き.*しますか/).first(),
    page.getByText(/修正候補/).first(),
    page.getByText(/上書きしますか/).first(),
  ];
  for (const label of labels) {
    if ((await label.count()) === 0) continue;
    if (!(await label.isVisible().catch(() => false))) continue;
    const labelText = normalizeText(await label.innerText().catch(() => ""));
    if (!isOverwritePromptText(labelText)) continue;
    const ancestor = label.locator("xpath=ancestor::*[self::div or self::section or self::dialog or self::form][1]");
    const container = (await ancestor.count()) > 0 ? ancestor.first() : page.locator("body");
    const containerText = normalizeText(await container.innerText().catch(() => labelText));
    return { container, text: containerText || labelText, source: "text_anchor" };
  }

  return null;
}

async function acceptOverwriteConfirmationIfNeeded(page, timeoutMs = 4500) {
  const start = Date.now();
  let promptSeen = false;
  let promptPreview = "";

  while (Date.now() - start < timeoutMs) {
    const prompt = await findVisibleOverwritePrompt(page);
    if (prompt) {
      promptSeen = true;
      promptPreview = truncateString(prompt.text || promptPreview || "", 200);
      const confirmButton = (await findOverwriteConfirmButton(prompt.container)) || (await findOverwriteConfirmButton(page));
      if (confirmButton) {
        await confirmButton.click({ timeout: 2000, force: true }).catch(() => {});
        await page.waitForTimeout(180);
        const remaining = await findVisibleOverwritePrompt(page);
        if (!remaining) {
          return {
            promptSeen: true,
            resolved: true,
            method: "confirm_button",
            prompt: promptPreview || null,
          };
        }
      }
    }
    await page.waitForTimeout(100);
  }

  const remaining = await findVisibleOverwritePrompt(page);
  if (remaining) {
    return {
      promptSeen: true,
      resolved: false,
      method: "prompt_still_visible",
      prompt: truncateString(remaining.text || promptPreview || "", 200),
    };
  }
  return {
    promptSeen,
    resolved: true,
    method: promptSeen ? "prompt_disappeared" : "not_present",
    prompt: promptPreview || null,
  };
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

async function attachReceiptFile(page, pdfPath, options = {}) {
  const resolved = path.resolve(pdfPath);
  if (!fs.existsSync(resolved)) throw new Error(`receipt_pdf_not_found: ${resolved}`);
  const expectedFileName = path.basename(resolved);
  const editorRoot = await resolveEditorRoot(page);
  const overwriteTimeoutMs = Math.max(1500, Number.parseInt(String(options?.overwriteTimeoutMs || "4500"), 10) || 4500);

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
      const overwriteConfirm = await acceptOverwriteConfirmationIfNeeded(page, overwriteTimeoutMs);
      if (overwriteConfirm.promptSeen && !overwriteConfirm.resolved) {
        throw new Error(`overwrite_confirm_unresolved:${overwriteConfirm.method}`);
      }
      const attached = await waitForReceiptAttached(page, editorRoot, expectedFileName, 30000);
      if (!attached.ok) {
        throw new Error(`receipt_file_attach_not_confirmed:${attachMethod || "unknown"}:${attached.method}`);
      }
      return {
        attachMethod: attachMethod || "unknown",
        verifyMethod: attached.method,
        overwriteConfirm,
      };
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

function buildSupplementMemoText(target) {
  if (String(target?.match_strategy || "") !== "date_vendor_fallback") return "";
  const useDate = String(target?.mf_use_date || "").trim();
  const useDateLabel = useDate ? useDate.replace(/-/g, "/") : "不明";
  const vendorLabel = String(target?.mf_vendor || "").trim() || "不明";
  const orderRef = String(target?.order_id || "").trim();
  const base = `利用日（${useDateLabel}）・請求先（${vendorLabel}）が一致するため、同一取引として領収書を手動添付して保存。`;
  if (orderRef) return `${base}注文番号/明細ID（${orderRef}）確認済み。`;
  return `${base}注文番号/明細IDは領収書側で確認済み。`;
}

async function appendSupplementMemoIfNeeded(page, target, auditJsonl) {
  const memoText = buildSupplementMemoText(target);
  if (!memoText) return { applied: false, reason: "not_required", field: null };

  const editorRoot = await resolveEditorRoot(page);
  const memoField = await firstVisible(
    editorRoot.locator(
      [
        "textarea[name*='memo' i]",
        "textarea[id*='memo' i]",
        "textarea[name*='note' i]",
        "textarea[id*='note' i]",
        "textarea[name*='comment' i]",
        "textarea[id*='comment' i]",
        "textarea[name*='remark' i]",
        "textarea[id*='remark' i]",
        "textarea[name*='summary' i]",
        "textarea[id*='summary' i]",
        "textarea[name*='description' i]",
        "textarea[id*='description' i]",
        "textarea[name*='content' i]",
        "textarea[id*='content' i]",
        "input[type='text'][name*='memo' i]",
        "input[type='text'][id*='memo' i]",
        "input[type='text'][name*='note' i]",
        "input[type='text'][id*='note' i]",
        "input[type='text'][name*='comment' i]",
        "input[type='text'][id*='comment' i]",
      ].join(", ")
    ),
    24
  );
  if (!memoField) {
    appendJsonl(auditJsonl, {
      ts: nowIso(),
      action: "supplement_memo_skipped",
      mf_expense_id: target?.mf_expense_id || null,
      reason: "field_not_found",
      match_strategy: target?.match_strategy || null,
    });
    return { applied: false, reason: "field_not_found", field: null };
  }

  const fieldName = await memoField
    .evaluate((el) => {
      const name = el?.getAttribute?.("name") || "";
      const id = el?.id || "";
      return name || id || "";
    })
    .catch(() => "");
  const currentValue = await memoField.inputValue().catch(() =>
    memoField.evaluate((el) => String(el?.value || "")).catch(() => "")
  );
  if (normalizeText(currentValue).includes(normalizeText(memoText))) {
    return { applied: false, reason: "already_present", field: fieldName || null };
  }

  const merged = String(currentValue || "").trim() ? `${String(currentValue || "").trim()}\n${memoText}` : memoText;
  let writeOk = true;
  try {
    await memoField.fill(merged, { timeout: 6000 });
  } catch {
    writeOk = await memoField
      .evaluate((el, value) => {
        if (!el) return false;
        el.focus();
        el.value = String(value || "");
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.blur();
        return true;
      }, merged)
      .catch(() => false);
  }
  if (!writeOk) {
    appendJsonl(auditJsonl, {
      ts: nowIso(),
      action: "supplement_memo_skipped",
      mf_expense_id: target?.mf_expense_id || null,
      reason: "write_failed",
      field: fieldName || null,
      match_strategy: target?.match_strategy || null,
    });
    return { applied: false, reason: "write_failed", field: fieldName || null };
  }

  const updatedValue = await memoField.inputValue().catch(() =>
    memoField.evaluate((el) => String(el?.value || "")).catch(() => "")
  );
  const applied = normalizeText(updatedValue).includes(normalizeText(memoText));
  appendJsonl(auditJsonl, {
    ts: nowIso(),
    action: applied ? "supplement_memo_applied" : "supplement_memo_unconfirmed",
    mf_expense_id: target?.mf_expense_id || null,
    field: fieldName || null,
    match_strategy: target?.match_strategy || null,
    memo_preview: truncateString(memoText, 200),
  });
  return { applied, reason: applied ? "applied" : "unconfirmed", field: fieldName || null };
}

function pickBestOption(options, preferTexts) {
  const cleaned = (options || [])
    .map((o) => ({ value: String(o?.value || ""), text: String(o?.text || "").trim() }))
    .filter((o) => o.value && o.value !== "0" && o.text && !/選択|未選択|---/i.test(o.text));

  const prefs = (preferTexts || []).map((t) => String(t || "").trim()).filter(Boolean);
  for (const pref of prefs) {
    const hit = cleaned.find((o) => o.text.includes(pref));
    if (hit) return hit;
  }
  return cleaned[0] || null;
}

async function setSelectValue(selectLocator, value) {
  if (!value) return false;
  try {
    await selectLocator.selectOption({ value: String(value) });
    return true;
  } catch {
    const ok = await selectLocator
      .evaluate((el, v) => {
        if (!el) return false;
        el.value = String(v);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }, String(value))
      .catch(() => false);
    return ok;
  }
}

async function collectEditorValidationErrors(editorRoot) {
  const errors = await editorRoot
    .evaluate((root) => {
      const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };

      const candidates = new Set();
      const selectors = [
        ".error",
        ".errors",
        ".error-message",
        ".field_with_errors",
        "[aria-invalid='true']",
        ".is-invalid",
        ".invalid-feedback",
      ];
      for (const sel of selectors) {
        for (const el of Array.from(root.querySelectorAll(sel))) {
          if (!isVisible(el)) continue;
          const t = (el.textContent || "").trim();
          if (t && t.length <= 240) candidates.add(t);
        }
      }
      return Array.from(candidates).slice(0, 20);
    })
    .catch(() => []);
  return (errors || []).map((x) => String(x || "").trim()).filter(Boolean);
}

async function autofillSelectIfEmpty(selectLocator, fieldName, preferTexts) {
  if ((await selectLocator.count()) === 0) return null;
  const sel = selectLocator.first();
  const current = await sel.evaluate((el) => String(el?.value || "")).catch(() => "");
  if (current && current !== "0") return null;

  const options = await sel
    .evaluate((el) =>
      Array.from(el.options || []).map((o) => ({ value: String(o?.value || ""), text: String(o?.textContent || "") }))
    )
    .catch(() => []);
  const picked = pickBestOption(options, preferTexts);
  if (!picked) return null;

  const ok = await setSelectValue(sel, picked.value);
  if (!ok) return null;
  return { field: fieldName, value: picked.value, text: picked.text };
}

function inferAutofillNeedsFromErrors(errors) {
  const text = Array.isArray(errors) ? errors.join(" ") : String(errors || "");
  const t = String(text || "");
  const has = (re) => re.test(t);

  return {
    account_title: has(/経費科目|勘定科目|科目|カテゴリ|分類/),
    department: has(/部門/),
    project: has(/プロジェクト/),
    tax: has(/税|税区分|税率|インボイス/),
    // Generic fallback for "something is required but unknown"
    any_required_select: has(/必須|入力してください|選択してください/),
  };
}

async function autofillAllEmptySelects(page, editorRoot, selects, fieldPrefix, preferTexts) {
  const out = [];
  const max = Math.min(await selects.count().catch(() => 0), 10);
  for (let i = 0; i < max; i++) {
    const sel = selects.nth(i);
    const visible = await sel.isVisible().catch(() => false);
    if (!visible) continue;

    const idOrName = await sel.evaluate((el) => el?.getAttribute("name") || el?.id || "").catch(() => "");
    const fieldName = idOrName ? `${fieldPrefix}:${String(idOrName)}` : fieldPrefix;
    const filled = await autofillSelectIfEmpty(sel, fieldName, preferTexts);
    if (filled) out.push(filled);
  }
  await page.bringToFront().catch(() => {});
  return out;
}

async function autofillRequiredFields(page, editorRoot, options) {
  const out = [];
  const preferAccount = options?.accountTitlePreferTexts || ["雑費", "その他"];
  const validationErrors = Array.isArray(options?.validationErrors) ? options.validationErrors : [];
  const needs = inferAutofillNeedsFromErrors(validationErrors);

  // Account title / expense category is the most common required field.
  const accountTitleSelect = editorRoot.locator(
    "select[name*='account_title' i], select[id*='account_title' i], select[name*='accountTitle' i], select[name*='account_item' i], select[name*='account_item_id' i]"
  );
  if (needs.account_title || needs.any_required_select || validationErrors.length === 0) {
    const accountFilled = await autofillSelectIfEmpty(accountTitleSelect, "account_title", preferAccount);
    if (accountFilled) out.push(accountFilled);
  }

  // Some tenants require department/project/tax category; fill first reasonable option if empty.
  const genericSelects = [
    { key: "department", sel: "select[name*='department' i], select[id*='department' i]" },
    { key: "project", sel: "select[name*='project' i], select[id*='project' i]" },
    { key: "tax", sel: "select[name*='tax' i], select[id*='tax' i]" },
  ];
  for (const g of genericSelects) {
    if (needs[g.key] || needs.any_required_select) {
      const filled = await autofillSelectIfEmpty(editorRoot.locator(g.sel), g.key, []);
      if (filled) out.push(filled);
    }
  }

  // If there are still visibly-invalid selects, try to fill them as well.
  const invalidSelects = editorRoot.locator("select[aria-invalid='true'], select.is-invalid");
  out.push(...(await autofillAllEmptySelects(page, editorRoot, invalidSelects, "invalid_select", [])));

  // As a last resort, fill selects that declare required/aria-required and are visible.
  // This is restricted to selects (no text inputs) to avoid accidental data entry.
  const requiredSelects = editorRoot.locator("select[required], select[aria-required='true'], select[data-required='true']");
  out.push(...(await autofillAllEmptySelects(page, editorRoot, requiredSelects, "required_select", [])));

  // Sometimes the focus is lost; keep editor in front.
  await page.bringToFront().catch(() => {});
  return out;
}

async function clickCreateAttempt(page) {
  const editorRoot = await resolveEditorRoot(page);
  const createButton = editorSubmitLocator(editorRoot);
  if ((await createButton.count()) === 0) throw new Error("create_button_not_found");
  await createButton.click({ timeout: 10000 });

  // If validation fails, MF keeps the editor open and shows error text quickly.
  await page.waitForTimeout(1200);
  if (!(await isExpenseEditorOpen(page))) return { ok: true, errors: [] };

  const errors = await collectEditorValidationErrors(editorRoot);
  if (errors.length > 0) return { ok: false, errors };

  const closed = await waitForEditorClose(page, 20000);
  return closed ? { ok: true, errors: [] } : { ok: false, errors: [] };
}

async function clickCreateWithAutofill(page, target, auditJsonl, opts) {
  const enableAutofill = opts?.enableAutofill !== false;
  const accountTitlePreferTexts = (opts?.accountTitlePreferTexts || []).filter(Boolean);
  const actions = [];

  for (let attempt = 1; attempt <= 3; attempt++) {
    const res = await clickCreateAttempt(page);
    if (res.ok) return { attempts: attempt, autofill: actions };

    appendJsonl(auditJsonl, {
      ts: nowIso(),
      action: "create_validation_failed",
      mf_expense_id: target?.mf_expense_id || null,
      attempt,
      errors: res.errors,
    });

    if (!enableAutofill) break;
    const editorRoot = await resolveEditorRoot(page);
    const filled = await autofillRequiredFields(page, editorRoot, {
      accountTitlePreferTexts: accountTitlePreferTexts.length ? accountTitlePreferTexts : undefined,
      validationErrors: res.errors,
    });
    if (filled.length === 0) break;
    actions.push(...filled);
    appendJsonl(auditJsonl, {
      ts: nowIso(),
      action: "autofill_required_fields",
      mf_expense_id: target?.mf_expense_id || null,
      attempt,
      filled,
    });
  }

  throw new Error("validation_failed");
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
  const enableAutofill =
    !(args["no-autofill"] === true) && !String(args["autofill"] || "").toLowerCase().startsWith("f"); // allow --autofill false
  const autofillAccountTitle = args["autofill-account-title"] ? String(args["autofill-account-title"]).trim() : "";
  const onlyExpenseIdRaw = args["only-expense-id"] ? String(args["only-expense-id"]) : "";
  const onlyExpenseIds = onlyExpenseIdRaw
    .split(",")
    .map((x) => String(x || "").trim())
    .filter(Boolean);
  const maxTargets = Number.parseInt(String(args["max-targets"] || "0"), 10);
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

  const loaded = loadTargets(reportJson, year, month);
  let targets = loaded.targets;
  let preSkipped = loaded.preSkipped;

  if (onlyExpenseIds.length) {
    const allow = new Set(onlyExpenseIds);
    targets = targets.filter((t) => allow.has(String(t.mf_expense_id || "")));
    preSkipped = preSkipped.filter((r) => allow.has(String(r.mf_expense_id || "")));
  }
  if (Number.isFinite(maxTargets) && maxTargets > 0) {
    targets = targets.slice(0, maxTargets);
  }

  const results = [...preSkipped];
  if (targets.length === 0) {
    const payload = {
      status: "success",
      data: {
        out_json: outJson,
        audit_jsonl: auditJsonl || null,
        only_expense_ids: onlyExpenseIds.length ? onlyExpenseIds : null,
        max_targets: Number.isFinite(maxTargets) && maxTargets > 0 ? maxTargets : null,
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
  let activeExpenseIdForDialog = null;
  page.on("dialog", async (dialog) => {
    const message = normalizeText(dialog.message() || "");
    const kind = String(dialog.type() || "");
    const isOverwrite = isOverwritePromptText(message);
    try {
      if (isOverwrite) {
        await dialog.accept();
        appendJsonl(auditJsonl, {
          ts: nowIso(),
          action: "overwrite_dialog_accepted",
          mf_expense_id: activeExpenseIdForDialog || null,
          dialog_type: kind || null,
          message: truncateString(message, 200),
        });
      } else {
        await dialog.dismiss();
      }
    } catch {
      // ignore dialog races
    }
  });

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
      activeExpenseIdForDialog = target.mf_expense_id || null;
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
        match_strategy: target.match_strategy || null,
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

        stage = "ensure_ocr";
        const ocrMethod = await ensureOcrChecked(page);
        stage = "confirm_overwrite_after_ocr";
        const overwriteAfterOcr = await acceptOverwriteConfirmationIfNeeded(page, 4500);
        if (overwriteAfterOcr.promptSeen && !overwriteAfterOcr.resolved) {
          throw new Error(`overwrite_confirm_unresolved:${overwriteAfterOcr.method}`);
        }
        appendJsonl(auditJsonl, {
          ts: nowIso(),
          action: "overwrite_confirm_after_ocr",
          mf_expense_id: target.mf_expense_id,
          prompt_seen: overwriteAfterOcr.promptSeen,
          resolved: overwriteAfterOcr.resolved,
          method: overwriteAfterOcr.method,
          prompt: overwriteAfterOcr.prompt || null,
        });
        stage = "attach_receipt";
        const attachResult = await attachReceiptFile(page, target.pdf_path, { overwriteTimeoutMs: 4500 });
        stage = "confirm_overwrite_after_attach";
        const lateOverwriteAfterAttach = await acceptOverwriteConfirmationIfNeeded(page, 2500);
        if (lateOverwriteAfterAttach.promptSeen && !lateOverwriteAfterAttach.resolved) {
          throw new Error(`overwrite_confirm_unresolved:${lateOverwriteAfterAttach.method}`);
        }
        const overwriteAfterAttach = lateOverwriteAfterAttach.promptSeen
          ? lateOverwriteAfterAttach
          : attachResult?.overwriteConfirm || { promptSeen: false, resolved: true, method: "not_present", prompt: null };
        appendJsonl(auditJsonl, {
          ts: nowIso(),
          action: "overwrite_confirm_after_attach",
          mf_expense_id: target.mf_expense_id,
          prompt_seen: Boolean(overwriteAfterAttach.promptSeen),
          resolved: Boolean(overwriteAfterAttach.resolved),
          method: overwriteAfterAttach.method || "not_present",
          prompt: overwriteAfterAttach.prompt || null,
        });
        stage = "write_supplement_memo";
        const supplementMemo = await appendSupplementMemoIfNeeded(page, target, auditJsonl);
        stage = "click_create";
        const createResult = await clickCreateWithAutofill(page, target, auditJsonl, {
          enableAutofill,
          accountTitlePreferTexts: autofillAccountTitle ? [autofillAccountTitle, "雑費", "その他"] : ["雑費", "その他"],
        });
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
          overwrite_after_ocr: overwriteAfterOcr.method,
          overwrite_after_attach: overwriteAfterAttach.method || "not_present",
          ocr_method: ocrMethod,
          supplement_memo: supplementMemo.reason,
          supplement_memo_field: supplementMemo.field || null,
          autofill: createResult.autofill.length ? createResult.autofill : undefined,
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
          overwrite_after_ocr: overwriteAfterOcr.method,
          overwrite_after_attach: overwriteAfterAttach.method || "not_present",
          ocr_method: ocrMethod,
          supplement_memo: supplementMemo.reason,
          supplement_memo_field: supplementMemo.field || null,
          autofill: createResult.autofill.length ? createResult.autofill : undefined,
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
      } finally {
        activeExpenseIdForDialog = null;
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
      only_expense_ids: onlyExpenseIds.length ? onlyExpenseIds : null,
      max_targets: Number.isFinite(maxTargets) && maxTargets > 0 ? maxTargets : null,
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

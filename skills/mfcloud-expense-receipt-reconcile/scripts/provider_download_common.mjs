#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";
import { ensureDir, safeFilePart, writeDebug } from "./mjs_common.mjs";

function isLoginUrl(url) {
  return /sign[_-]?in|login|auth|account\/signin|session/i.test(url || "");
}

function isChallengeUrl(url) {
  return /captcha|challenge|verify|cloudflare|arkose|hcaptcha|recaptcha/i.test(url || "");
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function isPageUsable(page) {
  return Boolean(page) && !page.isClosed();
}

async function hasLoginForm(page) {
  const email = page.locator("input[type='email'], input[name*='email' i]");
  if ((await email.count()) > 0) return true;
  const password = page.locator("input[type='password']");
  if ((await password.count()) > 0) return true;
  return false;
}

async function hasHumanVerification(page) {
  const url = String(page.url() || "");
  if (isChallengeUrl(url)) return true;
  const bodyText = await page.locator("body").innerText().catch(() => "");
  const normalized = normalizeText(bodyText).toLowerCase();
  if (!normalized) return false;
  const markers = [
    "verify you are human",
    "security check",
    "are you a robot",
    "bot check",
    "captcha",
    "challenge",
  ];
  return markers.some((marker) => normalized.includes(marker));
}

async function isLoginPage(page) {
  if (!isPageUsable(page)) return true;
  const url = String(page.url() || "");
  if (isLoginUrl(url)) return true;
  if (await hasLoginForm(page)) return true;
  return false;
}

async function persistStorageState(context, storageState) {
  if (!storageState) return;
  try {
    const dir = path.dirname(storageState);
    ensureDir(dir);
    await context.storageState({ path: storageState });
  } catch {
    // best effort
  }
}

async function waitForUserAuth(page, label, { timeoutMs = 20 * 60 * 1000, storageState = "" } = {}) {
  const context = page.context();
  const isInteractive = Boolean(process.stdin && process.stdin.isTTY);
  console.error(`[AUTH_REQUIRED] ${label}`);
  console.error("[AUTH_HINT] Complete login/challenge in the opened browser and keep the window open.");
  if (isInteractive) {
    console.error("Press Enter here after login is complete.");
  }
  await page.bringToFront().catch(() => {});

  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const pages = context.pages().filter((p) => isPageUsable(p));
    if (pages.length === 0) {
      throw new Error(`AUTH_HANDOFF_ABORTED: ${label} (browser was closed before login completed)`);
    }
    const active = pages[pages.length - 1];
    const loginPage = await isLoginPage(active);
    const challenge = await hasHumanVerification(active);
    if (!loginPage && !challenge) {
      await persistStorageState(context, storageState);
      return active;
    }
    await active.waitForTimeout(isInteractive ? 250 : 1000).catch(() => {});
  }

  throw new Error(`AUTH_REQUIRED: ${label} (timeout waiting for manual login/challenge completion)`);
}

async function ensureAuthenticated(page, authHandoff, label, { storageState = "" } = {}) {
  const challenge = await hasHumanVerification(page);
  const login = await isLoginPage(page);
  if (!challenge && !login) return page;
  if (!authHandoff) {
    throw new Error(`AUTH_REQUIRED: ${label} (storage_state expired or challenge detected)`);
  }
  const activePage = await waitForUserAuth(page, label, { storageState });
  await activePage.waitForLoadState("networkidle").catch(() => {});
  const stillLogin = await isLoginPage(activePage);
  const stillChallenge = await hasHumanVerification(activePage);
  if (stillLogin || stillChallenge) {
    throw new Error(`AUTH_REQUIRED: ${label} (still on login/challenge page)`);
  }
  return activePage;
}

function ymTokens(year, month) {
  const yyyy = String(year);
  const mm = String(month).padStart(2, "0");
  const m = String(Number.parseInt(mm, 10));
  return [
    `${yyyy}-${mm}`,
    `${yyyy}/${mm}`,
    `${yyyy}.${mm}`,
    `${yyyy}${mm}`,
    `${yyyy}-${m}`,
    `${yyyy}/${m}`,
    `${yyyy}.${m}`,
  ];
}

function maybeMonthMatched(text, year, month) {
  const normalized = normalizeText(text);
  if (!normalized) return false;
  return ymTokens(year, month).some((token) => normalized.includes(token));
}

function shouldTreatAsInvoiceLink(entry) {
  const text = normalizeText(entry?.text || "").toLowerCase();
  const href = String(entry?.href || "").toLowerCase();
  if (!href) return false;
  if (href.includes(".pdf")) return true;
  if (/invoice|receipt|billing|statement|download/.test(text)) return true;
  if (/invoice|receipt|billing|statement|download/.test(href)) return true;
  return false;
}

function uniqueByUrl(items) {
  const out = [];
  const seen = new Set();
  for (const item of items) {
    const url = String(item?.url || "").trim();
    if (!url || seen.has(url)) continue;
    seen.add(url);
    out.push(item);
  }
  return out;
}

async function collectInvoiceCandidatesFromPage(page, year, month) {
  if (!isPageUsable(page)) return [];
  const rows = await page
    .evaluate(() => {
      const anchors = Array.from(document.querySelectorAll("a[href]"));
      return anchors.map((a) => ({
        href: String(a.getAttribute("href") || ""),
        text: String(a.textContent || ""),
      }));
    })
    .catch(() => []);

  const base = page.url();
  const candidates = [];
  for (const row of rows || []) {
    const href = String(row?.href || "").trim();
    if (!href) continue;
    const text = normalizeText(row?.text || "");
    let url = "";
    try {
      url = new URL(href, base).toString();
    } catch {
      continue;
    }
    if (!shouldTreatAsInvoiceLink({ href: url, text })) continue;
    const monthHit = maybeMonthMatched(`${url} ${text}`, year, month);
    candidates.push({
      url,
      text,
      month_hit: monthHit,
      page_url: base,
    });
  }
  return candidates;
}

async function collectInvoiceCandidatesFromContext(context, year, month) {
  const all = [];
  const pages = context.pages().filter((page) => isPageUsable(page));
  for (const page of pages) {
    const pageCandidates = await collectInvoiceCandidatesFromPage(page, year, month);
    all.push(...pageCandidates);
  }
  const unique = uniqueByUrl(all);
  unique.sort((a, b) => Number(Boolean(b.month_hit)) - Number(Boolean(a.month_hit)));
  return unique;
}

async function downloadPdf(context, url) {
  const response = await context.request.get(url, {
    timeout: 30000,
    failOnStatusCode: false,
  });
  if (!response.ok()) return null;
  const body = await response.body();
  const contentType = String(response.headers()["content-type"] || "").toLowerCase();
  const looksPdf = contentType.includes("pdf") || body.slice(0, 5).toString("utf8") === "%PDF-";
  if (!looksPdf) return null;
  return body;
}

function outputName(provider, year, month, index, url) {
  const y = String(year);
  const m = String(month).padStart(2, "0");
  let token = "invoice";
  try {
    const parsed = new URL(url);
    const name = parsed.pathname.split("/").filter(Boolean).pop() || "invoice";
    token = safeFilePart(name.replace(/\.pdf$/i, ""));
  } catch {
    token = `invoice_${index + 1}`;
  }
  if (!token) token = `invoice_${index + 1}`;
  return `${y}-${m}_${provider}_${String(index + 1).padStart(2, "0")}_${token}.pdf`;
}

async function clickBillingHints(page) {
  if (!isPageUsable(page)) return page;
  const context = page.context();
  const hints = [
    "a:has-text('Billing')",
    "a:has-text('Invoice')",
    "a:has-text('Invoices')",
    "a:has-text('Payment')",
    "a:has-text('Subscription')",
    "a:has-text('Manage')",
    "button:has-text('Billing')",
    "button:has-text('Invoice')",
    "button:has-text('Payment')",
    "button:has-text('Subscription')",
    "button:has-text('Manage')",
  ];
  let activePage = page;
  for (const selector of hints) {
    if (!isPageUsable(activePage)) break;
    const el = activePage.locator(selector).first();
    if ((await el.count()) === 0) continue;
    const visible = await el.isVisible().catch(() => false);
    if (!visible) continue;
    const popupPromise = context.waitForEvent("page", { timeout: 1200 }).catch(() => null);
    await el.click({ timeout: 4000, force: true }).catch(() => {});
    const popup = await popupPromise;
    if (popup) {
      await popup.waitForLoadState("domcontentloaded").catch(() => {});
      activePage = popup;
    } else {
      await activePage.waitForLoadState("networkidle").catch(() => {});
    }
    await activePage.waitForTimeout(300).catch(() => {});
  }
  return activePage;
}

async function launchBrowser(headed, slowMoMs) {
  const launchBase = { headless: !headed, slowMo: slowMoMs };
  try {
    return await chromium.launch({ ...launchBase, channel: "msedge" });
  } catch {
    return chromium.launch(launchBase);
  }
}

async function waitForCandidatesViaManualNavigation(context, provider, year, month, { timeoutMs = 10 * 60 * 1000 } = {}) {
  console.error(`[MANUAL_ACTION] ${provider} billing page did not expose invoice links yet.`);
  console.error("[MANUAL_HINT] Please navigate to billing/invoice page in the opened browser.");
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const pages = context.pages().filter((page) => isPageUsable(page));
    if (pages.length === 0) {
      throw new Error(`MANUAL_BILLING_ABORTED: ${provider} (browser was closed before invoice links appeared)`);
    }
    const candidates = await collectInvoiceCandidatesFromContext(context, year, month);
    if (candidates.length > 0) return candidates;
    for (const page of pages) {
      await clickBillingHints(page).catch(() => {});
    }
    await pages[pages.length - 1].waitForTimeout(1000).catch(() => {});
  }
  throw new Error(`BILLING_PAGE_NOT_READY: ${provider} (no invoice links found after manual navigation timeout)`);
}

export async function runProviderDownload({
  provider,
  storageState,
  year,
  month,
  outDir,
  debugDir = "",
  authHandoff = false,
  headed = true,
  slowMoMs = 0,
  startUrls = [],
}) {
  if (!provider) throw new Error("provider is required");
  if (!storageState) throw new Error("storageState is required");
  if (!outDir) throw new Error("outDir is required");
  if (!fs.existsSync(storageState)) throw new Error(`storage_state_not_found: ${storageState}`);

  ensureDir(outDir);
  if (debugDir) ensureDir(debugDir);

  const browser = await launchBrowser(headed, slowMoMs);
  const context = await browser.newContext({
    storageState,
    locale: "ja-JP",
    timezoneId: "Asia/Tokyo",
    acceptDownloads: true,
  });
  await context.addInitScript(() => {
    try {
      Object.defineProperty(navigator, "webdriver", { get: () => undefined });
      window.chrome = window.chrome || { runtime: {} };
      Object.defineProperty(navigator, "plugins", { get: () => [1, 2, 3, 4] });
      Object.defineProperty(navigator, "languages", { get: () => ["ja-JP", "ja", "en-US", "en"] });
    } catch {
      // best effort
    }
  });
  let page = await context.newPage();

  const visited = [];
  const downloaded = [];
  const failures = [];
  try {
    const targets = Array.isArray(startUrls) && startUrls.length ? startUrls : ["https://example.com"];
    let navigatedAny = false;
    for (const url of targets) {
      try {
        await page.goto(url, { waitUntil: "domcontentloaded" });
        await page.waitForLoadState("networkidle").catch(() => {});
        page = await ensureAuthenticated(page, authHandoff, `${provider} billing`, { storageState });
        visited.push(page.url());
        page = await clickBillingHints(page);
        visited.push(page.url());
        navigatedAny = true;
      } catch (err) {
        failures.push({
          url,
          reason: `navigation_failed: ${String(err && err.message ? err.message : err)}`,
        });
      }
    }
    if (!navigatedAny) {
      throw new Error(`NAVIGATION_FAILED: ${provider} could not open any billing entry URL`);
    }

    let candidates = await collectInvoiceCandidatesFromContext(context, year, month);
    if (candidates.length === 0 && authHandoff) {
      candidates = await waitForCandidatesViaManualNavigation(context, provider, year, month);
    }

    for (let i = 0; i < candidates.length; i++) {
      const candidate = candidates[i];
      try {
        const data = await downloadPdf(context, candidate.url);
        if (!data) continue;
        const name = outputName(provider, year, month, i, candidate.url);
        const dest = path.resolve(path.join(outDir, name));
        fs.writeFileSync(dest, data);
        downloaded.push({
          url: candidate.url,
          file_path: dest,
          month_hit: Boolean(candidate.month_hit),
          page_url: String(candidate.page_url || ""),
        });
      } catch (err) {
        failures.push({
          url: candidate.url,
          reason: String(err && err.message ? err.message : err),
        });
      }
    }

    await persistStorageState(context, storageState);
    const result = {
      status: "success",
      data: {
        provider,
        year,
        month,
        out_dir: path.resolve(outDir),
        visited_urls: visited,
        candidates_found: candidates.length,
        downloaded_count: downloaded.length,
        downloaded_files: downloaded,
        failures,
        final_url: isPageUsable(page) ? page.url() : "",
      },
    };
    console.log(JSON.stringify(result));
    return result;
  } catch (err) {
    if (debugDir && isPageUsable(page)) {
      await writeDebug(page, debugDir, `${provider}_download_failed`).catch(() => {});
    }
    throw err;
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

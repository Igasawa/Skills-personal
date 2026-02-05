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

function fileExists(p) {
  if (!p) return false;
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

async function locatorVisible(locator) {
  try {
    if ((await locator.count()) === 0) return false;
    return await locator.first().isVisible();
  } catch {
    return false;
  }
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

function isMfLoginUrl(url) {
  return /auth|sign|login/i.test(url || "");
}

async function isMfLoginPage(page) {
  const url = page.url();
  if (isMfLoginUrl(url)) return true;
  const email = page.locator("input[type='email'], input[name*='email' i]");
  if (await locatorVisible(email)) return true;
  const password = page.locator("input[type='password']");
  if (await locatorVisible(password)) return true;
  const signIn = page.locator("button, input[type='submit']", { hasText: /ログイン|サインイン|Sign in/i }).first();
  if (await locatorVisible(signIn)) return true;
  return false;
}

async function waitForUserAuth(page, label, isLoginFn) {
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
    if (!(await isLoginFn(page))) {
      return;
    }
  }
  throw new Error(`AUTH_REQUIRED: ${label} (timeout waiting for manual login)`);
}

async function ensureAuthenticated(page, authHandoff, label, isLoginFn) {
  if (!(await isLoginFn(page))) return;
  if (!authHandoff) {
    throw new Error(`AUTH_REQUIRED: ${label} (storage_state expired)`);
  }
  await waitForUserAuth(page, label, isLoginFn);
  await page.waitForLoadState("networkidle").catch(() => {});
  if (await isLoginFn(page)) {
    throw new Error(`AUTH_REQUIRED: ${label} (still on login page)`);
  }
}

function attachAutoDialog(page) {
  page.on("dialog", async (dialog) => {
    try {
      await dialog.accept();
    } catch {
      // ignore
    }
  });
}

async function createContext(browser, storagePath) {
  if (storagePath && fileExists(storagePath)) {
    return browser.newContext({ storageState: storagePath });
  }
  return browser.newContext();
}

async function saveStorageState(context, storagePath) {
  if (!storagePath) return;
  ensureDir(path.dirname(storagePath));
  await context.storageState({ path: storagePath });
}

async function locateServiceContainer(page) {
  const heading = page.locator("text=連携サービス").first();
  if ((await heading.count()) > 0) {
    return heading.locator("xpath=ancestor::*[self::section or self::div][1]");
  }
  return page.locator("body");
}

async function findMenuButtons(container) {
  const selectors = [
    "button[aria-label*='メニュー']",
    "button[aria-label*='その他']",
    "button[aria-label*='More']",
    "button[aria-label*='オプション']",
    "[data-testid*='menu']",
    "[data-testid*='more']",
    "[data-testid*='dots']",
  ];
  for (const sel of selectors) {
    const loc = container.locator(sel);
    if ((await loc.count()) > 0) return loc;
  }
  const dotted = container.locator("button").filter({ hasText: /…|⋯|・・・/ });
  if ((await dotted.count()) > 0) return dotted;
  return container.locator("[data-preflight-menu='none']");
}

async function clickReacquire(page) {
  let menu = page.locator("[role='menu']").filter({ hasText: /再取得/ });
  if ((await menu.count()) > 0) {
    const item = menu.locator("[role='menuitem'], button, a, li, div", { hasText: /再取得/ }).first();
    if ((await item.count()) > 0) {
      await item.click().catch(() => {});
      return true;
    }
  }
  const fallback = page.locator("button, a, li, div", { hasText: /再取得/ }).first();
  if ((await fallback.count()) > 0) {
    await fallback.click().catch(() => {});
    return true;
  }
  return false;
}

async function confirmReacquireIfNeeded(page) {
  const modal = page.locator("[role='dialog'], .modal, .MuiDialog-root").first();
  if ((await modal.count()) > 0) {
    const btn = modal.locator("button, input[type='submit'], input[type='button']", { hasText: /再取得|実行|OK|はい|更新/ }).first();
    if ((await btn.count()) > 0) {
      await btn.click().catch(() => {});
      await page.waitForTimeout(300);
      return true;
    }
  }
  return false;
}

async function refreshLinkedServices(page) {
  const container = await locateServiceContainer(page);
  const menuButtons = await findMenuButtons(container);
  const count = await menuButtons.count();
  if (count === 0) {
    console.log("[mfcloud] menu buttons not found; skip refresh");
    return { total: 0, attempted: 0, refreshed: 0 };
  }
  let refreshed = 0;
  let attempted = 0;
  for (let i = 0; i < count; i++) {
    const btn = menuButtons.nth(i);
    try {
      await btn.scrollIntoViewIfNeeded().catch(() => {});
      await btn.click({ timeout: 2000 }).catch(() => {});
      attempted += 1;
      await page.waitForTimeout(200);
      const clicked = await clickReacquire(page);
      if (clicked) {
        refreshed += 1;
        await page.waitForTimeout(400);
        await confirmReacquireIfNeeded(page);
      } else {
        await page.keyboard.press("Escape").catch(() => {});
      }
    } catch {
      // continue
    }
  }
  return { total: count, attempted, refreshed };
}

async function main() {
  const args = parseArgs(process.argv);
  const amazonOrdersUrl = args["amazon-orders-url"] || "https://www.amazon.co.jp/gp/your-account/order-history";
  const rakutenOrdersUrl = args["rakuten-orders-url"] || "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order";
  const mfAccountsUrl = args["mfcloud-accounts-url"] || "https://expense.moneyforward.com/accounts";
  const amazonStorage = args["amazon-storage-state"];
  const rakutenStorage = args["rakuten-storage-state"];
  const mfStorage = args["mfcloud-storage-state"];
  const authHandoff = Boolean(args["auth-handoff"]);
  const headed = args.headed !== false;
  const slowMoMs = Number.parseInt(args["slow-mo-ms"] || "0", 10);

  const browser = await chromium.launch({ headless: !headed, slowMo: slowMoMs });
  const results = {
    amazon: { ok: false, storage_state: amazonStorage || null },
    rakuten: { ok: false, storage_state: rakutenStorage || null },
    mfcloud: { ok: false, storage_state: mfStorage || null, refreshed: 0, total_cards: 0 },
  };

  try {
    if (amazonOrdersUrl) {
      console.log("[preflight] Amazon login start");
      const context = await createContext(browser, amazonStorage);
      const page = await context.newPage();
      attachAutoDialog(page);
      await page.goto(amazonOrdersUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
      await ensureAuthenticated(page, authHandoff, "Amazon orders page", isAmazonLoginPage);
      await saveStorageState(context, amazonStorage);
      results.amazon.ok = true;
      await context.close().catch(() => {});
      console.log("[preflight] Amazon login done");
    }

    if (rakutenOrdersUrl) {
      console.log("[preflight] Rakuten login start");
      const context = await createContext(browser, rakutenStorage);
      const page = await context.newPage();
      attachAutoDialog(page);
      await page.goto(rakutenOrdersUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
      await ensureAuthenticated(page, authHandoff, "Rakuten order list", isRakutenLoginPage);
      await saveStorageState(context, rakutenStorage);
      results.rakuten.ok = true;
      await context.close().catch(() => {});
      console.log("[preflight] Rakuten login done");
    }

    if (mfAccountsUrl) {
      console.log("[preflight] MF Cloud login start");
      const context = await createContext(browser, mfStorage);
      const page = await context.newPage();
      attachAutoDialog(page);
      await page.goto(mfAccountsUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
      await ensureAuthenticated(page, authHandoff, "MF Cloud accounts page", isMfLoginPage);
      await page.waitForLoadState("networkidle").catch(() => {});
      const refreshed = await refreshLinkedServices(page);
      results.mfcloud.ok = true;
      results.mfcloud.refreshed = refreshed.refreshed;
      results.mfcloud.total_cards = refreshed.total;
      await saveStorageState(context, mfStorage);
      await context.close().catch(() => {});
      console.log(`[preflight] MF Cloud refresh done (refreshed ${refreshed.refreshed}/${refreshed.total})`);
    }
  } finally {
    await browser.close().catch(() => {});
  }

  console.log(JSON.stringify({ status: "success", data: results }));
}

main().catch((err) => {
  console.log(JSON.stringify({ status: "error", error: { type: err?.name || "Error", message: String(err?.message || err) } }));
  process.exit(1);
});

#!/usr/bin/env node
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";
import { ensureDir, fileExists, locatorVisible, parseArgs, writeDebug } from "./mjs_common.mjs";

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
  // Prefer the main content region to avoid picking up the sidebar "連携サービス"
  // entry, which caused refresh to be skipped even though cards were present.
  const main = page.locator("main, [role='main']").first();
  if ((await main.count()) > 0) return main;

  // The MF Cloud accounts page typically has tabs; this text is unlikely to appear in the sidebar.
  const tab = page.locator("text=連携サービス一覧").first();
  if ((await tab.count()) > 0) {
    return tab.locator("xpath=ancestor::*[self::section or self::div][1]");
  }

  // Fallback to a real heading element (sidebar entries are usually links/spans, not h1/h2).
  const heading = page
    .locator("h1, h2, [role='heading']")
    .filter({ hasText: "連携サービス" })
    .first();
  if ((await heading.count()) > 0) {
    return heading.locator("xpath=ancestor::*[self::section or self::div][1]");
  }

  return page.locator("body");
}

async function findMenuButtons(container) {
  // NOTE: MF Cloud's "kebab" menu trigger differs by tenant/version.
  // Prefer selectors that cover button/a/role=button without relying on visible text.
  const selectors = [
    // Common MUI patterns (MF Cloud often uses IconButton for the card menu).
    ".MuiCardHeader-action button",
    ".MuiCardHeader-action [role='button']",
    "button.MuiIconButton-root",
    "[role='button'].MuiIconButton-root",

    // Accessible labels (icon-only triggers are often labeled this way).
    ":is(button, a, [role='button'])[aria-label*='メニュー']",
    ":is(button, a, [role='button'])[aria-label*='その他']",
    ":is(button, a, [role='button'])[aria-label*='More']",
    ":is(button, a, [role='button'])[aria-label*='オプション']",

    // Common menu trigger semantics.
    ":is(button, a, [role='button'])[aria-haspopup='menu']",
    ":is(button, a, [role='button'])[aria-haspopup='true']",
    ":is(button, a, [role='button'])[data-toggle='dropdown']",
    ":is(button, a, [role='button'])[data-bs-toggle='dropdown']",
    ":is(button, a, [role='button'])[data-toggle*='dropdown']",
    ":is(button, a, [role='button'])[data-bs-toggle*='dropdown']",

    // Testing hooks / implementation details (best-effort).
    ":is(button, a, [role='button'])[data-testid*='menu']",
    ":is(button, a, [role='button'])[data-testid*='more']",
    ":is(button, a, [role='button'])[data-testid*='dots']",
    "[data-testid*='menu']",
    "[data-testid*='more']",
    "[data-testid*='dots']",

    // Class-hinted fallbacks (avoid relying solely on aria-label/text).
    ":is(button, a, [role='button'])[class*='ellipsis' i]",
    ":is(button, a, [role='button'])[class*='kebab' i]",
    ":is(button, a, [role='button'])[class*='dots' i]",
    ":is(button, a, [role='button'])[class*='menu' i]",
    ":is(button, a, [role='button'])[class*='more' i]",
    ":is(button, a, [role='button'])[class*='dropdown' i]",
  ];
  for (const sel of selectors) {
    const loc = container.locator(sel);
    if ((await loc.count()) > 0) return loc;
  }

  // Try to detect MUI "more" icons via SVG testids without relying on CSS :has().
  const byMoreIcon = container
    .locator("button, a, [role='button']")
    .filter({ has: container.locator("svg[data-testid='MoreHorizIcon'], svg[data-testid='MoreVertIcon'], svg[data-testid*='More' i]") });
  if ((await byMoreIcon.count()) > 0) return byMoreIcon;

  // Last resort: some tenants use an unlabeled icon button with visible dots/ellipsis.
  // Include vertical ellipsis variants as well.
  const dotted = container.locator("button, a, [role='button']").filter({ hasText: /…|⋯|⋮|︙|・・・|\.{3}/ });
  if ((await dotted.count()) > 0) return dotted;
  return container.locator("[data-preflight-menu='none']");
}

async function clickReacquire(page) {
  // Prefer the currently opened menu/popover rather than searching the whole page.
  const menus = [
    page.locator("[role='menu']").filter({ hasText: /再取得/ }),
    page.locator(".MuiMenu-paper, .MuiMenu-list, .MuiPopover-root").filter({ hasText: /再取得/ }),
    page.locator(".dropdown-menu, [data-popper-placement]").filter({ hasText: /再取得/ }),
  ];
  for (const menu of menus) {
    if ((await menu.count()) === 0) continue;
    const item = menu.locator("[role='menuitem'], button, a, li, div, span", { hasText: /再取得/ }).first();
    if ((await item.count()) === 0) continue;
    await item.click().catch(() => {});
    return true;
  }

  // Fallback: sometimes the menu root has no role/class we can rely on.
  const fallback = page.locator("button, a, li, div, span", { hasText: /再取得/ }).first();
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

async function ensureLinkedServiceListTab(page) {
  // Some tenants land on a different sub-tab within the accounts area.
  // Clicking this tab is safe even if already active.
  const tab = page
    .locator("a, button, [role='tab'], [role='button']")
    .filter({ hasText: "連携サービス一覧" })
    .first();
  if ((await tab.count()) === 0) return false;
  const visible = await tab.isVisible().catch(() => false);
  if (!visible) return false;
  await tab.click({ timeout: 5000 }).catch(() => {});
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(250);
  return true;
}

async function refreshLinkedServicesLegacy(page, debugDir) {
  // Some MF Cloud tenants still serve the legacy (non-MUI) accounts page:
  // - "ul.list-accounts" with per-account dropdown and an in-DOM "再取得" form.
  // In that case, it is more reliable to POST the "aggregation_queue" forms directly
  // rather than trying to click the (sometimes div-based) dropdown trigger.
  const list = page.locator("ul.list-accounts").first();
  if ((await list.count()) === 0) return null;
  await list.waitFor({ state: "visible", timeout: 15000 }).catch(() => {});

  const forms = list.locator("form[action$='/aggregation_queue']");
  const count = await forms.count();
  if (count === 0) return null;

  console.log(`[mfcloud] legacy aggregation forms detected: ${count}`);
  let attempted = 0;
  let refreshed = 0;
  // Guard against unexpected selector explosions.
  const maxForms = Math.min(count, 80);
  for (let i = 0; i < maxForms; i++) {
    const form = forms.nth(i);
    try {
      const ok = await form.evaluate(async (el) => {
        try {
          const fd = new FormData(el);
          const res = await fetch(el.action, { method: "POST", body: fd, credentials: "same-origin" });
          return Boolean(res && (res.ok || (res.status >= 200 && res.status < 400)));
        } catch {
          return false;
        }
      });
      attempted += 1;
      if (ok) refreshed += 1;
      await page.waitForTimeout(200);
    } catch {
      // continue
    }
  }

  // If it took effect, MF often shows "取得中" on the card.
  // The legacy page sometimes updates this indicator only after reload.
  await page.waitForTimeout(500);
  await page.reload({ waitUntil: "domcontentloaded" }).catch(() => {});
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.locator("text=取得中").first().waitFor({ state: "visible", timeout: 8000 }).catch(() => {});
  if (debugDir) await writeDebug(page, debugDir, "mfcloud_accounts_legacy_after_submit");
  return { total: count, attempted, refreshed };
}

async function refreshLinkedServices(page, debugDir) {
  await ensureLinkedServiceListTab(page).catch(() => {});

  const legacy = await refreshLinkedServicesLegacy(page, debugDir).catch(() => null);
  if (legacy) return legacy;

  // Cards are rendered asynchronously; avoid false "0 cards" due to early probing.
  await page.locator("text=今月の明細").first().waitFor({ state: "visible", timeout: 15000 }).catch(() => {});
  await page.locator("text=更新日").first().waitFor({ state: "visible", timeout: 15000 }).catch(() => {});

  const container = await locateServiceContainer(page);
  const menuButtons = await findMenuButtons(container);
  const count = await menuButtons.count();
  if (count === 0) {
    console.log("[mfcloud] menu buttons not found; skip refresh");
    if (debugDir) await writeDebug(page, debugDir, "mfcloud_accounts_no_menu_buttons");
    return { total: 0, attempted: 0, refreshed: 0 };
  }
  let refreshed = 0;
  let attempted = 0;
  let visibleTotal = 0;
  // Guard against unexpected selector explosions.
  const maxButtons = Math.min(count, 80);
  console.log(`[mfcloud] menu buttons detected: ${count}`);
  for (let i = 0; i < maxButtons; i++) {
    const btn = menuButtons.nth(i);
    const visible = await btn.isVisible().catch(() => false);
    if (!visible) continue;
    visibleTotal += 1;
    try {
      await btn.scrollIntoViewIfNeeded().catch(() => {});
      await btn.click({ timeout: 3000, force: true }).catch(() => {});
      // Wait briefly for the menu to render before searching for "再取得".
      await page.locator("text=再取得").first().waitFor({ state: "visible", timeout: 1500 }).catch(() => {});
      const clicked = await clickReacquire(page);
      if (clicked) {
        attempted += 1;
        refreshed += 1;
        await page.waitForTimeout(400);
        await confirmReacquireIfNeeded(page);
        // When the click took effect, MF often shows "取得中" on the card.
        await page.locator("text=取得中").first().waitFor({ state: "visible", timeout: 2500 }).catch(() => {});
        console.log(`[mfcloud] reacquire clicked (${refreshed}/${attempted})`);
      } else {
        await page.keyboard.press("Escape").catch(() => {});
      }
    } catch {
      // continue
    }
  }
  if (attempted === 0 && visibleTotal > 0) {
    console.log(`[mfcloud] menu opened but '再取得' not found (visible buttons ${visibleTotal}/${count})`);
  }
  return { total: visibleTotal, attempted, refreshed };
}

async function main() {
  const args = parseArgs(process.argv);
  const debugDir = args["debug-dir"] ? path.resolve(String(args["debug-dir"])) : null;
  const skipAmazon = Boolean(args["skip-amazon"]);
  const skipRakuten = Boolean(args["skip-rakuten"]);
  const skipMfcloud = Boolean(args["skip-mfcloud"]);

  const amazonOrdersUrl = skipAmazon ? null : args["amazon-orders-url"] || "https://www.amazon.co.jp/gp/your-account/order-history";
  const rakutenOrdersUrl = skipRakuten ? null : args["rakuten-orders-url"] || "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order";
  const mfAccountsUrl = skipMfcloud ? null : args["mfcloud-accounts-url"] || "https://expense.moneyforward.com/accounts";
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
      if (debugDir) await writeDebug(page, debugDir, "mfcloud_accounts_before_refresh");
      const refreshed = await refreshLinkedServices(page, debugDir);
      if (debugDir) await writeDebug(page, debugDir, "mfcloud_accounts_after_refresh");
      results.mfcloud.ok = true;
      results.mfcloud.refreshed = refreshed.refreshed;
      results.mfcloud.total_cards = refreshed.total;
      results.mfcloud.attempted = refreshed.attempted;
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

#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";

export function parseArgs(argv) {
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

export function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
  return p;
}

export function safeFilePart(s) {
  return String(s).replace(/[^a-zA-Z0-9._-]+/g, "_");
}

export function fileExists(p) {
  if (!p) return false;
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

export async function writeDebug(page, debugDir, name) {
  try {
    ensureDir(debugDir);
    await page.screenshot({ path: path.join(debugDir, `${name}.png`), fullPage: true });
    const html = await page.content();
    fs.writeFileSync(path.join(debugDir, `${name}.html`), html, "utf-8");
  } catch {
    // best-effort
  }
}

export async function locatorVisible(locator) {
  try {
    if ((await locator.count()) === 0) return false;
    return await locator.first().isVisible();
  } catch {
    return false;
  }
}

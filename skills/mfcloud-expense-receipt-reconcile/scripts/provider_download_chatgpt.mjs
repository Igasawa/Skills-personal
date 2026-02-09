#!/usr/bin/env node
import { parseArgs } from "./mjs_common.mjs";
import { runProviderDownload } from "./provider_download_common.mjs";

async function main() {
  const args = parseArgs(process.argv);
  const provider = "chatgpt";
  const storageState = String(args["storage-state"] || "");
  const outDir = String(args["out-dir"] || "");
  const debugDir = String(args["debug-dir"] || "");
  const year = Number.parseInt(String(args.year || "0"), 10);
  const month = Number.parseInt(String(args.month || "0"), 10);
  const authHandoff = Boolean(args["auth-handoff"]);
  const headed = args.headed !== false;
  const slowMoMs = Number.parseInt(String(args["slow-mo-ms"] || "0"), 10);

  if (!storageState) throw new Error("Missing --storage-state");
  if (!outDir) throw new Error("Missing --out-dir");
  if (!year || !month) throw new Error("Missing --year/--month");

  await runProviderDownload({
    provider,
    storageState,
    year,
    month,
    outDir,
    debugDir,
    authHandoff,
    headed,
    slowMoMs,
    startUrls: [
      "https://chatgpt.com/",
      "https://chatgpt.com/settings/billing",
      "https://chatgpt.com/admin/billing",
      "https://platform.openai.com/settings/organization/billing/overview",
      "https://platform.openai.com/settings/organization/billing/history",
    ],
  });
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});

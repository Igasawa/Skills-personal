#!/usr/bin/env node
import { parseArgs } from "./mjs_common.mjs";
import { runProviderDownload } from "./provider_download_common.mjs";

async function main() {
  const args = parseArgs(process.argv);
  const provider = "claude";
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
      "https://claude.ai/",
      "https://console.anthropic.com/settings/billing",
      "https://console.anthropic.com/settings/plans",
    ],
  });
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});

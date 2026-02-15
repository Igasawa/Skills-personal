param(
    [ValidateSet("weekly", "monthly", "change_response")]
    [string]$ReviewType = "weekly",

    [int]$TimeoutSeconds = 10,
    [int]$MaxAgeDays = 14,
    [string]$OutDir = "references/review_logs",
    [switch]$SkipUrlCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

python "$PSScriptRoot\review_official_manual.py" `
  --review-type $ReviewType `
  --timeout-seconds $TimeoutSeconds `
  --max-age-days $MaxAgeDays `
  --out-dir $OutDir `
  $(if ($SkipUrlCheck) { "--skip-url-check" })

param(
  [int]$Year,
  [int]$Month,
  [string]$OutputRoot,
  [switch]$IncludePdfs,
  [switch]$IncludeDebug
)

$ErrorActionPreference = "Stop"

function Get-AxHome {
  if ($env:AX_HOME -and $env:AX_HOME.Trim().Length -gt 0) {
    return $env:AX_HOME
  }
  return Join-Path $env:USERPROFILE ".ax"
}

function Resolve-OutputRoot([int]$Year, [int]$Month, [string]$OutputRoot) {
  if ($OutputRoot -and $OutputRoot.Trim().Length -gt 0) {
    return $OutputRoot
  }
  if (-not $Year -or -not $Month) {
    throw "Year and Month are required when OutputRoot is not specified."
  }
  $ym = "{0:D4}-{1:D2}" -f $Year, $Month
  $ax = Get-AxHome
  return Join-Path $ax "artifacts\\mfcloud-expense-receipt-reconcile\\$ym"
}

$root = Resolve-OutputRoot -Year $Year -Month $Month -OutputRoot $OutputRoot
if (-not (Test-Path $root)) {
  throw "Output root not found: $root"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$archiveRoot = Join-Path $root "archive"
$dest = Join-Path $archiveRoot $timestamp
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# Always keep the reports and key jsonl files.
$paths = @(
  (Join-Path $root "reports"),
  (Join-Path $root "amazon\\orders.jsonl"),
  (Join-Path $root "rakuten\\orders.jsonl"),
  (Join-Path $root "mfcloud\\expenses.jsonl"),
  (Join-Path $root "run_config.resolved.json")
)

foreach ($p in $paths) {
  if (Test-Path $p) {
    Copy-Item -Path $p -Destination $dest -Recurse -Force
  }
}

if ($IncludePdfs) {
  foreach ($p in @("amazon\\pdfs", "rakuten\\pdfs")) {
    $src = Join-Path $root $p
    if (Test-Path $src) {
      Copy-Item -Path $src -Destination $dest -Recurse -Force
    }
  }
}

if ($IncludeDebug) {
  $debug = Join-Path $root "debug"
  if (Test-Path $debug) {
    Copy-Item -Path $debug -Destination $dest -Recurse -Force
  }
}

Write-Host "Archived to: $dest"

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$hookPath = Join-Path $repoRoot ".githooks"

if (-not (Test-Path $hookPath)) {
  throw "Hook directory not found: $hookPath"
}

git -C $repoRoot config core.hooksPath ".githooks"
Write-Host "Configured core.hooksPath=.githooks for repo: $repoRoot"

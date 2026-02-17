param(
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$installHookScript = Join-Path $repoRoot "scripts/install_git_hooks.ps1"
$analyzeScript = Join-Path $repoRoot "scripts/analyze_commit.py"

if (-not (Test-Path $installHookScript)) {
    throw "Missing required script: $installHookScript"
}

if (-not (Test-Path $analyzeScript)) {
    throw "Missing required script: $analyzeScript"
}

$runner = (Get-Command powershell -ErrorAction SilentlyContinue).Source
if (-not $runner) {
    throw "PowerShell executable not found."
}

Write-Host "[KIL] Verifying hook installation..."
$verifyArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $installHookScript,
    "-VerifyOnly"
)

$verifyOutput = & $runner $verifyArgs 2>&1
$verifyExit = $LASTEXITCODE

if ($verifyExit -ne 0 -and -not $VerifyOnly) {
    Write-Host "[KIL] Hook is missing or unmanaged. Auto-bootstrap now..."
    $installArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $installHookScript
    )
    & $runner $installArgs

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to bootstrap post-commit hook. Please run with -ErrorAction Continue and inspect output."
    }
}
elseif ($verifyExit -ne 0 -and $VerifyOnly) {
    $verifyOutput | ForEach-Object { Write-Host $_ }
    throw "post-commit hook is missing or unmanaged. Run bootstrap_kil.ps1 without -VerifyOnly."
}

Write-Host "[KIL] Hook bootstrap/verify completed."
Write-Host "[KIL] Next: commit hooks will update docs/AGENT_BRAIN.md automatically after each commit."

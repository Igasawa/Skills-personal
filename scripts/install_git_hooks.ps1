param(
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$hooksCandidates = @(
    ".husky/_",
    ".githooks",
    ".git/hooks"
)
$hookFilename = "post-commit"
$markerText = "KIL_MANAGED_HOOK: post-commit"


function Get-GitConfig([string]$name) {
    $out = & git -C $repoRoot.Path config --get $name 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return $out.Trim()
}


function Resolve-HookDirectory([string]$rawPath) {
    if ([string]::IsNullOrWhiteSpace($rawPath)) {
        return $null
    }
    if ([System.IO.Path]::IsPathRooted($rawPath)) {
        if (Test-Path $rawPath) {
            return (Resolve-Path $rawPath).Path
        }
        return $null
    }
    $candidate = Join-Path $repoRoot $rawPath
    if (Test-Path $candidate) {
        return (Resolve-Path $candidate).Path
    }
    return $null
}


function Escape-BashSingleQuote([string]$value) {
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $value
    }
    $replacement = "'" + '"' + "'" + '"' + "'"
    return $value.Replace("'", $replacement)
}


function Write-HookFile([string]$targetPath, [string]$originalHookPath) {
    $orig = ""
    if (-not [string]::IsNullOrWhiteSpace($originalHookPath)) {
        $orig = Escape-BashSingleQuote($originalHookPath)
    }

    $content = @'
#!/usr/bin/env bash
set -euo pipefail

# KIL_MANAGED_HOOK: post-commit
KIL_HOOK_ORIG='{ORIG_HOOK}'
KIL_REPO_DIR='{REPO_DIR}'

if [ -n "${KIL_DISABLE_KIL_HOOK:-}" ] && [ "${KIL_DISABLE_KIL_HOOK:-}" != "0" ] && [ "${KIL_DISABLE_KIL_HOOK:-}" != "false" ]; then
  exit 0
fi

if [ -n "${KIL_HOOK_ORIG}" ] && [ -f "${KIL_HOOK_ORIG}" ]; then
  "${KIL_HOOK_ORIG}" "$@" || exit $?
fi

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="${KIL_REPO_DIR:-}"
if [ -z "${ROOT_DIR}" ]; then
  ROOT_DIR="$(git -C "$HOOK_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${ROOT_DIR}" ]; then
  ROOT_DIR="$(git -C "$HOOK_DIR/.." rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${ROOT_DIR}" ]; then
  ROOT_DIR="$(git -C "$HOOK_DIR/../.." rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${ROOT_DIR}" ]; then
  ROOT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"
fi
LOG_PATH="${KIL_POST_COMMIT_LOG:-$ROOT_DIR/docs/.kil_post_commit_hook.log}"
ANALYZE_SCRIPT="${KIL_ANALYZE_SCRIPT:-scripts/analyze_commit.py}"
ANALYZE_SCRIPT_ARGS=()

PYTHON_BIN="${KIL_PYTHON_BIN:-}"

if [ -z "${PYTHON_BIN}" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  elif command -v py >/dev/null 2>&1; then
    PYTHON_BIN="py"
    ANALYZE_SCRIPT_ARGS=("-3")
  fi
fi

if [ -z "${PYTHON_BIN}" ]; then
  echo "[KIL] Python not found. AGENT_BRAIN update skipped." >&2
  exit 0
fi

mkdir -p "$ROOT_DIR/docs"
  (
  cd "$ROOT_DIR"
  "$PYTHON_BIN" "${ANALYZE_SCRIPT_ARGS[@]}" "$ROOT_DIR/$ANALYZE_SCRIPT" >> "$LOG_PATH" 2>&1
) >> "$LOG_PATH" 2>&1 &
disown || true

exit 0
'@

    $repoDir = ($repoRoot.Path -replace '\\', '/')
    $content = $content.Replace("{REPO_DIR}", $repoDir)
    $content = $content.Replace("{ORIG_HOOK}", $orig)

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($targetPath, $content, $utf8NoBom)
}


function Ensure-Executable([string]$path) {
    if ([Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
        chmod +x "$path" | Out-Null
    }
}


function Test-KilHook([string]$path) {
    if (-not (Test-Path $path)) {
        return $false
    }
    $raw = Get-Content -Path $path -Raw -Encoding UTF8
    return $raw.Contains($markerText)
}


$configured = Get-GitConfig "core.hooksPath"
$resolvedHookDir = Resolve-HookDirectory $configured
$effectiveConfig = $configured

if ($null -eq $resolvedHookDir) {
    $selected = $null
    foreach ($candidate in $hooksCandidates) {
        $candidatePath = Join-Path $repoRoot $candidate
        if (Test-Path $candidatePath) {
            $selected = $candidate
            break
        }
    }

    if ($null -eq $selected) {
        $selected = ".git/hooks"
        New-Item -ItemType Directory -Path (Join-Path $repoRoot ".git/hooks") -Force | Out-Null
    }

    git -C $repoRoot config core.hooksPath $selected
    $effectiveConfig = $selected
    $resolvedHookDir = Resolve-HookDirectory $selected
    Write-Host "[KIL] core.hooksPath was unset or invalid; configured to: $selected"
} else {
    Write-Host "[KIL] Reusing existing core.hooksPath: $configured"
}

if (-not (Test-Path $resolvedHookDir)) {
    throw "Invalid hook directory: $resolvedHookDir"
}

$hookPath = Join-Path $resolvedHookDir $hookFilename
$originalHook = $null

if (Test-Path $hookPath) {
    if (Test-KilHook $hookPath) {
        Write-Host "[KIL] Existing managed post-commit hook found; updating content."
    } else {
        $timestamp = Get-Date -Format "yyyyMMddHHmmss"
        $backupPath = "$hookPath.kil-orig-$timestamp"
        Copy-Item -Path $hookPath -Destination $backupPath -Force
        $originalHook = $backupPath
        Write-Host "[KIL] Backed up existing post-commit to: $backupPath"
    }
}

if ($VerifyOnly) {
    if (-not (Test-Path $hookPath) -or -not (Test-KilHook $hookPath)) {
        Write-Error "[KIL] post-commit hook is missing or unmanaged. Run bootstrap without -VerifyOnly."
        exit 1
    }
    Write-Host "[KIL] post-commit hook is installed and managed."
    exit 0
}

Write-HookFile -targetPath $hookPath -originalHookPath $originalHook
Ensure-Executable $hookPath

Write-Host "[KIL] Installed managed post-commit hook at: $hookPath"
Write-Host "[KIL] Active hook path: $effectiveConfig"
Write-Host "[KIL] Bootstrap completed."

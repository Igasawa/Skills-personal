param(
    [string]$Message,
    [string]$Remote = "origin",
    [switch]$NoPush,
    [switch]$DryRun,
    [switch]$SkipScopeCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-OrThrow {
    param([string]$FilePath)
    if (-not (Get-Command $FilePath -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $FilePath"
    }
}

function Invoke-Git {
    param([string[]]$ArgumentList)
    $command = @("git") + $ArgumentList
    Write-Host "-> $($command -join ' ')"
    & git @ArgumentList
}

function Ensure-Root {
    $root = git rev-parse --show-toplevel
    Set-Location $root
}

function Get-CurrentBranch {
    $name = git rev-parse --abbrev-ref HEAD
    if ($name -eq "HEAD") {
        throw "Detached HEAD detected. Checkout a branch before running this script."
    }
    return $name
}

function Get-StagedFiles {
    $files = (git diff --cached --name-only --diff-filter=ACMR)
    return @($files | Where-Object { $_ -and $_.Trim() -ne "" })
}

function Test-Python {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $script:PythonCmd = "py"
        return
    }
    throw "Python is not found. Install Python and retry."
}

$script:PythonCmd = "python"

try {
    Test-Python
    Ensure-Root
    Invoke-OrThrow "git"
    Invoke-OrThrow $script:PythonCmd

    $branch = Get-CurrentBranch
    Write-Host "Branch: $branch"
    Write-Host "Remote: $Remote"

    $staged = Get-StagedFiles
    if ($staged.Count -eq 0) {
        throw "No staged changes found. Run `git add ...` first."
    }

    Write-Host "Staged files:"
    foreach ($path in $staged) {
        Write-Host "  - $path"
    }

    Write-Host "Encoding check (staged files)..."
    $args = @("scripts/check_text_encoding.py", "--scope", "staged")
    & $script:PythonCmd @args
    if ($LASTEXITCODE -ne 0) { throw "check_text_encoding.py failed (staged)." }

    if (-not $SkipScopeCheck) {
        Write-Host "Encoding check (dashboard template/static and scripts)..."
        $args = @(
            "scripts/check_text_encoding.py",
            "--scope", "tracked",
            "--path", "scripts",
            "--path", "skills/mfcloud-expense-receipt-reconcile/dashboard/templates",
            "--path", "skills/mfcloud-expense-receipt-reconcile/dashboard/static"
        )
        & $script:PythonCmd @args
        if ($LASTEXITCODE -ne 0) { throw "check_text_encoding.py failed (tracked targets)." }
    }

    if ($DryRun) {
        Write-Host "DryRun: commit/push skipped."
        exit 0
    }

    if ([string]::IsNullOrWhiteSpace($Message)) {
        $Message = Read-Host "Commit message"
    }
    if ([string]::IsNullOrWhiteSpace($Message)) {
        throw "Commit message is required."
    }

    Write-Host "Committing..."
    Invoke-Git @("commit", "-m", $Message)

    Write-Host "Fetch remote..."
    Invoke-Git @("fetch", $Remote)

    $upstream = "$Remote/$branch"
    try {
        git rev-parse --verify "$upstream" > $null
    } catch {
        Write-Host "No upstream tracked yet. Proceeding to push as first push."
        $upstream = $null
    }

    if ($upstream) {
        $behindOutput = git rev-list --count "HEAD..$upstream" 2>$null
        $behind = [int]$behindOutput
        if ($behind -gt 0) {
            throw "remote '$upstream' has $behind commits ahead. pull/rebase first."
        }
    }

    if ($NoPush) {
        Write-Host "NoPush specified. Commit only completed."
        exit 0
    }

    Write-Host "Pushing..."
    Invoke-Git @("push", $Remote, $branch)
    Write-Host "Done."
} catch {
    Write-Error $_
    exit 1
}

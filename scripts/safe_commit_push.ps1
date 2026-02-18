param(
    [string]$Message,
    [string]$Remote = "origin",
    [switch]$NoPush,
    [switch]$DryRun,
    [switch]$AllowNoStage,
    [switch]$CheckOnly,
    [switch]$SkipScopeCheck,
    [switch]$CheckLargeFiles,
    [int]$LargeFileThreshold = 300,
    [string[]]$LargeFileExtensions = @(
        ".py", ".pyi",
        ".js", ".mjs", ".ts", ".tsx", ".jsx",
        ".ps1", ".psm1", ".psd1",
        ".md", ".markdown",
        ".css", ".html",
        ".json", ".yaml", ".yml",
        ".toml", ".ini", ".cfg"
    ),
    [string[]]$LargeFileExcludeDirs = @(
        ".git",
        ".venv",
        "node_modules",
        "output",
        "__pycache__",
        ".pytest_cache",
        "skills/portable-codex-skills/pptx/ooxml/schemas"
    )
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
    $files = @()
    git diff --cached --name-only --diff-filter=ACMR | ForEach-Object {
        $line = $_.Trim()
        if ($line) {
            $files += $line
        }
    }
    return $files
}

function Get-WorkingTreeFiles {
    $files = @()
    git diff --name-only HEAD | ForEach-Object {
        $line = $_.Trim()
        if ($line) {
            $files += $line
        }
    }
    git ls-files --others --exclude-standard | ForEach-Object {
        $line = $_.Trim()
        if ($line) {
            $files += $line
        }
    }
    return ($files | Select-Object -Unique)
}

function Invoke-LargeFileCheck {
    param(
        [string[]]$Paths,
        [int]$Threshold,
        [string[]]$ExtFilter,
        [string[]]$ExcludeSubdirs
    )

    if (-not $Paths -or $Paths.Count -eq 0) {
        Write-Host "Large-file check target is empty. Skipped."
        return
    }

    $extLookup = @{}
    foreach ($ext in $ExtFilter) {
        $normalized = ("." + $ext.TrimStart(".")).ToLower()
        $extLookup[$normalized] = $true
    }

    $violations = @()
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }

        $normalizedPath = $path.ToLower()
        $skip = $false
        foreach ($dir in $ExcludeSubdirs) {
            $normalizedDir = $dir.ToLower().TrimEnd("/")
            if ($normalizedPath.StartsWith($normalizedDir) -or $normalizedPath -like "*$normalizedDir*") {
                $skip = $true
                break
            }
        }
        if ($skip) {
            continue
        }

        $ext = [IO.Path]::GetExtension($path).ToLower()
        if (-not $extLookup.ContainsKey($ext)) {
            continue
        }

        try {
            $lines = (Get-Content -LiteralPath $path -ErrorAction Stop | Measure-Object -Line).Lines
            if ($lines -gt $Threshold) {
                $violations += [pscustomobject]@{
                    File  = $path
                    Lines = $lines
                }
            }
        } catch {
            Write-Host "Skip file due to read error: $path"
        }
    }

    if ($violations.Count -gt 0) {
        Write-Host "Large-file debt check failed: files over $Threshold lines:"
        $violations | Sort-Object Lines -Descending | ForEach-Object {
            Write-Host ("  {0,5} {1}" -f $_.Lines, $_.File)
        }
        throw "Large-file debt check failed."
    }

    Write-Host "Large-file check passed."
}

function Invoke-EncodingCheck {
    param(
        [string]$Mode,
        [string[]]$Paths
    )
    if ($Paths.Count -eq 0) {
        Write-Host "$Mode check target is empty. Skipped."
        return
    }

    Write-Host "Encoding check ($Mode)..."
    $args = @("scripts/check_text_encoding.py")
    foreach ($path in $Paths) {
        $args += "--path"
        $args += $path
    }
    & $script:PythonCmd @args
    if ($LASTEXITCODE -ne 0) {
        throw "check_text_encoding.py failed ($Mode)."
    }
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
    if (-not $staged -or $staged.Count -eq 0) {
        if (-not $AllowNoStage) {
            if ($DryRun -or $CheckOnly) {
                throw "No staged changes found and no --AllowNoStage flag. Use -CheckOnly for repository checks only, or stage files first."
            }
            throw "No staged changes found. Run `git add ...` first."
        }

        Write-Host "No staged changes found. Running checks on working-tree files only with --AllowNoStage."
        $worktree = Get-WorkingTreeFiles
        Invoke-EncodingCheck "working tree" $worktree
        if ($CheckLargeFiles) {
            Invoke-LargeFileCheck -Paths $worktree -Threshold $LargeFileThreshold -ExtFilter $LargeFileExtensions -ExcludeSubdirs $LargeFileExcludeDirs
        }

        if ($CheckOnly -or $DryRun) {
            Write-Host "CheckOnly/DryRun: commit/push skipped."
            exit 0
        }

        throw "No staged files for commit. Stage files after checks, or rerun with -CheckOnly."
    }

    Write-Host "Staged files:"
    foreach ($path in $staged) {
        Write-Host "  - $path"
    }
    if ($CheckLargeFiles) {
        Invoke-LargeFileCheck -Paths $staged -Threshold $LargeFileThreshold -ExtFilter $LargeFileExtensions -ExcludeSubdirs $LargeFileExcludeDirs
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

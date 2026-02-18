Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$RUN_SCRIPT = Join-Path $SCRIPT_DIR "run.py"

function knowledge_refresh {
    [CmdletBinding()]
    param()

    $repo_root = (Get-Location).Path
    $run_args = @()
    $raw_args = @($args)

    for ($i = 0; $i -lt $raw_args.Count; $i++) {
        if ($raw_args[$i] -ieq "--repo-root") {
            if ($i -eq $raw_args.Count - 1) {
                throw "usage error: --repo-root requires a path value"
            }
            $repo_root = $raw_args[$i + 1]
            $i += 1
            continue
        }

        if ($raw_args[$i] -like "--repo-root=*") {
            $value = $raw_args[$i].Substring("--repo-root=".Length)
            if ([string]::IsNullOrWhiteSpace($value)) {
                throw "usage error: --repo-root requires a path value"
            }
            $repo_root = $value
            continue
        }

        $run_args += $raw_args[$i]
    }

    $resolved_repo_root = Resolve-Path -Path $repo_root

    $has_scan = $false
    $has_registry = $false
    for ($i = 0; $i -lt $run_args.Count; $i++) {
        if ($run_args[$i] -eq "--scan" -or $run_args[$i] -like "--scan=*") {
            $has_scan = $true
        }
        if ($run_args[$i] -eq "--registry" -or $run_args[$i] -like "--registry=*") {
            $has_registry = $true
        }
    }

    if (-not $has_scan) {
        $run_args = @("--scan", "docs") + $run_args
    }
    if (-not $has_registry) {
        $run_args = @("--registry", "docs/knowledge_refresh_registry.json") + $run_args
    }

    if (-not (Test-Path -LiteralPath $RUN_SCRIPT)) {
        throw "run.py not found: $RUN_SCRIPT"
    }

    Push-Location $resolved_repo_root
    try {
        & python $RUN_SCRIPT @run_args
    }
    finally {
        Pop-Location
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    knowledge_refresh @args
}

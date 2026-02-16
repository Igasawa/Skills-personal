Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

<#
.SYNOPSIS
Copy portable Codex skill snapshots from this repository into ~/.codex/skills.

.DESCRIPTION
This script reads skill data under skills/portable-codex-skills and restores them
to the user's ~/.codex/skills directory.

.PARAMETER Source
Path to portable skill snapshots. Defaults to:
`<repo>/skills/portable-codex-skills`

.PARAMETER Destination
Destination Codex skill root. Defaults to `$env:USERPROFILE\.codex\skills`.

.PARAMETER Skills
Target skills to restore.

.PARAMETER NoBackup
If specified, existing destination skills are removed without backup.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Source = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")) "skills\\portable-codex-skills"),
    [string]$Destination = (Join-Path $env:USERPROFILE ".codex\\skills"),
    [string[]]$Skills = @(
        "pptx",
        "spreadsheet",
        "xlsx",
        "google-apps-script"
    ),
    [switch]$NoBackup
)

if (-not (Test-Path $Source)) {
    throw "Source folder not found: $Source"
}

if (-not (Test-Path $Destination)) {
    New-Item -ItemType Directory -Path $Destination | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$restored = 0

foreach ($skill in $Skills) {
    $srcPath = Join-Path $Source $skill
    $dstPath = Join-Path $Destination $skill

    if (-not (Test-Path $srcPath)) {
        Write-Warning "Skill not found in source, skipping: $skill (`"$srcPath`")"
        continue
    }

    if ($PSCmdlet.ShouldProcess($dstPath, "Restore skill '$skill' from '$srcPath'")) {
        if (Test-Path $dstPath) {
            if ($NoBackup) {
                Remove-Item -Path $dstPath -Recurse -Force
            }
            else {
                $backupPath = "$dstPath.backup.$timestamp"
                $suffix = 1
                while (Test-Path $backupPath) {
                    $suffix++
                    $backupPath = "$dstPath.backup.$timestamp-$suffix"
                }
                Move-Item -Path $dstPath -Destination $backupPath
            }
        }

        Copy-Item -Path $srcPath -Destination $dstPath -Recurse -Force
        Write-Host "Restored: $skill"
        $restored++
    }
}

Write-Host "Done. Restored $restored of $($Skills.Count) skills."
Write-Host "Restart Codex to pick up new skills."

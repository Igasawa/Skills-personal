param(
  [int]$Year,
  [int]$Month,
  [string]$OutputRoot,
  [switch]$IncludePdfs,
  [switch]$IncludeDebug,
  [switch]$Cleanup,
  [switch]$NoCleanup
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
  return Join-Path $ax "artifacts\mfcloud-expense-receipt-reconcile\$ym"
}

function Resolve-YearMonthInfo([int]$Year, [int]$Month, [string]$RootPath) {
  if ($Year -gt 0 -and $Month -ge 1 -and $Month -le 12) {
    return @{
      HasValue = $true
      Year = $Year
      Month = $Month
      Label = ("{0:D4}-{1:D2}" -f $Year, $Month)
    }
  }
  $leaf = Split-Path -Path $RootPath -Leaf
  if ($leaf -match "^(?<Y>\d{4})-(?<M>\d{2})$") {
    $parsedYear = [int]$Matches["Y"]
    $parsedMonth = [int]$Matches["M"]
    return @{
      HasValue = $true
      Year = $parsedYear
      Month = $parsedMonth
      Label = ("{0:D4}-{1:D2}" -f $parsedYear, $parsedMonth)
    }
  }
  return @{
    HasValue = $false
    Year = 0
    Month = 0
    Label = ""
  }
}

function Remove-DirectoryEntries([string]$Path) {
  $existed = Test-Path -LiteralPath $Path
  $removed = 0
  if ($existed) {
    foreach ($entry in @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)) {
      Remove-Item -LiteralPath $entry.FullName -Recurse -Force
      $removed += 1
    }
  }
  return @{
    existed = [bool]$existed
    removed_entries = [int]$removed
  }
}

if ($Cleanup -and $NoCleanup) {
  throw "-Cleanup and -NoCleanup cannot be used together."
}
$cleanupEnabled = $true
if ($NoCleanup) {
  $cleanupEnabled = $false
} elseif ($Cleanup) {
  $cleanupEnabled = $true
}

$root = Resolve-OutputRoot -Year $Year -Month $Month -OutputRoot $OutputRoot
if (-not (Test-Path -LiteralPath $root)) {
  throw "Output root not found: $root"
}

$ymInfo = Resolve-YearMonthInfo -Year $Year -Month $Month -RootPath $root
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$archiveRoot = Join-Path $root "archive"
$dest = Join-Path $archiveRoot $timestamp
New-Item -ItemType Directory -Force -Path $dest | Out-Null

$copiedTopLevel = New-Object System.Collections.Generic.List[string]
$sourceTopLevel = New-Object System.Collections.Generic.List[string]
foreach ($item in @(Get-ChildItem -LiteralPath $root -Force)) {
  if ($item.Name -ieq "archive") {
    continue
  }
  $sourceTopLevel.Add($item.Name)
  $target = Join-Path $dest $item.Name
  Copy-Item -LiteralPath $item.FullName -Destination $target -Recurse -Force
  $copiedTopLevel.Add($item.Name)
}

$runsMetaCopied = 0
$runsLogCopied = 0
$artifactBaseDir = Split-Path -Path $root -Parent
$runsRoot = Join-Path $artifactBaseDir "_runs"
if (Test-Path -LiteralPath $runsRoot) {
  $runsDest = Join-Path $dest "runs"
  New-Item -ItemType Directory -Force -Path $runsDest | Out-Null
  foreach ($metaPath in @(Get-ChildItem -LiteralPath $runsRoot -Filter "run_*.json" -File | Sort-Object Name)) {
    $includeRun = $true
    if ($ymInfo.HasValue) {
      $includeRun = $false
      try {
        $metaPayload = Get-Content -LiteralPath $metaPath.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $params = $metaPayload.params
        if ($params -and ([int]$params.year -eq $ymInfo.Year) -and ([int]$params.month -eq $ymInfo.Month)) {
          $includeRun = $true
        }
      } catch {
        $includeRun = $false
      }
    }
    if (-not $includeRun) {
      continue
    }
    Copy-Item -LiteralPath $metaPath.FullName -Destination (Join-Path $runsDest $metaPath.Name) -Force
    $runsMetaCopied += 1
    $logPath = Join-Path $runsRoot ([System.IO.Path]::GetFileNameWithoutExtension($metaPath.Name) + ".log")
    if (Test-Path -LiteralPath $logPath) {
      Copy-Item -LiteralPath $logPath -Destination (Join-Path $runsDest ([System.IO.Path]::GetFileName($logPath))) -Force
      $runsLogCopied += 1
    }
  }
  if (-not (Get-ChildItem -LiteralPath $runsDest -Force -ErrorAction SilentlyContinue)) {
    Remove-Item -LiteralPath $runsDest -Force
  }
}

$archiveFiles = @(Get-ChildItem -LiteralPath $dest -Recurse -File -Force)
$archiveBytes = 0
if ($archiveFiles) {
  $archiveBytes = [int64](($archiveFiles | Measure-Object -Property Length -Sum).Sum)
}

$manifestPath = Join-Path $dest "manifest.json"
$zipPath = Join-Path $dest "full_snapshot.zip"
$checksumPath = Join-Path $dest "checksums.sha256"

$zipInputs = @(
  Get-ChildItem -LiteralPath $dest -Force |
    Where-Object { $_.Name -notin @("full_snapshot.zip", "manifest.json", "checksums.sha256") } |
    Select-Object -ExpandProperty FullName
)
if ($zipInputs.Count -gt 0) {
  Compress-Archive -Path $zipInputs -DestinationPath $zipPath -CompressionLevel Optimal -Force
}

$manifestPayload = [ordered]@{
  created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
  ym = $ymInfo.Label
  output_root = $root
  archived_to = $dest
  options = [ordered]@{
    include_pdfs = [bool]$IncludePdfs
    include_debug = [bool]$IncludeDebug
    cleanup = [bool]$cleanupEnabled
  }
  source_top_level = @($sourceTopLevel)
  copied_top_level = @($copiedTopLevel)
  files_total = [int]$archiveFiles.Count
  bytes_total = [int64]$archiveBytes
  runs = [ordered]@{
    runs_root = $runsRoot
    meta_files = [int]$runsMetaCopied
    log_files = [int]$runsLogCopied
  }
  zip_path = $zipPath
}
$manifestPayload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

$hashRows = New-Object System.Collections.Generic.List[string]
foreach ($filePath in @(Get-ChildItem -LiteralPath $dest -Recurse -File -Force | Sort-Object FullName)) {
  if ($filePath.FullName -eq $checksumPath) {
    continue
  }
  $hash = (Get-FileHash -LiteralPath $filePath.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  $relative = $filePath.FullName.Substring($dest.Length).TrimStart("\", "/")
  $hashRows.Add("$hash  $relative")
}
$hashRows | Set-Content -LiteralPath $checksumPath -Encoding UTF8

$cleanupReportPath = ""
$cleanupRemovedTotal = 0
if ($cleanupEnabled) {
  $cleanupTargets = @(
    @{ key = "manual_inbox"; path = (Join-Path $root "manual\inbox") },
    @{ key = "mf_bulk_upload_inbox"; path = (Join-Path $root "mf_bulk_upload\inbox") },
    @{ key = "debug"; path = (Join-Path $root "debug") }
  )
  $cleanupRows = New-Object System.Collections.Generic.List[object]
  foreach ($target in $cleanupTargets) {
    $result = Remove-DirectoryEntries -Path $target.path
    $cleanupRemovedTotal += [int]$result.removed_entries
    $cleanupRows.Add(
      [ordered]@{
        key = $target.key
        path = $target.path
        existed = [bool]$result.existed
        removed_entries = [int]$result.removed_entries
      }
    )
  }
  $cleanupReportPath = Join-Path $root "reports\archive_cleanup_report.json"
  $cleanupRowsArray = @($cleanupRows.ToArray())
  $cleanupPayload = [ordered]@{
    ym = $ymInfo.Label
    archived_to = $dest
    cleanup_enabled = $true
    executed_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
    removed_total = [int]$cleanupRemovedTotal
    targets = $cleanupRowsArray
  }
  $cleanupPayload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $cleanupReportPath -Encoding UTF8
}

Write-Host "Archived to: $dest"
Write-Host "Archive zip: $zipPath"
Write-Host "Archive manifest: $manifestPath"
Write-Host "Archive checksums: $checksumPath"
if ($cleanupEnabled) {
  Write-Host "Cleanup report: $cleanupReportPath"
  Write-Host "Cleanup removed: $cleanupRemovedTotal"
} else {
  Write-Host "Cleanup report: "
  Write-Host "Cleanup removed: 0"
}

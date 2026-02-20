param(
  [string]$AxHome = "",
  [switch]$AllowUnsafeAxHome,
  [switch]$PersistAxHome,
  [switch]$InstallDependencies,
  [switch]$InstallPlaywrightChromium,
  [switch]$InstallGitHooks,
  [switch]$NoDesktopShortcuts,
  [string]$ShortcutDir = "",
  [switch]$ForceConfig,
  [string]$CompanyName = "YOUR_COMPANY_NAME",
  [string]$CompanyNameFallback = "YOUR_COMPANY_NAME_FALLBACK"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-AxHomePath {
  param([string]$Requested)
  $candidate = [string]$Requested
  if (-not $candidate.Trim()) {
    $candidate = [string]$env:AX_HOME
  }
  if (-not $candidate.Trim()) {
    $candidate = [string]([Environment]::GetEnvironmentVariable("AX_HOME", "User"))
  }
  if (-not $candidate.Trim()) {
    $candidate = Join-Path $env:USERPROFILE ".ax"
  }
  return [Environment]::ExpandEnvironmentVariables($candidate.Trim())
}

function Test-Truthy {
  param([string]$Value)
  $raw = [string]$Value
  if (-not $raw.Trim()) {
    return $false
  }
  return @("1", "true", "yes", "on") -contains $raw.Trim().ToLowerInvariant()
}

function Resolve-FullPathSafe {
  param([string]$PathValue)
  $expanded = [Environment]::ExpandEnvironmentVariables($PathValue)
  return [System.IO.Path]::GetFullPath($expanded)
}

function Test-PathWithinRoot {
  param(
    [string]$CandidatePath,
    [string]$RootPath
  )

  $candidateFull = Resolve-FullPathSafe -PathValue $CandidatePath
  $rootFull = Resolve-FullPathSafe -PathValue $RootPath
  $comparison = [System.StringComparison]::OrdinalIgnoreCase

  $candidateNormalized = $candidateFull.TrimEnd('\', '/')
  $rootNormalized = $rootFull.TrimEnd('\', '/')
  if ($candidateNormalized.Equals($rootNormalized, $comparison)) {
    return $true
  }

  $rootWithSep = $rootNormalized + [System.IO.Path]::DirectorySeparatorChar
  return $candidateFull.StartsWith($rootWithSep, $comparison)
}

function Assert-SafeAxHome {
  param(
    [string]$CandidatePath,
    [string]$RepoRootPath,
    [switch]$AllowUnsafe
  )

  $unsafeAllowed = $false
  if ($AllowUnsafe) {
    $unsafeAllowed = $true
  }
  elseif (Test-Truthy -Value ([string]$env:AX_ALLOW_UNSAFE_AX_HOME)) {
    $unsafeAllowed = $true
  }
  if ($unsafeAllowed) {
    return
  }

  $candidateTrimmed = [string]$CandidatePath
  if ($candidateTrimmed.Trim().StartsWith("\\")) {
    throw "AX_HOME safety guard: UNC path is blocked to avoid cross-user shared session/config mixing. If intentional, set AX_ALLOW_UNSAFE_AX_HOME=1 or pass -AllowUnsafeAxHome."
  }

  if (Test-PathWithinRoot -CandidatePath $CandidatePath -RootPath $RepoRootPath) {
    $repoFull = Resolve-FullPathSafe -PathValue $RepoRootPath
    $candidateFull = Resolve-FullPathSafe -PathValue $CandidatePath
    throw "AX_HOME safety guard: AX_HOME must be outside repository root to avoid committing local configs/sessions. repo=$repoFull ax_home=$candidateFull. If intentional, set AX_ALLOW_UNSAFE_AX_HOME=1 or pass -AllowUnsafeAxHome."
  }
}

function Ensure-Directory {
  param([string]$PathValue)
  New-Item -ItemType Directory -Force -Path $PathValue | Out-Null
}

function Write-Utf8NoBomJson {
  param(
    [string]$PathValue,
    [object]$Data
  )
  $json = ($Data | ConvertTo-Json -Depth 12) + "`n"
  $encoding = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($PathValue, $json, $encoding)
}

function Ensure-Command {
  param([string]$Name)
  try {
    return (Get-Command $Name -ErrorAction Stop).Source
  }
  catch {
    throw "Required command not found: $Name"
  }
}

function Resolve-DesktopDirectory {
  param([string]$Requested)

  $candidate = [string]$Requested
  if (-not $candidate.Trim()) {
    $candidate = [string]$env:AX_DASHBOARD_SHORTCUT_DIR
  }
  if ($candidate.Trim()) {
    $expanded = [Environment]::ExpandEnvironmentVariables($candidate.Trim())
    Ensure-Directory -PathValue $expanded
    return $expanded
  }

  $desktopCandidates = @()
  if ($env:OneDrive) {
    $desktopCandidates += (Join-Path $env:OneDrive "Desktop")
  }
  if ($env:USERPROFILE) {
    $desktopCandidates += (Join-Path $env:USERPROFILE "Desktop")
  }

  foreach ($desktopPath in $desktopCandidates) {
    if ($desktopPath -and (Test-Path $desktopPath)) {
      return $desktopPath
    }
  }

  $fallback = [Environment]::GetFolderPath("Desktop")
  if (-not $fallback) {
    if ($desktopCandidates.Count -gt 0) {
      $fallback = $desktopCandidates[0]
    }
    else {
      $fallback = Join-Path $env:USERPROFILE "Desktop"
    }
  }
  Ensure-Directory -PathValue $fallback
  return $fallback
}

function New-DesktopShortcut {
  param(
    [object]$Shell,
    [string]$ShortcutPath,
    [string]$TargetPath,
    [string]$Arguments = "",
    [string]$WorkingDirectory = "",
    [string]$IconLocation = ""
  )

  $shortcut = $Shell.CreateShortcut($ShortcutPath)
  $shortcut.TargetPath = $TargetPath
  if ($Arguments -and $Arguments.Trim()) {
    $shortcut.Arguments = $Arguments
  }
  if ($WorkingDirectory -and $WorkingDirectory.Trim()) {
    $shortcut.WorkingDirectory = $WorkingDirectory
  }
  if ($IconLocation -and $IconLocation.Trim()) {
    $shortcut.IconLocation = $IconLocation
  }
  $shortcut.Save()
}

function Ensure-BootstrapDesktopShortcuts {
  param(
    [string]$SkillRootPath,
    [string]$RequestedShortcutDir
  )

  if ($env:OS -ne "Windows_NT") {
    Write-Host "[bootstrap] skipped desktop shortcuts (non-Windows OS)."
    return
  }

  try {
    $desktopDir = Resolve-DesktopDirectory -Requested $RequestedShortcutDir
    $shell = New-Object -ComObject WScript.Shell

    $powershellExe = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path $powershellExe)) {
      $powershellExe = Ensure-Command -Name powershell
    }

    $dashboardScriptPath = Join-Path $SkillRootPath "scripts\start_dashboard.ps1"
    $dashboardShortcutPath = Join-Path $desktopDir "MF_Expense_Dashboard.lnk"
    $dashboardArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$dashboardScriptPath`""
    New-DesktopShortcut -Shell $shell -ShortcutPath $dashboardShortcutPath -TargetPath $powershellExe -Arguments $dashboardArgs -WorkingDirectory $SkillRootPath -IconLocation "$powershellExe,0"

    $explorerExe = Join-Path $env:WINDIR "explorer.exe"
    if (-not (Test-Path $explorerExe)) {
      $explorerExe = "explorer.exe"
    }
    $folderShortcutPath = Join-Path $desktopDir "MF_Expense_Skill_Folder.lnk"
    $folderArgs = "`"$SkillRootPath`""
    New-DesktopShortcut -Shell $shell -ShortcutPath $folderShortcutPath -TargetPath $explorerExe -Arguments $folderArgs -WorkingDirectory $SkillRootPath -IconLocation "$explorerExe,0"

    Write-Host "[bootstrap] shortcut = $dashboardShortcutPath"
    Write-Host "[bootstrap] shortcut = $folderShortcutPath"
  }
  catch {
    Write-Warning "[bootstrap] desktop shortcut creation failed: $($_.Exception.Message)"
  }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillRoot = Resolve-Path (Join-Path $scriptDir "..")
$repoRoot = Resolve-Path (Join-Path $skillRoot "..\..")

$resolvedAxHome = Resolve-AxHomePath -Requested $AxHome
Assert-SafeAxHome -CandidatePath $resolvedAxHome -RepoRootPath $repoRoot -AllowUnsafe:$AllowUnsafeAxHome
$env:AX_HOME = $resolvedAxHome

if ($PersistAxHome) {
  [Environment]::SetEnvironmentVariable("AX_HOME", $resolvedAxHome, "User")
}

$configsDir = Join-Path $resolvedAxHome "configs"
$sessionsDir = Join-Path $resolvedAxHome "sessions"
$artifactsDir = Join-Path $resolvedAxHome "artifacts\mfcloud-expense-receipt-reconcile"
$runsDir = Join-Path $artifactsDir "_runs"
$logsDir = Join-Path $resolvedAxHome "logs"

Ensure-Directory -PathValue $configsDir
Ensure-Directory -PathValue $sessionsDir
Ensure-Directory -PathValue $artifactsDir
Ensure-Directory -PathValue $runsDir
Ensure-Directory -PathValue $logsDir

$skillConfigPath = Join-Path $configsDir "mfcloud-expense-receipt-reconcile.json"
$orgProfilePath = Join-Path $configsDir "org-profile.json"

$skillConfigTemplate = [ordered]@{
  config = [ordered]@{
    tenant = [ordered]@{
      key = "default"
      name = $CompanyName
      receipt = [ordered]@{
        name = $CompanyName
        name_fallback = $CompanyNameFallback
      }
      urls = [ordered]@{
        amazon_orders = "https://www.amazon.co.jp/gp/your-account/order-history"
        rakuten_orders = "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order"
        mfcloud_accounts = "https://expense.moneyforward.com/accounts"
        mfcloud_expense_list = $null
      }
    }
    receipt_name = $CompanyName
    receipt_name_fallback = $CompanyNameFallback
    urls = [ordered]@{
      amazon_orders = "https://www.amazon.co.jp/gp/your-account/order-history"
      mfcloud_accounts = "https://expense.moneyforward.com/accounts"
      mfcloud_expense_list = $null
    }
    rakuten = [ordered]@{
      enabled = $false
      orders_url = "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order"
    }
    playwright = [ordered]@{
      headed = $true
      slow_mo_ms = 0
    }
    matching = [ordered]@{
      date_window_days = 7
      max_candidates_per_mf = 5
    }
  }
}

$orgProfileTemplate = [ordered]@{
  config_version = "1"
  profile_key = "default"
  organization = [ordered]@{
    name = $CompanyName
    receipt = [ordered]@{
      name = $CompanyName
      name_fallback = $CompanyNameFallback
    }
    locale = $null
    timezone = $null
  }
  urls = [ordered]@{
    amazon_orders = "https://www.amazon.co.jp/gp/your-account/order-history"
    rakuten_orders = "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order"
    mfcloud_accounts = "https://expense.moneyforward.com/accounts"
    mfcloud_expense_list = $null
  }
}

if ($ForceConfig -or -not (Test-Path $skillConfigPath)) {
  Write-Utf8NoBomJson -PathValue $skillConfigPath -Data $skillConfigTemplate
}

if ($ForceConfig -or -not (Test-Path $orgProfilePath)) {
  Write-Utf8NoBomJson -PathValue $orgProfilePath -Data $orgProfileTemplate
}

if ($InstallGitHooks) {
  & (Ensure-Command -Name powershell) -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\bootstrap_kil.ps1")
}

if ($InstallDependencies -or $InstallPlaywrightChromium) {
  $python = $null
  if ($InstallDependencies) {
    $python = Ensure-Command -Name python
  }
  $npm = Ensure-Command -Name npm

  Push-Location $skillRoot
  try {
    if ($InstallDependencies) {
      & $python -m pip install -r "requirements-dev.txt"
      if ($LASTEXITCODE -ne 0) {
        throw "pip install failed."
      }
      & $npm ci
      if ($LASTEXITCODE -ne 0) {
        throw "npm ci failed."
      }
    }
    elseif (-not (Test-Path (Join-Path $skillRoot "node_modules\\playwright\\package.json"))) {
      & $npm ci
      if ($LASTEXITCODE -ne 0) {
        throw "npm ci failed."
      }
    }

    if ($InstallPlaywrightChromium) {
      & $npm exec playwright install chromium
      if ($LASTEXITCODE -ne 0) {
        throw "playwright chromium install failed."
      }
    }
  }
  finally {
    Pop-Location
  }
}

if (-not $NoDesktopShortcuts) {
  Ensure-BootstrapDesktopShortcuts -SkillRootPath $skillRoot -RequestedShortcutDir $ShortcutDir
}

Write-Host "[bootstrap] completed."
Write-Host "[bootstrap] AX_HOME = $resolvedAxHome"
Write-Host "[bootstrap] config  = $skillConfigPath"
Write-Host "[bootstrap] profile = $orgProfilePath"
Write-Host "[bootstrap] next: edit company URLs and run Playwright login for amazon/rakuten/mfcloud sessions."

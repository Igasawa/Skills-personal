param(
  [switch]$NoOpen,
  [switch]$Restart,
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8765,
  [int]$WaitSeconds = 120
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location $root

if ($Port -lt 1 -or $Port -gt 65535) {
  throw "Invalid -Port: $Port (expected 1-65535)."
}
if ($WaitSeconds -lt 1) {
  throw "Invalid -WaitSeconds: $WaitSeconds (expected >= 1)."
}

$logDir = Join-Path $env:USERPROFILE ".ax\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logOut = Join-Path $logDir "mf_dashboard_uvicorn.out.log"
$logErr = Join-Path $logDir "mf_dashboard_uvicorn.err.log"

$url = "http://$BindHost`:$Port/"
$shortcutName = "MF_Expense_Dashboard"

function Get-DesktopDirectory {
  $override = [string]($env:AX_DASHBOARD_SHORTCUT_DIR)
  if ($override.Trim()) {
    $expanded = [Environment]::ExpandEnvironmentVariables($override.Trim())
    New-Item -ItemType Directory -Force -Path $expanded | Out-Null
    return $expanded
  }

  $candidates = @()
  if ($env:OneDrive) {
    $candidates += (Join-Path $env:OneDrive "Desktop")
  }
  if ($env:USERPROFILE) {
    $candidates += (Join-Path $env:USERPROFILE "Desktop")
  }

  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path $candidate)) {
      return $candidate
    }
  }

  $fallback = $null
  if ($candidates.Count -gt 0) {
    $fallback = $candidates[0]
  } else {
    $fallback = [Environment]::GetFolderPath("Desktop")
  }
  if (-not $fallback) {
    $fallback = Join-Path $env:USERPROFILE "Desktop"
  }
  New-Item -ItemType Directory -Force -Path $fallback | Out-Null
  return $fallback
}

function Ensure-DashboardDesktopShortcut {
  if ($env:OS -ne "Windows_NT") {
    return
  }
  try {
    $desktopDir = Get-DesktopDirectory
    $shell = New-Object -ComObject WScript.Shell
    $targetPath = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path $targetPath)) {
      try {
        $targetPath = (Get-Command powershell -ErrorAction Stop).Source
      } catch {
        $targetPath = $null
      }
    }
    if (-not $targetPath) {
      return
    }

    $shortcutPaths = @()
    $existingShortcuts = Get-ChildItem -Path $desktopDir -Filter "*.lnk" -File -ErrorAction SilentlyContinue
    foreach ($existingPath in $existingShortcuts) {
      try {
        $existingShortcut = $shell.CreateShortcut($existingPath.FullName)
        $existingArgs = [string]$existingShortcut.Arguments
        if ($existingArgs -match "start_dashboard\.ps1") {
          $shortcutPaths += $existingPath.FullName
        }
      } catch {
        continue
      }
    }

    $defaultShortcutPath = Join-Path $desktopDir "$shortcutName.lnk"
    if ($shortcutPaths -notcontains $defaultShortcutPath) {
      $shortcutPaths += $defaultShortcutPath
    }

    foreach ($shortcutPath in ($shortcutPaths | Sort-Object -Unique)) {
      $shortcut = $shell.CreateShortcut($shortcutPath)
      $shortcut.TargetPath = $targetPath
      $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
      $shortcut.WorkingDirectory = $root
      $shortcut.IconLocation = "$targetPath,0"
      $shortcut.Save()
    }
  } catch {
    # Shortcut regeneration is best effort; startup should continue even if it fails.
  }
}

function Find-PythonRuntime {
  $python = $null
  $pythonPrefix = @()
  $venvPython = Join-Path $root ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    $python = $venvPython
  }
  if (-not $python) {
    try { $python = (Get-Command python -ErrorAction Stop).Source } catch {}
  }
  if (-not $python) {
    try {
      $python = (Get-Command py -ErrorAction Stop).Source
      $pythonPrefix = @("-3")
    } catch {}
  }
  if (-not $python) {
    $candidates = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python" -Recurse -Filter python.exe -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending |
      Select-Object -ExpandProperty FullName
    if ($candidates) {
      $python = $candidates[0]
    }
  }
  return @{
    Python = $python
    Prefix = $pythonPrefix
  }
}

function Get-DashboardImportNames {
  $requirementsPath = Join-Path $root "dashboard\requirements.txt"
  if (-not (Test-Path $requirementsPath)) {
    return @("fastapi", "uvicorn", "jinja2", "pypdf")
  }

  $imports = @()
  foreach ($line in Get-Content -Path $requirementsPath) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) {
      continue
    }

    $name = $trimmed -replace "\[.*\]", ""
    $name = $name -replace "[<>=!~].*$", ""
    $name = ($name -replace "-", "_").Trim()
    if ($name) {
      $imports += $name
    }
  }

  if (-not $imports) {
    return @("fastapi", "uvicorn", "jinja2", "pypdf")
  }
  return @($imports | Sort-Object -Unique)
}

function Test-PythonImportsAvailable {
  param(
    [string]$Python,
    [string[]]$Prefix = @(),
    [string[]]$Modules = @()
  )
  if (-not $Python -or -not $Modules -or $Modules.Count -eq 0) {
    return $false
  }
  $importScript = ($Modules | ForEach-Object { "import $_" }) -join "; "
  $probeArgs = @()
  if ($Prefix) {
    $probeArgs += $Prefix
  }
  $probeArgs += @("-c", $importScript)
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $Python @probeArgs 1>$null 2>$null
  } catch {
    return $false
  } finally {
    $ErrorActionPreference = $prev
  }
  return ($LASTEXITCODE -eq 0)
}

function Ensure-UvBinary {
  $runtimeDir = Join-Path $env:USERPROFILE ".ax\runtime\uv"
  $uvExe = Join-Path $runtimeDir "uv.exe"
  if (Test-Path $uvExe) {
    return $uvExe
  }
  New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
  $zipPath = Join-Path $runtimeDir "uv-windows.zip"
  Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $zipPath
  Expand-Archive -Path $zipPath -DestinationPath $runtimeDir -Force
  Remove-Item -Force $zipPath
  $found = Get-ChildItem -Path $runtimeDir -Recurse -Filter uv.exe -ErrorAction SilentlyContinue |
    Sort-Object FullName |
    Select-Object -First 1 -ExpandProperty FullName
  if (-not $found) {
    throw "uv bootstrap failed: uv.exe was not found after extraction."
  }
  if ($found -ne $uvExe) {
    Copy-Item -Path $found -Destination $uvExe -Force
  }
  return $uvExe
}

function Get-ActiveDashboardListener {
  param([int]$LocalPort)
  return Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Stop-DashboardListener {
  param($Listener)
  if ($Listener -and $Listener.OwningProcess) {
    try {
      Stop-Process -Id $Listener.OwningProcess -Force -ErrorAction Stop
    } catch {}
    Start-Sleep -Seconds 1
  }
}

function Get-LatestDashboardCodeWriteTime {
  $dashboardDir = Join-Path $root "dashboard"
  $codeFiles = @()
  if (Test-Path $dashboardDir) {
    $codeFiles = Get-ChildItem -Path $dashboardDir -Recurse -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Extension -in @(".py", ".html", ".js", ".css") }
  }
  if (Test-Path $scriptPath) {
    $codeFiles = @($codeFiles) + @(Get-Item -Path $scriptPath)
  }
  if (-not $codeFiles -or $codeFiles.Count -eq 0) {
    return $null
  }
  return ($codeFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty LastWriteTime)
}

function Should-RestartForCodeChange {
  param([int]$LocalPort)
  $listener = Get-ActiveDashboardListener -LocalPort $LocalPort
  if (-not $listener -or -not $listener.OwningProcess) {
    return $false
  }
  try {
    $proc = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
  } catch {
    return $false
  }
  $latestWrite = Get-LatestDashboardCodeWriteTime
  if (-not $latestWrite) {
    return $false
  }
  return ($latestWrite -gt $proc.StartTime.AddSeconds(1))
}

Ensure-DashboardDesktopShortcut

try {
  $resp = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 2
  if ($resp.StatusCode -eq 200) {
    $listener = Get-ActiveDashboardListener -LocalPort $Port
    if ($Restart -or (Should-RestartForCodeChange -LocalPort $Port)) {
      Stop-DashboardListener -Listener $listener
    } else {
      if (-not $NoOpen) {
        Start-Process $url
      }
      return
    }
  }
} catch {}

$pythonInfo = Find-PythonRuntime
$python = $pythonInfo.Python
$pythonPrefix = @($pythonInfo.Prefix)
$requiredImports = Get-DashboardImportNames
$pythonHasDashboardDeps = Test-PythonImportsAvailable -Python $python -Prefix $pythonPrefix -Modules $requiredImports

$launcher = $null
$args = @()
if ($python -and $pythonHasDashboardDeps) {
  $launcher = $python
  $args = @(
    $pythonPrefix + @(
      "-m", "uvicorn",
      "dashboard.app:app",
      "--host", $BindHost,
      "--port", "$Port",
      "--app-dir", $root
    )
  )
} else {
  $uv = Ensure-UvBinary
  $launcher = $uv
  $args = @(
    "run",
    "--python", "3.11",
    "--with-requirements", (Join-Path $root "dashboard\requirements.txt"),
    "uvicorn",
    "dashboard.app:app",
    "--host", $BindHost,
    "--port", "$Port",
    "--app-dir", $root
  )
}

Start-Process -FilePath $launcher -ArgumentList $args -WorkingDirectory $root -RedirectStandardOutput $logOut -RedirectStandardError $logErr -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  try {
    $resp = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 5
    if ($resp.StatusCode -eq 200) {
      if (-not $NoOpen) {
        Start-Process $url
      }
      return
    }
  } catch {}
}

Write-Host "Dashboard failed. See logs: $logOut , $logErr"

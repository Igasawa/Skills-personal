$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location $root

$logDir = Join-Path $env:USERPROFILE ".ax\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logOut = Join-Path $logDir "mf_dashboard_uvicorn.out.log"
$logErr = Join-Path $logDir "mf_dashboard_uvicorn.err.log"

$url = "http://127.0.0.1:8765/"
try {
  $resp = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 2
  if ($resp.StatusCode -eq 200) {
    Start-Process $url
    return
  }
} catch {}

$python = $null
$pythonPrefix = @()
try { $python = (Get-Command python -ErrorAction Stop).Source } catch {}
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
if (-not $python) { throw "Python runtime not found. Install Python 3.11+ and expose python or py in PATH." }

$args = @(
  $pythonPrefix + @(
    "-m", "uvicorn",
    "dashboard.app:app",
    "--host", "127.0.0.1",
    "--port", "8765",
    "--app-dir", $root
  )
)

Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $root -RedirectStandardOutput $logOut -RedirectStandardError $logErr -WindowStyle Hidden

Start-Sleep -Seconds 2
try {
  $resp = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 5
  if ($resp.StatusCode -eq 200) {
    Start-Process $url
    return
  }
} catch {}

Write-Host "Dashboard failed. See logs: $logOut , $logErr"

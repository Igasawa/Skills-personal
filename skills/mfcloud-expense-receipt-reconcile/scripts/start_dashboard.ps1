$ErrorActionPreference = "Stop"

$root = "C:\Users\Tatsuo-2023\Projects\PersonalSkills\skills\mfcloud-expense-receipt-reconcile"
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
try { $python = (Get-Command python).Source } catch {}
if (-not $python -and (Test-Path "C:\Python313\python.exe")) { $python = "C:\Python313\python.exe" }
if (-not $python) { throw "python not found" }

$args = @(
  "-m", "uvicorn",
  "dashboard.app:app",
  "--host", "127.0.0.1",
  "--port", "8765",
  "--app-dir", $root
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

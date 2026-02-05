$ErrorActionPreference = "Stop"

$root = "C:\Users\Tatsuo-2023\Projects\PersonalSkills\skills\mfcloud-expense-receipt-reconcile"
Set-Location $root

$appDir = Join-Path $root "dashboard"
$args = @(
  "-m", "uvicorn",
  "dashboard.app:app",
  "--host", "127.0.0.1",
  "--port", "8765",
  "--app-dir", $root
)
Start-Process -FilePath (Get-Command python).Source -ArgumentList $args -WorkingDirectory $root

Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8765/"

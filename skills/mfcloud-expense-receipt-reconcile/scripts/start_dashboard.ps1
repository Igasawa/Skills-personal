$ErrorActionPreference = "Stop"

$root = "c:\Users\TatsuoIgasawa\.vscode\Skillpersonal\skills\mfcloud-expense-receipt-reconcile"
Set-Location $root

$appDir = Join-Path $root "dashboard"
$args = @(
  "-m", "uvicorn",
  "app:app",
  "--host", "127.0.0.1",
  "--port", "8765",
  "--app-dir", $appDir
)
Start-Process -FilePath (Get-Command python).Source -ArgumentList $args -WorkingDirectory $root

Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8765/"

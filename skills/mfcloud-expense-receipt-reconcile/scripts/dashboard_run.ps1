$ErrorActionPreference = "Stop"

$skillRoot = "C:\Users\Tatsuo-2023\Projects\PersonalSkills\skills\mfcloud-expense-receipt-reconcile"
$mfUrl = "https://expense.moneyforward.com/transactions"

Set-Location $skillRoot

Write-Host "Running monthly fetch + reconcile..."
python scripts/run.py --mfcloud-expense-list-url $mfUrl --enable-rakuten --interactive

Write-Host "Building print list (Amazon/Rakuten PDFs only)..."
python scripts/collect_print.py

$outputRoot = "$env:USERPROFILE\.ax\artifacts\mfcloud-expense-receipt-reconcile\$(Get-Date -Format 'yyyy-MM')"
$reportsDir = Join-Path $outputRoot "reports"

if (Test-Path $reportsDir) {
  Start-Process $reportsDir
}

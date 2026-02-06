$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$mfUrl = "https://expense.moneyforward.com/outgo_input"

function Resolve-PythonRuntime {
  $cmd = $null
  $prefix = @()
  try { $cmd = (Get-Command python -ErrorAction Stop).Source } catch {}
  if (-not $cmd) {
    try {
      $cmd = (Get-Command py -ErrorAction Stop).Source
      $prefix = @("-3")
    } catch {}
  }
  if (-not $cmd) {
    $candidates = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python" -Recurse -Filter python.exe -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending |
      Select-Object -ExpandProperty FullName
    if ($candidates) { $cmd = $candidates[0] }
  }
  if (-not $cmd) { throw "Python runtime not found. Install Python 3.11+ and expose python or py in PATH." }
  return @{ Command = $cmd; Prefix = $prefix }
}

Set-Location $skillRoot
$python = Resolve-PythonRuntime

Write-Host "Running monthly fetch + reconcile..."
& $python.Command @(
  $python.Prefix + @(
    "scripts/run.py",
    "--mfcloud-expense-list-url", $mfUrl,
    "--enable-rakuten",
    "--interactive"
  )
)

Write-Host "Building print list (Amazon/Rakuten PDFs only)..."
& $python.Command @(
  $python.Prefix + @(
    "scripts/collect_print.py"
  )
)

$outputRoot = "$env:USERPROFILE\.ax\artifacts\mfcloud-expense-receipt-reconcile\$(Get-Date -Format 'yyyy-MM')"
$reportsDir = Join-Path $outputRoot "reports"

if (Test-Path $reportsDir) {
  Start-Process $reportsDir
}

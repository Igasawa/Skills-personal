param(
  [string]$BaseUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"

$session = "wf-trigger-smoke-" + (Get-Date -Format "yyyyMMddHHmmss")
$outputDir = Join-Path $PSScriptRoot "..\output\playwright"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$reportPath = Join-Path $outputDir ("workflow_trigger_execution_smoke_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".txt")
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Invoke-Pw {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$CliArgs
  )
  $base = @("--yes", "--package", "@playwright/cli", "playwright-cli", "-s=$session")
  & npx @base @CliArgs
  if ($LASTEXITCODE -ne 0) {
    throw "playwright-cli failed: $($CliArgs -join ' ')"
  }
}

function Assert-RunCode {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Code,
    [Parameter(Mandatory = $true)]
    [string]$Label
  )
  try {
    Invoke-Pw -CliArgs @("run-code", $Code)
  } catch {
    throw "E2E assertion failed: $Label`n$($_.Exception.Message)"
  }
}

$workspaceRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $workspaceRoot
try {
  $lines = @()
  $lines += "session=$session"
  $lines += "base_url=$BaseUrl"

  Invoke-Pw -CliArgs @("open", "$BaseUrl/expense-workflow-copy")
  Invoke-Pw -CliArgs @("run-code", "await page.locator('#template-step-add').click()")
  Invoke-Pw -CliArgs @("run-code", "await page.locator('[data-template-step-title]').first().fill('Trigger Execution Smoke Step 1')")

$code = @'
const fields = await page.locator('.template-step-select-field').count();
if (fields < 3) {
  throw new Error('missing select field wrappers: ' + fields);
}
'@
  Assert-RunCode -Label "select fields must be visible" -Code $code
  $lines += "check=field_captions:pass"

$code = @'
const line = await page.locator('#workflow-create-preview-list li').nth(3).innerText();
if (!line.includes('Trigger Execution Smoke Step 1')) {
  throw new Error('preview title missing: ' + line);
}
const parts = line.split(' / ').filter(Boolean);
if (parts.length < 4) {
  throw new Error('preview format mismatch: ' + line);
}
'@
  Assert-RunCode -Label "preview format must include trigger and mode sections" -Code $code
  $lines += "check=preview_labels:pass"

$code = @'
await page.locator('[data-template-step-type]').first().selectOption('agent');
const modeOptions = await page
  .locator('[data-template-step-execution-mode]')
  .first()
  .locator('option')
  .evaluateAll((nodes) => nodes.map((node) => node.value));
if (!modeOptions.includes('auto')) {
  throw new Error('unexpected mode values for agent: ' + JSON.stringify(modeOptions));
}
'@
  Assert-RunCode -Label "agent step must allow auto mode" -Code $code
  $lines += "check=agent_auto_mode_option:pass"

$code = @'
await page.locator('[data-template-step-type]').first().selectOption('manual');
const modeOptions = await page
  .locator('[data-template-step-execution-mode]')
  .first()
  .locator('option')
  .evaluateAll((nodes) => nodes.map((node) => node.value));
if (modeOptions.length !== 1 || modeOptions[0] !== 'manual_confirm') {
  throw new Error('unexpected mode values for manual: ' + JSON.stringify(modeOptions));
}
'@
  Assert-RunCode -Label "manual step must force manual_confirm" -Code $code
  $lines += "check=manual_mode_constraint:pass"

  Invoke-Pw -CliArgs @("run-code", "await page.locator('#template-step-add').click()")
$code = @'
const triggerOptions = await page
  .locator('[data-template-step-trigger-kind]')
  .nth(1)
  .locator('option')
  .evaluateAll((nodes) => nodes.map((node) => node.value));
if (triggerOptions.length !== 1 || triggerOptions[0] !== 'after_previous') {
  throw new Error('unexpected trigger values for step2: ' + JSON.stringify(triggerOptions));
}
'@
  Assert-RunCode -Label "step2 trigger must be after_previous only" -Code $code
  $lines += "check=step2_trigger_constraint:pass"

  Invoke-Pw -CliArgs @("screenshot")

  $lines += "page=expense-workflow-copy"
  $lines += "result=pass"

  [System.IO.File]::WriteAllLines($reportPath, $lines, $utf8NoBom)
  Write-Output "Trigger/Execution smoke report: $reportPath"
} finally {
  Pop-Location
}

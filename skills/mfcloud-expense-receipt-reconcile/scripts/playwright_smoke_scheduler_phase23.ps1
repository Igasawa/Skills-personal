param(
  [string]$BaseUrl = "http://127.0.0.1:8765",
  [string]$TemplateId = "e2e_scheduler_phase23"
)

$ErrorActionPreference = "Stop"

$session = "wf-scheduler-phase23-" + (Get-Date -Format "yyyyMMddHHmmss")
$outputDir = Join-Path $PSScriptRoot "..\output\playwright"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$reportPath = Join-Path $outputDir ("workflow_scheduler_phase23_smoke_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".txt")
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
  $lines += "template_id=$TemplateId"

  Invoke-Pw -CliArgs @("open", "$BaseUrl/expense-workflow-copy")

$injectTemplateContext = @'
const templateId = "__TEMPLATE_ID__";
const templateInput = document.querySelector('#run-form [name=template_id]');
if (!templateInput) throw new Error('template_id input missing');
templateInput.value = templateId;
document.dispatchEvent(
  new CustomEvent('scheduler-context-changed', {
    bubbles: true,
    detail: {
      template_id: templateId,
      card_id: `workflow-template:${templateId}`,
      action_key: 'preflight',
    },
  })
);
'@
  $injectTemplateContext = $injectTemplateContext.Replace("__TEMPLATE_ID__", $TemplateId)
  Assert-RunCode -Label "inject template context" -Code $injectTemplateContext

$checkRecurrenceOptions = @'
const values = await page
  .locator('#scheduler-recurrence option')
  .evaluateAll((nodes) => nodes.map((node) => node.value));
const required = ['once', 'daily', 'weekly', 'monthly'];
for (const value of required) {
  if (!values.includes(value)) {
    throw new Error('missing recurrence option: ' + value + ' / options=' + JSON.stringify(values));
  }
}
'@
  Assert-RunCode -Label "scheduler recurrence options include once/daily/weekly/monthly" -Code $checkRecurrenceOptions
  $lines += "check=recurrence_options:pass"

$saveWeekly = @'
await page.locator('#scheduler-toggle').uncheck();
await page.locator('#scheduler-run-date').fill('2099-03-05');
await page.locator('#scheduler-run-time').fill('09:15');
await page.locator('#scheduler-catch-up').selectOption('run_on_startup');
await page.locator('#scheduler-recurrence').selectOption('weekly');
await page.locator('#scheduler-save').click();
await page.waitForTimeout(300);
'@
  Assert-RunCode -Label "save weekly scheduler state" -Code $saveWeekly

$assertWeeklyPersisted = @'
const templateId = "__TEMPLATE_ID__";
const res = await fetch(`/api/scheduler/state?template_id=${encodeURIComponent(templateId)}`, { cache: 'no-store' });
if (!res.ok) throw new Error('scheduler GET failed: ' + res.status);
const body = await res.json();
if (String(body.recurrence || '') !== 'weekly') {
  throw new Error('recurrence is not weekly: ' + JSON.stringify(body));
}
if (String(body.run_date || '') !== '2099-03-05') {
  throw new Error('run_date mismatch: ' + JSON.stringify(body));
}
if (String(body.run_time || '') !== '09:15') {
  throw new Error('run_time mismatch: ' + JSON.stringify(body));
}
'@
  $assertWeeklyPersisted = $assertWeeklyPersisted.Replace("__TEMPLATE_ID__", $TemplateId)
  Assert-RunCode -Label "weekly settings persisted via API" -Code $assertWeeklyPersisted
  $lines += "check=weekly_persist:pass"

$saveMonthly = @'
await page.locator('#scheduler-run-date').fill('2099-01-31');
await page.locator('#scheduler-run-time').fill('10:30');
await page.locator('#scheduler-recurrence').selectOption('monthly');
await page.locator('#scheduler-save').click();
await page.waitForTimeout(300);
'@
  Assert-RunCode -Label "save monthly scheduler state" -Code $saveMonthly

$assertMonthlyPersisted = @'
const templateId = "__TEMPLATE_ID__";
const res = await fetch(`/api/scheduler/state?template_id=${encodeURIComponent(templateId)}`, { cache: 'no-store' });
if (!res.ok) throw new Error('scheduler GET failed: ' + res.status);
const body = await res.json();
if (String(body.recurrence || '') !== 'monthly') {
  throw new Error('recurrence is not monthly: ' + JSON.stringify(body));
}
if (String(body.run_date || '') !== '2099-01-31') {
  throw new Error('run_date mismatch: ' + JSON.stringify(body));
}
if (String(body.run_time || '') !== '10:30') {
  throw new Error('run_time mismatch: ' + JSON.stringify(body));
}
'@
  $assertMonthlyPersisted = $assertMonthlyPersisted.Replace("__TEMPLATE_ID__", $TemplateId)
  Assert-RunCode -Label "monthly settings persisted via API" -Code $assertMonthlyPersisted
  $lines += "check=monthly_persist:pass"

  Invoke-Pw -CliArgs @("screenshot")
  $lines += "result=pass"

  [System.IO.File]::WriteAllLines($reportPath, $lines, $utf8NoBom)
  Write-Output "Scheduler Phase 2.3 smoke report: $reportPath"
} finally {
  Pop-Location
}

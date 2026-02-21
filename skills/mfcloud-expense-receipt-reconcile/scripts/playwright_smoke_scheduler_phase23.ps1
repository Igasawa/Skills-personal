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

$saveRetryTarget = @'
const templateId = "__TEMPLATE_ID__";
const now = new Date(Date.now() - 90_000);
const yyyy = now.getFullYear();
const mm = String(now.getMonth() + 1).padStart(2, '0');
const dd = String(now.getDate()).padStart(2, '0');
const hh = String(now.getHours()).padStart(2, '0');
const mi = String(now.getMinutes()).padStart(2, '0');
const runDate = `${yyyy}-${mm}-${dd}`;
const runTime = `${hh}:${mi}`;

const yearInput = document.querySelector('#run-form [name=year]');
const monthInput = document.querySelector('#run-form [name=month]');
if (!yearInput || !monthInput) throw new Error('year/month hidden inputs missing');
yearInput.value = '2099';
monthInput.value = '12';

document.dispatchEvent(
  new CustomEvent('scheduler-context-changed', {
    bubbles: true,
    detail: {
      template_id: templateId,
      card_id: `workflow-template:${templateId}`,
      action_key: 'amazon_download',
    },
  })
);

await page.locator('#scheduler-toggle').check();
await page.locator('#scheduler-catch-up').selectOption('run_on_startup');
await page.locator('#scheduler-recurrence').selectOption('once');
await page.locator('#scheduler-run-date').fill(runDate);
await page.locator('#scheduler-run-time').fill(runTime);
await page.locator('#scheduler-save').click();
await page.waitForTimeout(500);
'@
  $saveRetryTarget = $saveRetryTarget.Replace("__TEMPLATE_ID__", $TemplateId)
  Assert-RunCode -Label "save retry target state (expected first failure)" -Code $saveRetryTarget

$assertRetryScheduled = @'
const templateId = "__TEMPLATE_ID__";
const res = await fetch(`/api/scheduler/state?template_id=${encodeURIComponent(templateId)}`, { cache: 'no-store' });
if (!res.ok) throw new Error('scheduler GET failed: ' + res.status);
const body = await res.json();
const last = body.last_result && typeof body.last_result === 'object' ? body.last_result : {};
if (String(last.status || '') !== 'deferred') {
  throw new Error('expected deferred after first failure: ' + JSON.stringify(body));
}
if (String(last.reason_code || '') !== 'retry_scheduled') {
  throw new Error('expected retry_scheduled after first failure: ' + JSON.stringify(body));
}
if (body.enabled !== true) {
  throw new Error('expected enabled=true while retry pending: ' + JSON.stringify(body));
}
'@
  $assertRetryScheduled = $assertRetryScheduled.Replace("__TEMPLATE_ID__", $TemplateId)
  Assert-RunCode -Label "first failure schedules single retry" -Code $assertRetryScheduled
  $lines += "check=retry_scheduled:pass"

$waitAndTriggerRetry = @'
const templateId = "__TEMPLATE_ID__";
let retrySeconds = 60;
try {
  const healthRes = await fetch('/api/scheduler/health?limit=1', { cache: 'no-store' });
  if (healthRes.ok) {
    const health = await healthRes.json();
    const fromApi = Number.parseInt(String(health.failure_retry_seconds ?? ''), 10);
    if (Number.isFinite(fromApi) && fromApi > 0) {
      retrySeconds = fromApi;
    }
  }
} catch {}

const timeoutMs = (retrySeconds + 20) * 1000;
const deadline = Date.now() + timeoutMs;
let lastBody = null;
while (Date.now() < deadline) {
  const res = await fetch(`/api/scheduler/state?template_id=${encodeURIComponent(templateId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error('scheduler POST failed: ' + res.status + ' ' + JSON.stringify(body));
  }
  const body = await res.json();
  lastBody = body;
  const last = body.last_result && typeof body.last_result === 'object' ? body.last_result : {};
  if (String(last.status || '') === 'failed' && String(last.reason_code || '') === 'retry_exhausted' && body.enabled === false) {
    return;
  }
  await new Promise((resolve) => setTimeout(resolve, 1500));
}
throw new Error(
  'retry exhaustion not observed in time; retrySeconds=' + retrySeconds + '; lastBody=' + JSON.stringify(lastBody)
);
'@
  $waitAndTriggerRetry = $waitAndTriggerRetry.Replace("__TEMPLATE_ID__", $TemplateId)
  Assert-RunCode -Label "retry attempt exhausts and fails" -Code $waitAndTriggerRetry
  $lines += "check=retry_exhausted:pass"

$recordRetryConfig = @'
const res = await fetch('/api/scheduler/health?limit=1', { cache: 'no-store' });
if (!res.ok) {
  throw new Error('scheduler health GET failed: ' + res.status);
}
const body = await res.json();
const retrySeconds = Number.parseInt(String(body.failure_retry_seconds ?? ''), 10);
const retryMaxAttempts = Number.parseInt(String(body.failure_retry_max_attempts ?? ''), 10);
if (!Number.isFinite(retrySeconds) || retrySeconds < 1) {
  throw new Error('invalid failure_retry_seconds: ' + JSON.stringify(body));
}
if (!Number.isFinite(retryMaxAttempts) || retryMaxAttempts < 1) {
  throw new Error('invalid failure_retry_max_attempts: ' + JSON.stringify(body));
}
window.__schedulerRetryConfig = { retrySeconds, retryMaxAttempts };
'@
  Assert-RunCode -Label "read scheduler retry config from health endpoint" -Code $recordRetryConfig
$readRetryConfig = @'
const cfg = window.__schedulerRetryConfig || {};
if (!cfg.retrySeconds || !cfg.retryMaxAttempts) {
  throw new Error('scheduler retry config not captured');
}
'@
  Assert-RunCode -Label "scheduler retry config captured" -Code $readRetryConfig

$health = Invoke-WebRequest -UseBasicParsing "$BaseUrl/api/scheduler/health?limit=1" | Select-Object -ExpandProperty Content | ConvertFrom-Json
$retrySeconds = [string]($health.failure_retry_seconds)
$retryMaxAttempts = [string]($health.failure_retry_max_attempts)
if (-not $retrySeconds) { $retrySeconds = "unknown" }
if (-not $retryMaxAttempts) { $retryMaxAttempts = "unknown" }
$lines += "retry_seconds=$retrySeconds"
$lines += "retry_max_attempts=$retryMaxAttempts"

  Invoke-Pw -CliArgs @("screenshot")
  $lines += "result=pass"

  [System.IO.File]::WriteAllLines($reportPath, $lines, $utf8NoBom)
  Write-Output "Scheduler Phase 2.3 smoke report: $reportPath"
} finally {
  Pop-Location
}

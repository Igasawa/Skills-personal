param(
  [string]$BaseUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"

$session = "wf-smoke-" + (Get-Date -Format "yyyyMMddHHmmss")
$outputDir = Join-Path $PSScriptRoot "..\output\playwright"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$reportPath = Join-Path $outputDir ("workflow_smoke_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".txt")

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

$lines = @()
$lines += "session=$session"
$lines += "base_url=$BaseUrl"

Invoke-Pw -CliArgs @("open", "$BaseUrl/expense-workflow-copy")
$workflowName = "Smoke-WF-" + (Get-Date -Format "HHmmss")
Invoke-Pw -CliArgs @("run-code", "await page.locator('[name=template_name]').fill('$workflowName')")
Invoke-Pw -CliArgs @("run-code", "await page.locator('#workflow-page-create').click()")
Invoke-Pw -CliArgs @("run-code", "await page.locator('.modal .primary').click()")
Invoke-Pw -CliArgs @("run-code", "await page.waitForURL(/\\/workflow\\//, { timeout: 15000 })")
Invoke-Pw -CliArgs @("screenshot")

$title = (& npx --yes --package @playwright/cli playwright-cli -s=$session eval "document.title")
$url = (& npx --yes --package @playwright/cli playwright-cli -s=$session eval "location.href")
$lines += "title=$title"
$lines += "url=$url"

$lines | Set-Content -Encoding utf8 $reportPath
Write-Output "Smoke report: $reportPath"

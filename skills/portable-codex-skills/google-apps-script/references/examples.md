# Google Apps Script - Code Examples

Detailed, production-ready examples for common Google Apps Script automation tasks.

## Example 1: Automated Spreadsheet Report

```javascript
function generateWeeklyReport() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('Data');

  // Batch read for performance
  const data = sheet.getRange('A2:D').getValues();

  // Process data
  const report = data
    .filter(row => row[0])  // Filter empty rows
    .map(row => ({
      name: row[0],
      value: row[1],
      status: row[2],
      date: row[3]
    }));

  // Write summary
  const summarySheet = ss.getSheetByName('Summary') || ss.insertSheet('Summary');
  summarySheet.clear();
  summarySheet.appendRow(['Name', 'Total Value', 'Status']);

  report.forEach(item => {
    summarySheet.appendRow([item.name, item.value, item.status]);
  });

  // Email notification
  MailApp.sendEmail({
    to: Session.getEffectiveUser().getEmail(),
    subject: 'Weekly Report Generated',
    body: `Report generated with ${report.length} records.`
  });
}
```

## Example 2: Gmail Auto-Responder

```javascript
function processUnreadEmails() {
  const threads = GmailApp.search('is:unread from:specific@example.com');

  threads.forEach(thread => {
    const messages = thread.getMessages();
    const latestMessage = messages[messages.length - 1];

    const subject = latestMessage.getSubject();
    const body = latestMessage.getPlainBody();

    // Process and respond
    thread.reply(`Thank you for your email regarding: ${subject}\n\nWe will respond within 24 hours.`);

    // Mark as read and label
    thread.markRead();
    const label = GmailApp.getUserLabelByName('Auto-Responded');
    thread.addLabel(label);
  });
}
```

## Example 3: Document Generation from Template

```javascript
function generateDocumentFromTemplate() {
  // Get template
  const templateId = 'YOUR_TEMPLATE_ID';
  const template = DriveApp.getFileById(templateId);

  // Make copy
  const newDoc = template.makeCopy('Generated Document - ' + new Date());

  // Open and edit
  const doc = DocumentApp.openById(newDoc.getId());
  const body = doc.getBody();

  // Replace placeholders
  body.replaceText('{{NAME}}', 'John Doe');
  body.replaceText('{{DATE}}', new Date().toDateString());
  body.replaceText('{{AMOUNT}}', '$1,234.56');

  // Save
  doc.saveAndClose();

  // Share with user
  newDoc.addEditor('recipient@example.com');

  Logger.log('Document created: ' + newDoc.getUrl());
}
```

## Example 4: Time-Based Trigger Setup

```javascript
function setupDailyTrigger() {
  // Delete existing triggers to avoid duplicates
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === 'dailyReport') {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  // Create new trigger for 9 AM daily
  ScriptApp.newTrigger('dailyReport')
    .timeBased()
    .atHour(9)
    .everyDays(1)
    .create();

  Logger.log('Daily trigger configured');
}

function dailyReport() {
  // This function runs daily at 9 AM
  generateWeeklyReport();
}
```

## Example 5: Monthly GAS Import + Dashboard Webhook

```javascript
const PROVIDER_IMPORT_SETTINGS = {
  scriptProjectId: '1AjvXBW7pwKbNjWVS2QVKeYbp911Mph5xvD0OPeWHQzDh5CeWf2V-pBcs',
  baseUrlProp: 'AX_EXPENSE_DASHBOARD_BASE_URL',
  webhookTokenProp: 'AX_PROVIDER_IMPORT_WEBHOOK_TOKEN',
  providers: ['aquavoice', 'claude', 'chatgpt', 'gamma'],
};

function runMonthlyProviderImportWithWebhook() {
  const ym = getTargetYearMonthForProviderImport_();
  const props = PropertiesService.getScriptProperties();
  const baseUrl = String(props.getProperty(PROVIDER_IMPORT_SETTINGS.baseUrlProp) || '').trim();
  const token = String(props.getProperty(PROVIDER_IMPORT_SETTINGS.webhookTokenProp) || '').trim();

  if (!baseUrl) {
    throw new Error('Script property AX_EXPENSE_DASHBOARD_BASE_URL is required.');
  }

  const importResult = runGmailProviderImport_(ym);
  const payload = buildProviderImportPayload_(ym, importResult);
  return postProviderImportResult_(baseUrl, ym, payload, token);
}

function setupMonthlyProviderImportTrigger() {
  const fn = 'runMonthlyProviderImportWithWebhook';
  ScriptApp.getProjectTriggers().forEach((trigger) => {
    if (trigger.getHandlerFunction() === fn) {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  ScriptApp.newTrigger(fn)
    .timeBased()
    .everyMonths(1)
    .onMonthDay(5)
    .atHour(4)
    .nearMinute(0)
    .create();

  Logger.log('Monthly trigger configured: 5th day 04:00');
}

function runGmailProviderImport_(ym) {
  // TODO: replace with your existing Gmail import flow.
  // Return an object with fields like:
  // {foundFiles, foundPdfs, imported, importedMissingAmount,
  //  skippedDuplicates, failed, providerCounts, manualActionRequired, manualActionReason}
  return {
    foundFiles: 0,
    foundPdfs: 0,
    imported: 0,
    importedMissingAmount: 0,
    skippedDuplicates: 0,
    failed: 0,
    providerCounts: {
      aquavoice: {found: 0, imported: 0, imported_missing_amount: 0, skipped_duplicates: 0, failed: 0},
      claude: {found: 0, imported: 0, imported_missing_amount: 0, skipped_duplicates: 0, failed: 0},
      chatgpt: {found: 0, imported: 0, imported_missing_amount: 0, skipped_duplicates: 0, failed: 0},
      gamma: {found: 0, imported: 0, imported_missing_amount: 0, skipped_duplicates: 0, failed: 0},
    },
    manualActionRequired: false,
    manualActionReason: '',
  };
}

function buildProviderImportPayload_(ym, importResult) {
  const nowIso = new Date().toISOString();
  const manualActionRequired = Boolean(importResult.manualActionRequired) ||
    Number(importResult.failed || 0) > 0 ||
    Number(importResult.skippedDuplicates || 0) > 0;

  return {
    attempted: true,
    status: manualActionRequired ? 'warning' : 'ok',
    found_files: Number(importResult.foundFiles || 0),
    found_pdfs: Number(importResult.foundPdfs || importResult.foundFiles || 0),
    imported: Number(importResult.imported || 0),
    imported_missing_amount: Number(importResult.importedMissingAmount || 0),
    skipped_duplicates: Number(importResult.skippedDuplicates || 0),
    failed: Number(importResult.failed || 0),
    manual_action_required: manualActionRequired,
    manual_action_reason: manualActionRequired ? String(importResult.manualActionReason || (Number(importResult.failed || 0) > 0 ? 'failed' : 'skipped')) : '',
    provider_filter: PROVIDER_IMPORT_SETTINGS.providers,
    ingestion_channel: 'provider_inbox',
    provider_counts: buildProviderCounts_(importResult.providerCounts),
    updated_at: nowIso,
    source_import: {
      script_id: ScriptApp.getScriptId(),
      script_name: PROVIDER_IMPORT_SETTINGS.scriptProjectId,
      executed_at: nowIso,
      target_ym: ym,
    },
    report_json: `manual/reports/manual_import_last.json`,
    provider_report_json: `manual/reports/provider_import_last.json`,
  };
}

function buildProviderCounts_(providerCounts) {
  const result = {};
  const asNumber = (value) => {
    const num = Number(value);
    return Number.isFinite(num) && num > 0 ? Math.floor(num) : 0;
  };

  PROVIDER_IMPORT_SETTINGS.providers.forEach((name) => {
    const row = providerCounts && providerCounts[name] ? providerCounts[name] : {};
    result[name] = {
      found: asNumber(row.found),
      imported: asNumber(row.imported),
      imported_missing_amount: asNumber(row.imported_missing_amount),
      skipped_duplicates: asNumber(row.skipped_duplicates),
      failed: asNumber(row.failed),
    };
  });

  result.manual = {
    found: 0,
    imported: 0,
    imported_missing_amount: 0,
    skipped_duplicates: 0,
    failed: 0,
  };
  return result;
}

function postProviderImportResult_(baseUrl, ym, payload, token) {
  const endpoint = `${baseUrl.replace(/\/$/, '')}/api/provider-import/${encodeURIComponent(ym)}/result`;
  const headers = {'Content-Type': 'application/json'};
  if (token) {
    headers['x-provider-import-token'] = token;
  }

  const response = UrlFetchApp.fetch(endpoint, {
    method: 'post',
    headers,
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  const code = response.getResponseCode();
  const body = response.getContentText();
  if (code < 200 || code >= 300) {
    throw new Error(`Provider import webhook failed (${code}): ${body}`);
  }

  return JSON.parse(body);
}

function getTargetYearMonthForProviderImport_() {
  const now = new Date();
  const target = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return Utilities.formatDate(target, Session.getScriptTimeZone(), 'yyyy-MM');
}

function testProviderImportWebhookPayloadOnly_() {
  const ym = getTargetYearMonthForProviderImport_();
  const payload = buildProviderImportPayload_(ym, runGmailProviderImport_(ym));
  Logger.log(JSON.stringify(payload));
}
```

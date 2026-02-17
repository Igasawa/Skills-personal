---
name: moneyforward
description: "Guidance for MoneyForward expense workflows: invoice/accounting operations, file input flows, and practical reconciliation support."
category: finance, accounting, expense
dependencies:
  - MoneyForward web portal access
  - Expense data source (CSV/API/manual upload path)
  - OCR output file handling
updated: 2026-02-16
---

# MoneyForward

## What this skill is for

Use this skill when working with MoneyForward expense operations:

- Receipt capture and invoice processing flow
- Expense record import (including CSV/manual upload)
- Account/category assignment and reconciliation support
- Report preparation with traceability
- Operational runbooks for regular finance tasks

## Core workflow

1. Prepare source data and expected mapping (vendor, amount, date, tax, category).
2. Confirm authentication/session state and permissions.
3. Apply import method:
   - web upload path
   - API/path-based import (if available in environment)
   - OCR-assisted data intake
4. Validate imported records against source totals.
5. Apply manual correction rules.
6. Export or archive results with run log and evidence.

## Configuration and operation notes

- Keep tenant/account scope explicit per environment.
- Maintain template mapping for:
  - header normalization
  - default account/category rules
  - duplicate detection keys
- Use non-destructive sync in first pass; do write-only on confirmed records.

## Error handling

- Keep invalid rows in a rejection bucket with reason code.
- Retry transient failures only (network, temporary UI/API instability).
- For auth/session issues, re-auth and re-run from checkpoint.
- Validate amount/date tax parsing before import commit.
- Keep idempotent behavior where possible (run-key + source row hash).

## Verification checklist

1. Confirm all required columns exist (or are safely defaulted).
2. Verify totals by currency and period after import.
3. Confirm duplicate/overlap detection works for reruns.
4. Spot-check at least one representative sample per batch.
5. Confirm evidence logs include source file, timestamp, and operator.

## Troubleshooting

- **Upload blocked / permission error**: verify role permissions and tenant access.
- **OCR mismatch**: compare image/text extraction against original receipt and adjust template rules.
- **Tax misclassification**: inspect tax/category mapping table before reconciliation.
- **Missing imports**: check encoding (CSV/UTF-8), date format, and delimiter.

## Operational logging

- Log at least:
  - source file name
  - job start/end
  - processed/failed counts
  - unresolved exception rows
  - operator notes

## Security and audit

- Do not log user credentials.
- Store session artifacts in controlled directories.
- Keep retention policy for exports and logs consistent with finance policy.

## References

- `references/official_sources.md` for latest MoneyForward official manuals and account/feature pages.

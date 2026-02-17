# Incident Plan: incident_20260217_061752_run_20260208_094248_545973

## Summary
- Failure class: run_failed
- Step: amazon_download
- Error signature: run_failed | amazon_download | Run failed: mode=amazon_download reason=process_ended_without_final_status returncode=-1
- Message: Run failed: mode=amazon_download reason=process_ended_without_final_status returncode=-1

## Root Cause Hypotheses
- H1: Run failed without clear class-specific signal; inspect logs and replay mode. (confidence: low)

## Action Plan
- A1 [P0] Confirm reproduction path and isolate failure boundary
  - target paths:
    - skills/mfcloud-expense-receipt-reconcile/scripts/amazon_download.mjs
    - skills/mfcloud-expense-receipt-reconcile/scripts/run_core_pipeline.py
  - verification:
    - `python -m pytest -q tests/test_run_core_pipeline.py`
- A2 [P0] Apply minimal fix in the most likely target files
  - target paths:
    - skills/mfcloud-expense-receipt-reconcile/scripts/amazon_download.mjs
    - skills/mfcloud-expense-receipt-reconcile/scripts/run_core_pipeline.py
  - verification:
    - `python -m pytest -q tests/test_run_core_pipeline.py`
- A3 [P1] Run verification suite and confirm non-regression
  - verification:
    - `python -m pytest -q tests/test_run_core_pipeline.py`
    - `python scripts/run.py --year 2026 --month 1 --dry-run --skip-rakuten --skip-mfcloud`

## Verification Commands
- `python -m pytest -q tests/test_run_core_pipeline.py`
- `python scripts/run.py --year 2026 --month 1 --dry-run --skip-rakuten --skip-mfcloud`

## Done Criteria
- Target error no longer reproduces in the same mode.
- Verification commands pass with no regression on critical path.

## Rollback
- Revert the modified files and re-run baseline verification.

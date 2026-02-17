# Incident Plan: incident_ui_smoke_20260217_114759

## Summary
- Failure class: smoke_test
- Step: ui_smoke
- Error signature: smoke_test | ui_smoke | UI smoke test for /errors page
- Message: UI smoke test for /errors page

## Root Cause Hypotheses
- H1: Insufficient evidence for direct cause; start with reproducible dry-run. (confidence: low)

## Action Plan
- A1 [P0] Confirm reproduction path and isolate failure boundary
  - verification:
    - `python -m pytest -q tests/test_run_smoke.py`
- A2 [P0] Apply minimal fix in the most likely target files
  - verification:
    - `python -m pytest -q tests/test_run_smoke.py`
- A3 [P1] Run verification suite and confirm non-regression
  - verification:
    - `python -m pytest -q tests/test_run_smoke.py`
    - `python scripts/run.py --year 2026 --month 13 --dry-run --skip-rakuten --skip-mfcloud`

## Verification Commands
- `python -m pytest -q tests/test_run_smoke.py`
- `python scripts/run.py --year 2026 --month 13 --dry-run --skip-rakuten --skip-mfcloud`

## Done Criteria
- Target error no longer reproduces in the same mode.
- Verification commands pass with no regression on critical path.

## Rollback
- Revert the modified files and re-run baseline verification.

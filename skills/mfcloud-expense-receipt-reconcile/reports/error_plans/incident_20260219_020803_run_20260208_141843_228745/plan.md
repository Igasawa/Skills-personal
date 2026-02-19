# Incident Plan: incident_20260219_020803_run_20260208_141843_228745

## Summary
- Failure class: run_failed
- Step: rakuten_download
- Error signature: run_failed | rakuten_download | Run failed: mode=rakuten_download reason=worker_exit returncode=1
- Message: Run failed: mode=rakuten_download reason=worker_exit returncode=1
- Planner: ai
- Confidence: 0.7
- Risk: Scraper failures often stem from UI changes or auth issues; repeated failed attempts may trigger account blocks.

## Card Summary
- Plan: Diagnose the rakuten_download worker crash by inspecting logs and verifying site selectors, followed by a logic fix.
- First Step: Inspect stderr logs for rakuten_download.mjs to identify the specific JS exception.
- ETA (minutes): 45
- Risk: low
- Approval: required

## Root Cause Hypotheses
- H1: Rakuten login or download page DOM structure changed, causing selector timeout. (confidence: 0.5)
- H2: Authentication failure or session expiration not handled gracefully by the script. (confidence: 0.3)
- H3: Worker environment missing required Node.js dependencies or browser binaries. (confidence: 0.2)

## Action Plan
- A1 [P0] Inspect worker logs and stderr
  - target paths:
    - skills/mfcloud-expense-receipt-reconcile/scripts/rakuten_download.mjs
  - verification:
    - `python -m pytest -q tests/test_run_core_pipeline.py`
- A2 [P1] Validate Rakuten selectors and login flow
  - target paths:
    - skills/mfcloud-expense-receipt-reconcile/scripts/rakuten_download.mjs
  - verification:
    - `python -m pytest -q tests/test_run_core_pipeline.py`
- A3 [P1] Apply fix for identified scraper logic or selector
  - target paths:
    - skills/mfcloud-expense-receipt-reconcile/scripts/rakuten_download.mjs
  - verification:
    - `python -m pytest -q tests/test_run_core_pipeline.py`

## Verification Commands
- `python -m pytest -q tests/test_run_core_pipeline.py`
- `python scripts/run.py --year 2026 --month 1 --dry-run --skip-mfcloud`

## Done Criteria
- rakuten_download.mjs completes without worker_exit
- Verification suite passes
- Dry-run confirms successful navigation to download targets

## Rollback
- git checkout skills/mfcloud-expense-receipt-reconcile/scripts/rakuten_download.mjs

## Antigravity Handoff
- Executor: Scraper Engineer
- Requires approval: False
- Intent: Identify why the Node.js worker exited and restore Rakuten statement downloading.

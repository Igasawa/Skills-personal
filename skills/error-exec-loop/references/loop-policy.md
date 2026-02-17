# Error Exec Loop Policy

## Canonical Contract

Use shared contract:

- `../mfcloud-expense-receipt-reconcile/references/error_automation_contract.md`

## Exit Conditions

Resolve when all are true:

- incident-specific error no longer reproduces
- verification commands in `plan.json` pass
- incident archived to `error_archive/resolved/<incident_id>/`

Escalate when any is true:

- loops used > 8
- runtime > 45 minutes
- same error signature repeated 3 times
- blocked by missing credentials or unavailable dependencies
- no actionable progress for two consecutive loops

## Iteration Record

Write one file per loop:

- `error_runs/<incident_id>/attempt_01.json`
- `error_runs/<incident_id>/attempt_02.json`

Recommended fields:

```json
{
  "incident_id": "incident_20260217_120000_run_abc",
  "iteration": 1,
  "started_at": "2026-02-17T03:20:00+00:00",
  "finished_at": "2026-02-17T03:25:00+00:00",
  "actions_applied": ["A1"],
  "verification_commands": ["python -m pytest -q tests/test_run_core_pipeline.py"],
  "verification_passed": false,
  "result": "continue",
  "error_signature": "selector_not_found"
}
```

## Final Result File

Write once per run:

- `error_runs/<incident_id>/run_result.json`

Required fields:

```json
{
  "incident_id": "incident_20260217_120000_run_abc",
  "final_status": "resolved",
  "loops_used": 3,
  "runtime_minutes": 18,
  "same_error_repeats": 1,
  "archived_to": "error_archive/resolved/incident_20260217_120000_run_abc"
}
```


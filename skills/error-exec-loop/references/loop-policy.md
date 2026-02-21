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

### Replan policy for consecutive no-progress

- `error_exec_loop.py` tracks `no_progress_streak` as count of consecutive iterations where the same `error_signature` repeats.
- When `auto_replan_on_no_progress` is true, the loop must stop at `no_progress_limit` with `final_status = replan_requested` after:
  - the same non-empty `error_signature` repeats for `no_progress_limit` consecutive iterations (default `2`)
  - `incident` status is updated from `running` to `plan_proposed`
  - the current plan is regenerated via `error_plan_generate.py --incident-id <id> --force`
- This `replan_requested` condition has priority over `same_error_limit` escalation and should terminate the loop before escalation.

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

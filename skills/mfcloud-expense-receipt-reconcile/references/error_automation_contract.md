# Error Automation Contract

This file defines the fixed folder layout and JSON contracts used by:

- `scripts/error_capture.py`
- `scripts/error_status.py`
- `scripts/error_archive.py`
- skill `error-plan`
- skill `error-exec-loop`

## Fixed Folder Layout

All paths are relative to:

`skills/mfcloud-expense-receipt-reconcile/reports/`

- `error_inbox/` : unresolved incidents
- `error_archive/resolved/` : completed incidents
- `error_archive/escalated/` : incidents that require manual intervention
- `error_plans/` : generated remediation plans
- `error_runs/` : execution-loop artifacts

## State Model

`new -> planned -> running -> resolved | escalated`

Rule:

- unresolved = folder exists in `error_inbox/`
- resolved/escalated = folder moved into archive bucket

## Incident Bundle (required files)

Each incident uses:

`error_inbox/<incident_id>/`

- `incident.json`
- `status.txt`
- `log_tail.txt`
- `audit_tail.jsonl`
- `context.json`

### `incident.json` required fields

```json
{
  "incident_id": "incident_20260217_120000_run_abc",
  "status": "new",
  "created_at": "2026-02-17T03:00:00+00:00",
  "updated_at": "2026-02-17T03:00:00+00:00",
  "run_id": "run_20260217_115959_123456",
  "year": 2026,
  "month": 1,
  "ym": "2026-01",
  "step": "amazon_download",
  "failure_class": "transient",
  "message": "Network timeout during receipt download",
  "error_signature": "transient | amazon_download | Network timeout during receipt download"
}
```

### `status.txt` values

- `new`
- `planned`
- `running`
- `resolved`
- `escalated`

## Plan Output Contract

Plan outputs are written to:

`error_plans/<incident_id>/`

- `plan.md`
- `plan.json`

### `plan.json` required structure

```json
{
  "incident_id": "incident_20260217_120000_run_abc",
  "generated_at": "2026-02-17T03:15:00+00:00",
  "summary": "Short problem summary",
  "root_cause_hypotheses": [
    {
      "id": "H1",
      "confidence": "medium",
      "reason": "Selector changed in provider page"
    }
  ],
  "actions": [
    {
      "id": "A1",
      "title": "Adjust selector",
      "priority": "P0",
      "risk": "low",
      "target_paths": ["skills/mfcloud-expense-receipt-reconcile/scripts/provider_download_chatgpt.mjs"],
      "verification": [
        "python -m pytest -q tests/test_provider_download_orchestrator.py"
      ]
    }
  ],
  "verification_commands": [
    "python -m pytest -q tests/test_run_core_pipeline.py"
  ],
  "done_criteria": [
    "Target error no longer reproduces",
    "Listed verification commands pass"
  ]
}
```

## Execution Loop Artifacts

Loop outputs are written to:

`error_runs/<incident_id>/`

- `attempt_01.json`, `attempt_02.json`, ...
- `run_result.json`
- optional notes/logs

### `attempt_XX.json` recommended fields

```json
{
  "incident_id": "incident_20260217_120000_run_abc",
  "iteration": 1,
  "started_at": "2026-02-17T03:20:00+00:00",
  "finished_at": "2026-02-17T03:25:00+00:00",
  "actions_applied": ["A1"],
  "verification_commands": ["python -m pytest -q tests/test_provider_download_orchestrator.py"],
  "verification_passed": false,
  "result": "continue",
  "error_signature": "selector_not_found"
}
```

### `run_result.json` required fields

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

## Archive Rule

On closure, move the entire incident folder:

- `error_inbox/<incident_id>/` -> `error_archive/resolved/<incident_id>/`
- `error_inbox/<incident_id>/` -> `error_archive/escalated/<incident_id>/`

Do not keep duplicate unresolved copies in `error_inbox/`.

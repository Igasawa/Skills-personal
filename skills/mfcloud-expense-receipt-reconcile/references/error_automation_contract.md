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
- `error_handoffs/` : prepared handoff packages for Antigravity execution
- `error_runs/` : execution-loop artifacts

## State Model

`new -> plan_proposed -> approved -> handed_off -> running -> resolved | escalated`

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
- `plan_proposed`
- `approved`
- `handed_off`
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
  "evidence": [
    {
      "id": "E1",
      "source": "log_tail",
      "path": "log_tail.txt",
      "kind": "log_signal",
      "excerpt": "AUTH_REQUIRED: provider login page detected"
    }
  ],
  "evidence_quality": {
    "total_count": 4,
    "signal_count": 2,
    "strong_signal_count": 1,
    "weak_signal_count": 2,
    "has_failure_signal": true,
    "score": 0.63,
    "assessment": "medium",
    "strongest_evidence_ids": ["E1"]
  },
  "root_cause_hypotheses": [
    {
      "id": "H1",
      "confidence": "medium",
      "reason": "Selector changed in provider page",
      "evidence_ids": ["E1"]
    }
  ],
  "hypothesis_evidence_map": [
    {
      "hypothesis_id": "H1",
      "evidence_ids": ["E1"]
    }
  ],
  "cause_analysis": [
    {
      "hypothesis_id": "H1",
      "reason": "Selector changed in provider page",
      "confidence": "medium",
      "support_strength": "medium",
      "evidence_ids": ["E1"],
      "supporting_evidence": [
        {
          "id": "E1",
          "path": "log_tail.txt",
          "kind": "log_signal",
          "excerpt": "AUTH_REQUIRED: provider login page detected"
        }
      ],
      "gaps": ["Need full stderr to confirm exact selector failure point"]
    }
  ],
  "unknowns": [
    "Need full stderr to confirm exact selector failure point"
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
  "error_signature": "selector_not_found",
  "same_error_repeats": 1,
  "no_progress_streak": 2
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
  "no_progress_streak": 0,
  "archived_to": "error_archive/resolved/incident_20260217_120000_run_abc"
}
```

### `run_result.json` extended fields

```json
{
  "incident_id": "incident_20260217_120000_run_abc",
  "final_status": "replan_requested",
  "loops_used": 2,
  "runtime_minutes": 1,
  "same_error_repeats": 1,
  "no_progress_streak": 2,
  "replan": {
    "requested": true,
    "reason": "no actionable progress for 2 consecutive loops",
    "iteration": 2,
    "plan_json": {
      "status": "ok",
      "plan_json": "error_plans/incident_20260217_120000_run_abc/plan.json",
      "force": true,
      "returncode": 0
    }
  },
  "commit": {
    "requested": true,
    "enabled": false,
    "ran": false,
    "skipped": false,
    "remote": "origin",
    "branch": "main",
    "scope": "incident",
    "commit_sha": null,
    "commit_message": null,
    "push": {
      "requested": true,
      "ran": false,
      "success": false,
      "error": null
    },
    "error": null
  }
}
```

`final_status` may be:
- `resolved`
- `escalated`
- `replan_requested`

## Archive Rule

On closure, move the entire incident folder:

- `error_inbox/<incident_id>/` -> `error_archive/resolved/<incident_id>/`
- `error_inbox/<incident_id>/` -> `error_archive/escalated/<incident_id>/`

Do not keep duplicate unresolved copies in `error_inbox/`.

## Antigravity Handoff

Handoff artifacts are written to:

- `error_handoffs/<incident_id>/handoff.json`
- `error_handoffs/<incident_id>/handoff.md`

Optional external queue export:

- Set `AX_ANTIGRAVITY_HANDOFF_DIR` or pass `--queue-dir` to `error_handoff_prepare.py`.
- Queue payload file name: `<incident_id>.json`

### Recommended API lifecycle

1. `POST /api/errors/incidents/{incident_id}/plan`
2. `POST /api/errors/incidents/{incident_id}/approve`
3. `POST /api/errors/incidents/{incident_id}/handoff`

Status transition:

- `new -> plan_proposed -> approved -> handed_off`

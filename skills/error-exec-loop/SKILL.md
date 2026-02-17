---
name: error-exec-loop
description: Execute approved remediation plans for incidents in `skills/mfcloud-expense-receipt-reconcile/reports/error_inbox` after an explicit `GO incident_id` command. Use when the user requests autonomous implementation loops that continue until the incident is resolved or escalated, with bounded retries and runtime.
---

# Error Exec Loop

Run bounded fix loops and close incidents by moving them out of inbox.

## Preconditions

- Require explicit user approval:
  - `GO <incident_id>`
- Require existing plan:
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_plans/<incident_id>/plan.json`
- Require incident folder in:
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_inbox/<incident_id>/`

## Loop Policy

- `max_loops = 8`
- `max_runtime_minutes = 45`
- `same_error_limit = 3`
- code-change scope:
  - `skills/mfcloud-expense-receipt-reconcile/**`

If any limit is hit, close as `escalated`.

## Execution Workflow

1. Mark incident running.
- Set `status.txt` to `running`.
- Update `incident.json.status` and `incident.json.updated_at`.

2. Execute loop iteration.
- Pick highest-priority remaining action from `plan.json`.
- Apply minimal code or config changes.
- Run listed verification commands.
- Persist iteration output to:
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_runs/<incident_id>/attempt_XX.json`

3. Evaluate iteration result.
- If verification passes and target error does not reproduce, finish `resolved`.
- If failure repeats with same signature, increment repeat counter.
- If repeat counter reaches `same_error_limit`, finish `escalated`.

4. Close incident.
- On success:
```powershell
python skills/mfcloud-expense-receipt-reconcile/scripts/error_archive.py --incident-id <incident_id> --result resolved --reason "loop completed"
```
- On escalation:
```powershell
python skills/mfcloud-expense-receipt-reconcile/scripts/error_archive.py --incident-id <incident_id> --result escalated --reason "needs manual intervention"
```

5. Write final loop summary.
- `skills/mfcloud-expense-receipt-reconcile/reports/error_runs/<incident_id>/run_result.json`

## Guardrails

- Never use destructive git commands.
- Never run month-close completion actions inside autonomous loop.
- If blocked by auth/session/credentials, escalate quickly with clear manual steps.

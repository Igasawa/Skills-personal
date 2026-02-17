---
name: error-plan
description: Analyze unresolved error incidents from `skills/mfcloud-expense-receipt-reconcile/reports/error_inbox` and create a detailed remediation plan in `reports/error_plans/incident_id/`. Use when the user asks to check failures, inspect logs, identify root cause hypotheses, or produce a structured fix plan before execution. This skill is planning-only and should not implement code changes.
---

# Error Plan

Generate remediation plans from incident bundles and prepare a clean handoff for execution.

## Workflow

1. Select incident.
- Prefer an incident id from the user.
- If no id is provided, choose the newest unresolved incident from:
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_inbox`
- Inspect queue with:
```powershell
python skills/mfcloud-expense-receipt-reconcile/scripts/error_status.py --json
```

2. Load evidence files in this order.
- `incident.json`
- `status.txt`
- `log_tail.txt`
- `audit_tail.jsonl`
- `context.json`
- If a file is missing, keep going and mark it as an assumption gap.

3. Build plan outputs.
- Write:
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_plans/<incident_id>/plan.md`
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_plans/<incident_id>/plan.json`
- Follow schema and examples in `references/workflow.md`.
- Include:
  - root cause hypotheses tied to evidence
  - prioritized actions (`P0`, `P1`, `P2`)
  - exact verification commands
  - rollback note
  - done criteria

4. Update incident state to planned.
- Update `skills/mfcloud-expense-receipt-reconcile/reports/error_inbox/<incident_id>/status.txt` to `planned`.
- Update `incident.json` with:
  - `status: "planned"`
  - `plan_path`
  - `planned_at`
  - `updated_at`

5. Return a concise decision package.
- Summarize top three actions.
- Highlight first execution command.
- Request explicit execution approval:
  - `GO <incident_id>`

## Guardrails

- Keep this skill planning-only. Do not implement code changes.
- Do not archive incidents in this skill.
- Keep planned code scope inside:
  - `skills/mfcloud-expense-receipt-reconcile/**`

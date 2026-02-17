# Error Plan Workflow Notes

## Canonical Contract

Use the shared contract as source of truth:

- `../mfcloud-expense-receipt-reconcile/references/error_automation_contract.md`

## `plan.md` template

Use this structure:

```markdown
# Incident Plan: <incident_id>

## Summary
- Failure class:
- Step:
- Error signature:

## Evidence
- log_tail highlights:
- audit_tail highlights:
- context highlights:

## Root Cause Hypotheses
1. H1 (confidence: high|medium|low)
   - reason:
   - evidence:

## Action Plan
1. A1 (P0)
   - target paths:
   - change:
   - risk:
   - verification:

## Rollback
- rollback strategy:

## Done Criteria
- criterion 1
- criterion 2
```

## `plan.json` minimum fields

```json
{
  "incident_id": "incident_20260217_120000_run_abc",
  "generated_at": "2026-02-17T03:15:00+00:00",
  "summary": "Short summary",
  "root_cause_hypotheses": [],
  "actions": [],
  "done_criteria": []
}
```

## Evidence Scoring Heuristic

- Prefer signals from `incident.json` and reproducible log patterns.
- Treat one-off stack traces as weak evidence until reproduced.
- Promote hypotheses with direct file/path linkage to `high`.
- Keep uncertain hypotheses but mark confidence `low`.


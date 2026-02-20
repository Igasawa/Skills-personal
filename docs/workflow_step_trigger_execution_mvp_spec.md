# Workflow Step Trigger/Execution MVP Spec

- Updated: 2026-02-20
- Scope: `/expense-workflow-copy` workflow step editor
- Goal: Separate "when it starts" and "how it runs" clearly in UI/API/data

## 1. Core Concepts

Each step has two independent axes:

1. `trigger_kind` (when a step starts)
2. `execution_mode` (how a step proceeds after triggered)

### 1.1 trigger_kind

- `manual_start`: manually start from UI
- `scheduled`: start by scheduler
- `external_event`: start by webhook/external event
- `after_previous`: start after previous step completion

### 1.2 execution_mode

- `auto`: proceed automatically (no confirmation gate)
- `manual_confirm`: require human confirmation before proceed

## 2. Step Type

- `manual` (human)
- `agent` (AI)
- `browser` (AI browser)

## 3. MVP Validation Rules

### 3.1 Position rules

- Step #1 can use:
  - `manual_start`
  - `scheduled`
  - `external_event`
- Step #2+ can use only:
  - `after_previous`

### 3.2 Type rules

- `manual` step:
  - `execution_mode` must be `manual_confirm`
- `agent` / `browser` step:
  - `execution_mode` can be `auto` or `manual_confirm`

### 3.3 Field requirements

- `browser` step:
  - `target_url` is required
  - must be valid `http` or `https`
- `agent` step:
  - `agent_prompt` is required
- `execution_mode=auto`:
  - `timer_minutes` required (`1..10080`)
- `execution_mode=manual_confirm`:
  - `timer_minutes` optional

## 4. Persistence Schema (MVP Canonical)

```json
{
  "id": "step_xxx",
  "order": 1,
  "title": "string",
  "action": "preflight",
  "step_type": "manual",
  "trigger_kind": "manual_start",
  "execution_mode": "manual_confirm",
  "target_url": "",
  "agent_prompt": "",
  "timer_minutes": null,
  "configs": {
    "schedule": {},
    "event": {},
    "dependency": {}
  },
  "execution_log": []
}
```

## 5. Backward Compatibility Mapping

On read/normalize, map old fields into new fields:

- `trigger=manual` -> `trigger_kind=manual_start`
- `trigger=schedule` -> `trigger_kind=scheduled`
- `trigger=webhook` -> `trigger_kind=external_event`
- `trigger=after_step` -> `trigger_kind=after_previous`
- `auto_run=true` -> `execution_mode=auto`
- `auto_run=false` -> `execution_mode=manual_confirm`

For compatibility, old fields may still be written during transition, but new fields are source of truth.

## 6. Current MVP Behavior Notes

- In this phase, scheduler/webhook/orchestration execution wiring is out of scope.
- This MVP implements:
  - UI separation and constraints
  - API normalization and validation
  - safe persistence with backward compatibility

## 7. Future Wiring (Out of Scope for This MVP)

- `trigger_kind=scheduled` -> `core_scheduler` integration
- `trigger_kind=external_event` -> webhook receiver integration
- `trigger_kind=after_previous` -> step orchestration integration


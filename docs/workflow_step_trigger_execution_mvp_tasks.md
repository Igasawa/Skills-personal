# Workflow Step Trigger/Execution MVP Tasks

- Updated: 2026-02-20
- Spec: `docs/workflow_step_trigger_execution_mvp_spec.md`

## Phase A: API/Data (Normalization + Validation)

1. Add canonical enums for:
   - `trigger_kind`: `manual_start|scheduled|external_event|after_previous`
   - `execution_mode`: `auto|manual_confirm`
2. Add backward-compatible mapping from:
   - `trigger` -> `trigger_kind`
   - `auto_run` -> `execution_mode`
3. Persist canonical fields in `steps`.
4. Add validation:
   - first step trigger restriction
   - step #2+ trigger restriction
   - type/execution_mode compatibility
   - browser URL required
   - agent prompt required
   - auto timer required range

## Phase B: Frontend UX

1. Replace trigger selector labels with new `trigger_kind` labels.
2. Add separate `execution_mode` selector.
3. Dynamically restrict trigger options by step position.
4. Dynamically restrict execution_mode by step type.
5. Keep timer input behavior aligned with `execution_mode`.
6. Update preview lines to show:
   - trigger label
   - execution mode label

## Phase C: Tests

1. API tests:
   - mapping old fields to canonical
   - reject invalid trigger by position
   - reject invalid execution/type combination
   - reject missing URL/prompt for required types
   - reject invalid timer for auto mode
2. Page/UI tests:
   - ensure new fields are rendered/handled
   - ensure old scheduler panel assumptions remain unchanged

## Phase D: Follow-up (Future)

1. Scheduler wiring for `scheduled`.
2. Webhook wiring for `external_event`.
3. Orchestrator wiring for `after_previous`.


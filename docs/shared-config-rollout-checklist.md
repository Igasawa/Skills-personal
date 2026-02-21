# Shared Config Rollout Checklist

Updated: 2026-02-20  
Target priority: high-frequency skills first

## Rollout Rules

- Resolution order must be `CLI > skill config > org-profile > defaults`.
- Existing skill config must remain backward compatible during rollout.
- Add tests for both:
  - `org-profile` fallback when skill config is missing
  - skill config override precedence over `org-profile`

## Skill Checklist

| Skill | Priority | Owner | Status | Scope | Tests | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `mfcloud-expense-receipt-reconcile` | P0 | management automation | Done | `run_core.py`, `collect_print.py`, pipeline metadata | `test_run_core_config.py`, `test_collect_print.py`, related pipeline/smoke tests | Pilot completed, deprecation warnings active |
| `dashboard-ja-localization` | P1 | dashboard team | Planned | shared organization metadata consumption review | TBD | No direct org-profile dependency confirmed yet |
| other skills under `skills/` | P2 | each skill owner | Planned | compatibility assessment only | TBD | Apply only when shared values are actually reused |

## Verification Checklist (Per Skill)

- [ ] `org-profile` is loaded from `AX_HOME/configs/org-profile.json`.
- [ ] Priority is implemented exactly as documented.
- [ ] Legacy keys still work during deprecation period.
- [ ] Unit tests cover fallback and override behavior.
- [ ] Encoding check passes for changed files.
- [ ] CI checks pass.

## Current Wave Summary

- Wave 1 complete:
  - `mfcloud-expense-receipt-reconcile` migrated as pilot
  - `run_core.py` shared-config resolution implemented
  - `collect_print.py` shared-config resolution implemented
  - run metadata now includes `org_profile` details

- Wave 2 candidate:
  - evaluate P1 skill applicability
  - implement only if shared organization fields are needed

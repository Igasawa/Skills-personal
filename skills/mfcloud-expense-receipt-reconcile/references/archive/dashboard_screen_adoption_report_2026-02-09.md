# Dashboard Screen Adoption Report

Run date: `2026-02-09`
Checklist: `references/dashboard_screen_adoption_checklist.md`
Guideline baseline: `references/dashboard_token_mapping_guideline.md`
Method: static code audit (CSS/HTML/JS). Visual browser QA was not executed in this run.

## 1. Executive Result

- Overall result: `FAIL` (not yet Design Pack aligned for current scope).
- Reason: semantic token contract, focus visibility, reduced motion, dark/light parity, and z-index baseline are not satisfied.

## 2. Checklist Outcome

| ID | Status | Note |
| --- | --- | --- |
| C-01 | FAIL | Current styles use local palette variables and hardcoded colors, not Design Pack semantic aliases. |
| C-02 | FAIL | No `rgb(var(--...))` / `hsl(var(--...))` contract usage found for Design Pack tokens. |
| C-03 | PASS | No token rename/remove migration activity was detected in this run. |
| C-04 | FAIL | No explicit focus/focus-visible style rules found for shared controls. |
| C-05 | FAIL | No reduced-motion media handling found. |
| C-06 | FAIL | No dark theme implementation pattern found. |
| C-07 | FAIL | Only `z-index: 50` toast layer is defined; does not match guideline baseline. |
| C-08 | FAIL | Home card surfaces use local vars; mapping to baseline semantic tokens not implemented. |
| C-09 | FAIL | Input/select borders and background are hardcoded values. |
| C-10 | FAIL | Button states use local/hardcoded values and no semantic contract. |
| C-11 | FAIL | Run detail stat tiles use local variables/hardcoded values. |
| C-12 | FAIL | Table divider/hover mapping not aligned with semantic interaction aliases. |
| C-13 | FAIL | Feedback colors are hardcoded and not tied to semantic feedback aliases. |
| C-14 | FAIL | Excluded page filter controls are hardcoded style values. |
| C-15 | FAIL | Excluded page actions are not mapped to semantic token contract. |
| C-16 | FAIL | Archive page filter controls follow same non-semantic styling pattern. |
| C-17 | FAIL | Contrast and semantic mapping cannot be confirmed against Design Pack contract. |
| C-18 | N/A | Chart UI not present in current dashboard templates. |
| C-19 | N/A | Modal/overlay UI not present in current dashboard templates. |

## 3. Evidence

- Local palette variables and hardcoded colors:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:4`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:11`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:25`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:71`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/pages.css:11`
- Missing focus rules:
- no `focus` or `focus-visible` match found in `dashboard/static/styles/*.css` (rg result empty)
- Motion without reduced-motion handling:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/layout.css:5`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:204`
- z-index mismatch:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:205`
- Screen structure includes cards/tables/filters but no chart/modal:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/templates/index.html:25`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/templates/run.html:179`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/templates/excluded_pdfs.html:31`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/templates/archive_receipts.html:31`

## 4. Required Remediation (Priority Order)

1. Replace local palette and hardcoded colors with Design Pack token variables and semantic aliases.
2. Add explicit focus styles for button/input/select using semantic interaction focus token.
3. Add reduced-motion behavior via media query and duration-reduced mapping.
4. Implement theme strategy (light/dark) and verify contrast in both modes.
5. Align layer values to dashboard z-index baseline contract.

## 5. Recheck Gate

- Next run should be recorded as `dashboard_screen_adoption_report_2026-02-XX.md`.
- Exit condition: all applicable checks (`C-01` to `C-17`) are `PASS`.

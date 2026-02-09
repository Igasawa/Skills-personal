# Dashboard Screen Adoption Report (Run #3: Visual QA)

Run date: `2026-02-09`
Checklist: `references/dashboard_screen_adoption_checklist.md`
Guideline baseline: `references/dashboard_token_mapping_guideline.md`
Method:
- Static audit (token/focus/motion/z-index contract)
- Browser visual QA (light/dark screenshots via Playwright CLI)
- Contrast ratio check for key text/surface pairs

## 1. Executive Result

- Overall result: `FAIL` (remaining contrast issue)
- Result summary:
- `C-06` is closed as `PASS` (light/dark parity visually confirmed).
- `C-17` is now evaluated and is `FAIL` under AA normal-text threshold (`4.5:1`) for specific action/feedback pairs.

## 2. Visual Evidence Artifacts

Captured files (`output/playwright/design-qa/`):
- `home-light.png`
- `home-dark.png`
- `run-light.png`
- `run-dark.png`
- `excluded-light.png`
- `excluded-dark.png`
- `archive-light.png`
- `archive-dark.png`

## 3. Checklist Outcome (Run #3)

| ID | Status | Note |
| --- | --- | --- |
| C-01 | PASS | Semantic aliases are applied to shared controls. |
| C-02 | PASS | RGB/HSL token format contract is implemented. |
| C-03 | PASS | Migration remains additive. |
| C-04 | PASS | Focus visibility rules are present and visible in screenshots. |
| C-05 | PASS | Reduced-motion media rule is present. |
| C-06 | PASS | Light/dark rendering is consistent across home/run/excluded/archive. |
| C-07 | PASS | z-index token contract is defined and mapped. |
| C-08 | PASS | Home cards map to semantic surface/border/text styling. |
| C-09 | PASS | Field controls use semantic field tokens. |
| C-10 | PASS | Action buttons follow semantic button tokens. |
| C-11 | PASS | Run detail KPI/status areas follow semantic mapping. |
| C-12 | PASS | Table structure and interaction styles follow token mapping. |
| C-13 | PASS | Feedback visuals are mapped via semantic feedback aliases. |
| C-14 | PASS | Excluded filter controls follow semantic styling. |
| C-15 | PASS | Excluded table/actions follow semantic styling. |
| C-16 | PASS | Archive filter/table follows same baseline mapping. |
| C-17 | FAIL | Contrast check failed for specific normal-text action/feedback pairs. |
| C-18 | N/A | Chart UI is not rendered in current dashboard scope. |
| C-19 | N/A | Modal UI is not rendered in current dashboard scope. |

## 4. Contrast Check (AA Normal Threshold 4.5:1)

| Mode | Pair | Ratio | Result |
| --- | --- | --- | --- |
| light | text_default on surface_1 | 17.89 | PASS |
| light | text_secondary on surface_1 | 7.53 | PASS |
| light | text_default on surface_2 | 15.95 | PASS |
| light | button_primary_text on button_primary_bg | 4.72 | PASS |
| light | danger_text on danger_bg | 4.09 | FAIL |
| dark | text_default on surface_1 | 14.37 | PASS |
| dark | text_secondary on surface_1 | 8.24 | PASS |
| dark | text_default on surface_2 | 11.77 | PASS |
| dark | button_primary_text on button_primary_bg | 3.13 | FAIL |
| dark | danger_text on danger_bg | 4.09 | FAIL |

## 5. Evidence (Implementation Lines)

- Dark/light + motion + focus foundations:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:160`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:210`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:226`
- Button/field semantic mapping:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:19`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:49`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:109`
- Layering + modal/chart contract classes:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:222`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:356`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:369`

## 6. Remaining Work

1. Resolve contrast failures for:
- `button_primary_text on button_primary_bg` in dark mode.
- `danger_text on danger_bg` in light/dark.
2. Apply fix via Design Pack token update or approved accessibility exception policy.
3. Re-run visual QA and issue a new report with `C-17 = PASS`.

## 7. Sign-Off

- Current sign-off status: `Not approved` (`C-17` unresolved).

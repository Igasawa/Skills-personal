# Dashboard Screen Adoption Report (Run #4: Contrast Fixed)

Run date: `2026-02-09`
Checklist: `references/dashboard_screen_adoption_checklist.md`
Guideline baseline: `references/dashboard_token_mapping_guideline.md`
Method:
- Static audit (token/focus/motion/z-index contract)
- Browser visual QA (Playwright CLI screenshots in light/dark)
- Contrast ratio re-check after accessibility color adjustment

## 1. Executive Result

- Overall result: `PASS` (current scope)
- Result summary:
- `C-06` remains `PASS` (light/dark parity)
- `C-17` is now `PASS` (previous contrast failures resolved)

## 2. Visual Evidence Artifacts

Path: `output/playwright/design-qa/`

- `home-light-v2.png`
- `home-dark-v2.png`
- `run-light-v2.png`
- `run-dark-v2.png`
- `excluded-light-v2.png`
- `excluded-dark-v2.png`
- `archive-light-v2.png`
- `archive-dark-v2.png`

## 3. Checklist Outcome (Run #4)

| ID | Status | Note |
| --- | --- | --- |
| C-01 | PASS | Semantic aliases are applied to shared controls. |
| C-02 | PASS | RGB/HSL token format contract is implemented. |
| C-03 | PASS | Migration remains additive. |
| C-04 | PASS | Focus-visible styles are implemented and visible. |
| C-05 | PASS | Reduced-motion handling is implemented. |
| C-06 | PASS | Light/dark parity verified on all target screens. |
| C-07 | PASS | z-index token mapping is aligned in current scope. |
| C-08 | PASS | Home cards map to semantic surface/border/text. |
| C-09 | PASS | Form fields map to semantic field tokens. |
| C-10 | PASS | Actions map to semantic button tokens. |
| C-11 | PASS | Run detail KPI/status areas map to semantic styling. |
| C-12 | PASS | Table structure and interaction styles are aligned. |
| C-13 | PASS | Feedback visuals map to semantic feedback aliases. |
| C-14 | PASS | Excluded filter controls follow semantic mapping. |
| C-15 | PASS | Excluded table/actions follow semantic mapping. |
| C-16 | PASS | Archive filter/table follows shared baseline mapping. |
| C-17 | PASS | Key text/surface/button/feedback contrast checks satisfy AA normal threshold. |
| C-18 | N/A | Chart UI is not rendered in current dashboard scope. |
| C-19 | N/A | Modal UI is not rendered in current dashboard scope. |

## 4. Contrast Re-Check (AA Normal Threshold 4.5:1)

| Mode | Pair | Ratio | Result |
| --- | --- | --- | --- |
| light | text_default on surface_1 | 17.89 | PASS |
| light | text_secondary on surface_1 | 7.53 | PASS |
| light | text_default on surface_2 | 15.95 | PASS |
| light | button_primary_text on button_primary_bg | 4.72 | PASS |
| light | danger_text on danger_bg | 4.72 | PASS |
| light | success_text on success_bg | 7.31 | PASS |
| light | info_text on info_bg | 4.56 | PASS |
| light | warning_text on warning_bg | 9.72 | PASS |
| dark | text_default on surface_1 | 14.37 | PASS |
| dark | text_secondary on surface_1 | 8.24 | PASS |
| dark | text_default on surface_2 | 11.77 | PASS |
| dark | button_primary_text on button_primary_bg | 6.17 | PASS |
| dark | danger_text on danger_bg | 4.72 | PASS |
| dark | success_text on success_bg | 8.96 | PASS |
| dark | info_text on info_bg | 7.10 | PASS |
| dark | warning_text on warning_bg | 10.63 | PASS |

## 5. Delta from Run #3

- `semantic-button-primary-text` is overridden in dark mode to improve primary button contrast.
- feedback text aliases (`success/danger/info`) use accessible dark text.
- low-contrast small status/error text colors were moved to readable text tokens.

## 6. Sign-Off

- Current sign-off status: `Approved` for current implemented scope (`C-01` to `C-17`).

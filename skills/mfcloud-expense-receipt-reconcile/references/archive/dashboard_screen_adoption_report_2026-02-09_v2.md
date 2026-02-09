# Dashboard Screen Adoption Report (Run #2)

Run date: `2026-02-09`
Checklist: `references/dashboard_screen_adoption_checklist.md`
Guideline baseline: `references/dashboard_token_mapping_guideline.md`
Method: static code audit after token migration (`CSS/HTML/JS`).

## 1. Executive Result

- Overall result: `PARTIAL PASS`
- Scope result:
- Contract checks (`C-01` to `C-16` excluding visual-only criteria) are now mostly satisfied.
- Visual QA dependent checks remain `PENDING` until browser verification is completed.

## 2. Checklist Outcome (Run #2)

| ID | Status | Note |
| --- | --- | --- |
| C-01 | PASS | Shared control styling now references semantic aliases (`semantic-button-*`, `semantic-field-*`, `semantic-feedback-*`). |
| C-02 | PASS | RGB token usage standardized; chart contract classes use `hsl(var(--chart-*))`. |
| C-03 | PASS | Additive migration applied; no token key removal/rename introduced. |
| C-04 | PASS | Global and field-level `focus-visible` styles are defined. |
| C-05 | PASS | Reduced motion media query is implemented. |
| C-06 | PENDING | Light/dark token sets are defined, but browser visual verification is still pending. |
| C-07 | PASS | z-index contract variables are defined and mapped for toast/modal layers. |
| C-08 | PASS | Home cards use surface and semantic border tokens. |
| C-09 | PASS | Field controls use semantic border/background/text/focus tokens. |
| C-10 | PASS | Primary/secondary/action button styles map to semantic button aliases. |
| C-11 | PASS | Run detail KPI/status blocks map to semantic/surface tokens. |
| C-12 | PASS | Table header/divider/hover/active states map to semantic interaction and border tokens. |
| C-13 | PASS | Feedback states use semantic danger/success/warning aliases. |
| C-14 | PASS | Excluded page filters inherit semantic field and interaction styling. |
| C-15 | PASS | Excluded page actions inherit semantic button/feedback styling. |
| C-16 | PASS | Archive page filter and table styles follow shared semantic rules. |
| C-17 | PENDING | Contrast validation requires runtime visual QA in light and dark. |
| C-18 | N/A | Chart UI is not rendered yet; contract class stubs were added for future charts. |
| C-19 | N/A | Modal UI is not rendered yet; modal/backdrop contract classes were added. |

## 3. Evidence (Key Lines)

- Semantic/token foundations:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:75`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:91`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:160`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:226`
- Focus visibility:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:210`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:123`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:127`
- Semantic control mapping:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:19`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:49`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:109`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:149`
- Table/interaction mapping:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:342`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:348`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:352`
- Layering and modal/backdrop contract:
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:62`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/base.css:67`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:222`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:356`
- Token format contract (`rgb` + `hsl`):
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:50`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/components.css:369`

## 4. Remaining Work

1. Execute browser QA in light and dark to close `C-06` and `C-17`.
2. Capture screenshots and attach evidence to the next report.
3. If needed, tune token values only via aliases (not direct hardcoded colors).

## 5. Sign-Off Gate

- Current sign-off status: `Not yet` (pending visual QA).
- Next report target: all applicable checks `PASS`.

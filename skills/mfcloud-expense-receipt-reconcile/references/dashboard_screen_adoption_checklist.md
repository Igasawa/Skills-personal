# Dashboard Screen Adoption Checklist

Date: `2026-02-09`
Target package: Growfidence Design Pack `1.1.0`
Reference: `references/dashboard_token_mapping_guideline.md`

## 1. Target Screens

| Screen | Route | Main elements |
| --- | --- | --- |
| Dashboard home | `/` | cards, run cards, form inputs, primary/secondary buttons, status chips |
| Run detail | `/runs/{ym}` | KPI stats, action buttons, data tables, status notes |
| Excluded PDFs | `/runs/{ym}/excluded-pdfs` | filter inputs/selects, checkboxes, table, single-print actions |
| Archived receipts | `/runs/{ym}/archived-receipts` | filter inputs/selects, table |

## 2. Checklist Matrix

Status values:
- `PASS`
- `FAIL`
- `N/A`
- `PENDING`

| ID | Area | Check item | Pass condition | Status | Evidence / note |
| --- | --- | --- | --- | --- | --- |
| C-01 | Global | Semantic-first mapping | Shared controls use semantic aliases, not direct brand utility classes | PENDING |  |
| C-02 | Global | Token format contract | RGB tokens use `rgb(...)`; chart tokens use `hsl(...)` | PENDING |  |
| C-03 | Global | Additive migration policy | No existing token key rename/remove in rollout 1 | PENDING |  |
| C-04 | Global | Focus visibility | Button/Input/Select have visible focus in light and dark | PENDING |  |
| C-05 | Global | Reduced motion support | Reduced motion mode maps to duration-reduced behavior | PENDING |  |
| C-06 | Global | Dark/light parity | Light and dark theme both defined and legible | PENDING |  |
| C-07 | Global | z-index contract | Layer order follows dashboard guideline baseline | PENDING |  |
| C-08 | Home | KPI/run cards | Card surface/text/border map to baseline tokens | PENDING |  |
| C-09 | Home | Form fields | Input/select background/text/border/focus align to semantic field tokens | PENDING |  |
| C-10 | Home | Actions | Primary/secondary/link button semantics align to guideline | PENDING |  |
| C-11 | Run detail | KPI stat tiles | stat blocks follow card + feedback token rules | PENDING |  |
| C-12 | Run detail | Table styling | table background/header/divider/hover use baseline mapping | PENDING |  |
| C-13 | Run detail | Status feedback | success/warning/danger status UI uses semantic feedback mapping | PENDING |  |
| C-14 | Excluded PDFs | Filter bar | search/select/checkbox controls follow semantic field + interaction tokens | PENDING |  |
| C-15 | Excluded PDFs | Table + actions | row and actions follow semantic button/interaction mapping | PENDING |  |
| C-16 | Archive | Filter bar | field and action states satisfy same rule as excluded page | PENDING |  |
| C-17 | Archive | Table readability | text/surface contrast and divider mapping pass thresholds | PENDING |  |
| C-18 | Chart (future) | Chart semantics | stable color order (`chart.1` to `chart.5`) and threshold mapping | N/A | activate only when chart UI is added |
| C-19 | Modal (future) | Modal contract | backdrop/modal z-index and dark opacity baseline match guideline | N/A | activate only when modal UI is added |

## 3. Execution Protocol

1. Run static audit first (token references, focus rules, motion rules, z-index usage).
2. Run visual QA in browser for all target screens in light and dark.
3. Record status and evidence for every check row.
4. Open issue for every `FAIL` item with owner and fix note.
5. Re-run checklist and update status to `PASS` only after verification.

## 4. Sign-Off Rule

- Sign-off is allowed only when all applicable (`PASS`/`FAIL`) checks are `PASS`.
- `N/A` is allowed only for features not present in current scope.

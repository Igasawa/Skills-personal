# Dashboard Design Execution Plan (Item 1 + Item 2)

Date: `2026-02-09`
Target pack: Growfidence Design Pack `1.1.0`
Base guideline: `references/dashboard_token_mapping_guideline.md`

## 1. Goal

- Item 1: Prepare a reusable handoff package text for other product teams.
- Item 2: Define and execute a screen-level adoption checklist for the dashboard.

## 2. Workstreams

### WS1: Handoff Template Production (Item 1)

Objective:
- Convert the current dashboard guideline into a copy/paste handoff format for receiving teams.

Tasks:
- `WS1-T1` Extract fixed contract values from the current guideline and token pack.
- `WS1-T2` Build one handoff template with version, scope, required files, acceptance criteria.
- `WS1-T3` Add "do not" rules (no brand utility hardcode in shared controls, semantic-first policy).
- `WS1-T4` Review for portability (no repo-specific implementation detail leakage).

Deliverable:
- `references/dashboard_handoff_template.md` (new)

Done criteria:
- Template includes `Version`, `Release Date`, `Change Type`, `Files`, `Scope`, `Acceptance`.
- Template references locked decisions from `dashboard_token_mapping_guideline.md`.
- Template is usable as-is by another product team without extra editing.

### WS2: Screen Adoption Checklist and Execution (Item 2)

Objective:
- Make token adoption verifiable on actual dashboard screens.

Tasks:
- `WS2-T1` Define target screens/components (KPI card, table, filter bar, chart area, modal).
- `WS2-T2` Build per-screen token mapping checks (semantic alias usage, interaction states, focus ring, layer order).
- `WS2-T3` Add QA checks (contrast, reduced motion, dark/light parity, chart color consistency).
- `WS2-T4` Execute checklist on current dashboard and log pass/fail with notes.

Deliverables:
- `references/dashboard_screen_adoption_checklist.md` (new)
- `references/dashboard_screen_adoption_report_2026-02-XX.md` (new, execution report)

Done criteria:
- All target screens have explicit pass/fail entries.
- Any fail item has owner + fix note + recheck status.
- Final report confirms whether section 6 criteria in the guideline are satisfied.

## 3. Sequencing and Dates

| Date | Step | Output |
| --- | --- | --- |
| 2026-02-09 | Plan lock (this file) | Execution baseline fixed |
| 2026-02-10 | WS1-T1 to WS1-T3 | Handoff template v1 |
| 2026-02-11 | WS2-T1 to WS2-T2 | Screen checklist v1 |
| 2026-02-12 | WS2-T3 to WS2-T4 (run #1) | Adoption report draft |
| 2026-02-13 | Recheck and sign-off | Final adoption report |

## 4. Roles

- Design system owner: approve semantic and visual contract.
- Frontend owner: implement token mapping and fix failures.
- QA owner: run checklist in light/dark and reduced-motion conditions.

## 5. Risks and Controls

- Risk: RGB/HSL format misuse.
- Control: enforce WS2 checklist item for `rgb(...)` vs `hsl(...)`.
- Risk: Secondary action style drift to accent color buttons.
- Control: enforce `semantic.button.secondary.*` as default secondary action.
- Risk: Dark modal backdrop readability mismatch.
- Control: verify baseline opacity (`0.56`) and adjust only with logged QA reason.

## 6. Exit Condition

- WS1 deliverable approved.
- WS2 report shows no unresolved high-impact visual/interaction defects.
- Dashboard can be declared "Design Pack aligned (v1.1.0)" for the defined scope.

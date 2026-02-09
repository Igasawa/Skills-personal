# Dashboard Semantic Token Mapping (Draft)

This draft maps dashboard UI elements to Growfidence Design Pack tokens.
Target package version: `1.1.0` (release date `2026-02-09`).

## 1. Scope

- KPI Card
- Data Table
- Filter Area (Input/Select/Button)
- Chart Area
- Modal

## 2. Mapping Matrix

| Area | Element / State | Token Source | Notes |
| --- | --- | --- | --- |
| KPI Card | Card background | `tokens.color.surface.1` | Base surface for dashboard cards |
| KPI Card | Card border | `tokens.semantic.field.borderDefault` | Do not use brand utility colors directly |
| KPI Card | Title text | `tokens.color.text.secondary` | Secondary hierarchy |
| KPI Card | Main value text | `tokens.color.text.default` | Primary readability target |
| KPI Card | Delta positive chip | `tokens.semantic.feedback.success.surface` + `tokens.semantic.feedback.success.text` | Keep semantic meaning first |
| KPI Card | Delta warning chip | `tokens.semantic.feedback.warning.surface` + `tokens.semantic.feedback.warning.text` | Warning text token is fixed in pack |
| KPI Card | Delta danger chip | `tokens.semantic.feedback.danger.surface` + `tokens.semantic.feedback.danger.text` | For negative critical metrics |
| KPI Card | Card action button (default) | `tokens.semantic.button.secondary.*` | Use this as default secondary action |
| KPI Card | Card action button (high-emphasis) | `tokens.semantic.button.primary.*` | Use only if card has one primary CTA |
| Data Table | Table background | `tokens.color.surface.1` | Main container background |
| Data Table | Header row background | `tokens.color.surface.2` | Distinguish header from body |
| Data Table | Header text | `tokens.color.text.secondary` | Keep lower visual weight than key values |
| Data Table | Body text | `tokens.color.text.default` | Main data readability |
| Data Table | Row divider | `tokens.semantic.field.borderDefault` | Semantic border baseline |
| Data Table | Row hover | `tokens.semantic.interaction.hoverOverlay` | Hover affordance only |
| Data Table | Row active/selected | `tokens.semantic.interaction.activeOverlay` | Selection feedback |
| Data Table | Inline error state | `tokens.semantic.feedback.danger.*` | Error badges and callouts |
| Filter Area | Input background | `tokens.semantic.field.background` | Keep inputs neutral |
| Filter Area | Input text | `tokens.semantic.field.text` | Shared field text color |
| Filter Area | Input border default | `tokens.semantic.field.borderDefault` | Baseline field border |
| Filter Area | Input border hover | `tokens.semantic.field.borderHover` | Optional for richer affordance |
| Filter Area | Input border focus | `tokens.semantic.field.borderFocus` | Focus border color |
| Filter Area | Focus ring | `tokens.semantic.interaction.focusRing` | Must be visible in both themes |
| Filter Area | Apply/Search button | `tokens.semantic.button.primary.*` | Primary flow action |
| Filter Area | Reset/Clear button | `tokens.semantic.button.outline.*` | Secondary reset action |
| Filter Area | Link action | `tokens.semantic.button.link.*` | Text-only utility actions |
| Chart Area | Plot background | `tokens.color.surface.1` | Match surrounding card |
| Chart Area | Grid/axis line | `tokens.color.surface.3` | Low-contrast structural lines |
| Chart Area | Axis/legend text | `tokens.color.text.secondary` | Supporting text |
| Chart Area | Series colors | `tokens.color.chart.1` to `tokens.color.chart.5` | Keep stable series ordering |
| Chart Area | Threshold warning line | `tokens.color.state.warning` | For caution thresholds |
| Chart Area | Threshold danger line | `tokens.color.state.danger` | For breach thresholds |
| Chart Area | Tooltip background | `tokens.color.surface.1` | Use card-like tooltip surface |
| Chart Area | Tooltip border | `tokens.semantic.field.borderDefault` | Neutral border |
| Chart Area | Tooltip text | `tokens.color.text.default` | High readability |
| Modal | Backdrop layer | `tokens.zIndex.modalBackdrop` (`400`) | Must stay above overlays/dropdowns |
| Modal | Backdrop color | `tokens.color.surface.overlay` | Validate dark mode opacity in QA |
| Modal | Modal body layer | `tokens.zIndex.modal` (`500`) | Modal content layer |
| Modal | Modal body surface | `tokens.color.surface.1` | Base dialog surface |
| Modal | Modal border | `tokens.semantic.field.borderDefault` | Neutral border |
| Modal | Modal title/body text | `tokens.color.text.default` | Main copy |
| Modal | Modal supporting text | `tokens.color.text.secondary` | Explanatory copy |
| Modal | Modal actions primary | `tokens.semantic.button.primary.*` | Confirm/submit |
| Modal | Modal actions secondary | `tokens.semantic.button.secondary.*` | Cancel/back |

## 3. Layering Baseline for Dashboard

| Layer | Token | Value |
| --- | --- | --- |
| Action bar | `tokens.zIndex.actionbar` | `80` |
| Dropdown (table/filter) | `tokens.zIndex.dropdown` | `135` |
| Overlay | `tokens.zIndex.overlay` | `140` |
| Header | `tokens.zIndex.header` | `145` |
| Sidebar | `tokens.zIndex.sidebar` | `150` |
| Modal backdrop | `tokens.zIndex.modalBackdrop` | `400` |
| Modal body | `tokens.zIndex.modal` | `500` |
| Tooltip | `tokens.zIndex.tooltip` | `700` |
| Toast | `tokens.zIndex.toast` | `9999` |

## 4. Dashboard-Specific Rules

- Rule 1: Shared UI controls (button/input/select/alert/card) must use `tokens.semantic.*` first.
- Rule 2: `tokens.modeTheme.*` can be used only in feature-level mode containers, not in shared controls.
- Rule 3: Dashboard chart series must keep fixed order (`chart.1` to `chart.5`) across screens.
- Rule 4: Use `tokens.semantic.button.secondary.*` as the default secondary action style.
- Rule 5: Use `tokens.semantic.button.primary.*` only when the card/section has one clear main CTA.
- Rule 6: Keep migration additive only; do not rename/remove existing token keys in rollout 1.
- Rule 7: RGB tokens must be consumed with `rgb(...)`; chart HSL tokens must be consumed with `hsl(...)`.
- Rule 8: Modal backdrop in dark mode must apply alpha via `rgb(var(--surface-overlay) / <alpha>)`.

## 5. QA Checklist (Dashboard Extension)

- Contrast: body text and card/table surfaces pass threshold in light and dark.
- Interaction states: `default`, `hover`, `active`, `disabled`, `error` exist for buttons and fields.
- Focus visibility: focus ring is visible for button/input/select in both themes.
- Layering: no conflicts among sticky header, dropdown, tooltip, modal.
- Motion: reduced motion mode maps transitions to `tokens.motion.durationReduced`.
- Token sync: semantic aliases in app theme match `tokens.json` values.
- Chart consistency: series color ordering and threshold color semantics are stable across pages.

## 6. Resolved Decisions

- Decision 1 (token format): lock mixed-format handling as follows.
- Use `rgb(var(--token) / <alpha>)` for RGB-channel tokens (brand/state/surface/text).
- Use `hsl(var(--token) / <alpha>)` for chart tokens (`tokens.color.chart.*`).
- Do not cross-use RGB tokens with `hsl(...)` or HSL tokens with `rgb(...)`.
- Decision 2 (secondary action): lock secondary action to `tokens.semantic.button.secondary.*` for dashboard controls.
- `semanticUsage.secondaryAction` (`brand.sub500`) is treated as contextual accent only (badge/icon/highlight), not shared secondary button background.
- Decision 3 (dark modal backdrop): lock backdrop opacity in dark mode by applying alpha on top of `tokens.color.surface.overlay`.
- Recommended baseline: light `0.40`, dark `0.56` (final value may be tuned during QA if readability fails).

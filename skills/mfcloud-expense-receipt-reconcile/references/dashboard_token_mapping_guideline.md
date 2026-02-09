# Dashboard Token Mapping Guideline (Implementation-Ready)

Applies to: Growfidence Design Pack `1.1.0` (`2026-02-09`)
Source draft: `references/dashboard_token_mapping_draft.md`
Status: ready for dashboard implementation.

## 1. Mandatory Decisions (Locked)

- Use `tokens.semantic.*` first for shared controls.
- Use `tokens.modeTheme.*` only for feature-level mode containers.
- Lock dashboard secondary actions to `tokens.semantic.button.secondary.*`.
- Allow `tokens.semantic.button.primary.*` only for one clear primary CTA in a section.
- Keep chart series order fixed: `tokens.color.chart.1` to `tokens.color.chart.5`.
- Use additive migration only; no token key rename/remove in rollout 1.

## 2. Token Format Contract (Locked)

- RGB-channel tokens (brand/state/surface/text): use `rgb(var(--token) / <alpha>)`.
- Chart tokens (`tokens.color.chart.*`): use `hsl(var(--token) / <alpha>)`.
- Never cross-use RGB tokens with `hsl(...)` or HSL tokens with `rgb(...)`.

## 3. Modal Backdrop Contract (Locked)

- Backdrop layer: `tokens.zIndex.modalBackdrop` (`400`).
- Modal layer: `tokens.zIndex.modal` (`500`).
- Backdrop color base: `tokens.color.surface.overlay`.
- Opacity baseline: light `0.40`, dark `0.56`.

```css
.modal-backdrop {
  background: rgb(var(--surface-overlay) / 0.40);
  z-index: var(--z-modal-backdrop);
}

[data-theme="dark"] .modal-backdrop {
  background: rgb(var(--surface-overlay) / 0.56);
}

.modal {
  z-index: var(--z-modal);
}
```

## 4. Area-to-Token Baseline

| Area | Baseline mapping |
| --- | --- |
| KPI Card | `surface.1`, `text.default`, `text.secondary`, `semantic.field.borderDefault`, `semantic.feedback.*` |
| Data Table | `surface.1`, `surface.2`, `text.default`, `text.secondary`, `semantic.interaction.hoverOverlay`, `semantic.interaction.activeOverlay` |
| Filter Area | `semantic.field.*`, `semantic.interaction.focusRing`, `semantic.button.primary/outline/link.*` |
| Chart Area | `surface.1`, `surface.3`, `text.secondary`, `color.chart.1-5`, `state.warning`, `state.danger` |
| Modal | `zIndex.modalBackdrop`, `zIndex.modal`, `surface.overlay`, `surface.1`, `semantic.button.primary/secondary.*` |

## 5. CSS Usage Examples

```css
.btn-primary {
  background: rgb(var(--brand-main-500));
  color: rgb(var(--brand-contrast-strong));
}

.chart-series-1 {
  stroke: hsl(var(--chart-1));
}

.table-row:hover {
  background: rgb(var(--surface-2));
}
```

## 6. QA Sign-Off Criteria

- Contrast passes for light and dark text/surface pairs.
- Button/Input/Select support `default`, `hover`, `active`, `disabled`, `error`.
- Focus ring remains visible in both themes.
- No z-index conflicts among header, dropdown, tooltip, and modal.
- Reduced motion behavior maps to `tokens.motion.durationReduced`.
- App semantic aliases match `tokens.json` values.
- Chart color order and threshold semantics are consistent across pages.

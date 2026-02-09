# Dashboard Handoff Template

Use this template when handing the dashboard design contract to another product team.

## 1. Copy/Paste Text

```text
Design package: Growfidence Design Pack
Version: 1.1.0
Release Date: 2026-02-09
Change Type: non-breaking

Files:
- tokens.json
- guideline.md
- CHANGELOG.md
- dashboard_token_mapping_guideline.md (dashboard supplement)

Scope:
- Core color tokens (brand/state/surface/text/chart)
- Semantic aliases for interaction/button/field/feedback
- Typography, spacing, radius, shadow, motion
- z-index stack
- Optional mode accents (modeTheme)
- Dashboard baseline mapping (KPI/table/filter/modal)

Locked Decisions:
1) Semantic-first for shared UI controls.
2) modeTheme is allowed only in feature-level containers.
3) Secondary action uses semantic.button.secondary.* by default.
4) Token format contract is strict:
   - RGB tokens -> rgb(var(--token) / <alpha>)
   - Chart HSL tokens -> hsl(var(--token) / <alpha>)
5) Modal backdrop baseline opacity:
   - light: 0.40
   - dark: 0.56

Prohibited:
- No brand utility hardcoding inside shared components.
- Do not rename or remove existing token keys in rollout 1.

Acceptance:
- Pass dashboard QA sign-off criteria in dashboard_token_mapping_guideline.md section 6
- Verify contrast, interaction states, focus visibility, layer ordering, reduced motion, token sync
```

## 2. Sender Checklist

- Confirm package metadata matches current `tokens.json`.
- Attach all listed files.
- Include known limitations and N/A areas (if chart or modal are not yet implemented).
- Include first adoption report and open issues.

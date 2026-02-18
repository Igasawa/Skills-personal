---
last_reviewed: 2026-02-18
review_source: knowledge_refresh_weekly
---
# Automation Jobs Runbook

## Purpose

`ax jobs` 縺ｧ縲悟ｮ悟・閾ｪ蜍募喧繧ｸ繝ｧ繝悶阪・螳壽悄螳溯｡後→邨先棡蜿ｯ隕門喧繧定｡後≧縲・

- 繝ｬ繧ｸ繧ｹ繝医Μ: `docs/automation_schedule_registry.json`
- 螳溯｡後Ο繧ｰ: `AX_HOME/runs/...`
- 繝繝・す繝･繝懊・繝・ `AX_HOME/reports/automation_dashboard/schedule.html` / `results.html`

## Commands

```powershell
# 1) 繝ｬ繧ｸ繧ｹ繝医Μ讀懆ｨｼ
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 jobs validate

# 2) 繧ｸ繝ｧ繝紋ｸ隕ｧ縺ｨ谺｡蝗槫ｮ溯｡梧凾蛻ｻ
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 jobs list

# 3) 莉ｻ諢上ず繝ｧ繝悶ｒ謇句虚螳溯｡・
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 jobs run --job-id knowledge_refresh_weekly --trigger manual

# 4) 迴ｾ蝨ｨ譎ょ綾縺ｫ due 縺ｮ繧ｸ繝ｧ繝悶□縺大ｮ溯｡・
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 jobs run-due --dashboard --days 30

# 5) 繝繝・す繝･繝懊・繝峨□縺大・逕滓・
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 jobs dashboard --days 30
```

## Windows Task Scheduler Example

5蛻・＃縺ｨ縺ｫ `run-due` 繧貞ｮ溯｡後☆繧倶ｾ・

```powershell
schtasks /Create /F /SC MINUTE /MO 5 /TN "AX-Automation-RunDue" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\TatsuoIgasawa\.vscode\Skills\scripts\ax.ps1 jobs run-due --dashboard --days 30"
```

## Notes

- kintone 謚慕ｨｿ邉ｻ縺ｯ `preflight_required=true` 繧貞渕譛ｬ縺ｫ縺吶ｋ縲・
- `--skip-preflight` 縺ｮ萓句､夜°逕ｨ縺ｯ逅・罰繧貞ｿ・★谿九☆・・kintone-gas-price-notification` 縺ｯ `--skip-preflight-reason` 蠢・茨ｼ峨・
- secrets 縺ｯ蠢・★ `AX_HOME/secrets/*.env` 縺ｧ邂｡逅・＠縲√Μ繝昴ず繝医Μ縺ｫ縺ｯ鄂ｮ縺九↑縺・・


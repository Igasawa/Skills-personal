---
last_reviewed: 2026-02-18
review_source: knowledge_refresh_weekly
---
# 蠑輔″邯吶℃譖ｸ: automation jobs 蝓ｺ逶､・・026-02-18・・

## 1. 逶ｮ逧・

繝ｯ繝ｼ繧ｯ繝輔Ο繝ｼ謇ｿ隱榊梛莉･螟悶・縲悟ｮ悟・閾ｪ蜍募喧讌ｭ蜍吶阪ｒ螳壽悄螳溯｡後＠縲∫ｵ先棡繧貞庄隕門喧縺吶ｋ縺溘ａ縺ｮ蝓ｺ逶､繧定ｿｽ蜉縺励◆縲・

- 繧ｹ繧ｱ繧ｸ繝･繝ｼ繝ｫ邂｡逅・ `ax jobs`
- 螳溯｡後Ο繧ｰ菫晏ｭ・ `AX_HOME/runs/...`
- 蜿ｯ隕門喧繝壹・繧ｸ: `AX_HOME/reports/automation_dashboard/schedule.html`, `results.html`

## 2. 蜿肴丐貂医∩繧ｳ繝溘ャ繝・

- `9055283` feat(axkit): add scheduled jobs runner and dashboard pages
- `1134ac1` feat(gas-price): require skip-preflight reason for audit trail

蜿肴丐蜈医ヶ繝ｩ繝ｳ繝・
- `Skills-main`
- `origin/Skills-main` 縺ｨ蜷梧悄貂医∩・亥ｷｮ蛻・↑縺暦ｼ・

## 3. 霑ｽ蜉繝ｻ螟画峩繝輔ぃ繧､繝ｫ

### axkit・域眠隕擾ｼ・

- `packages/axkit/axkit/jobs_registry.py`
- `packages/axkit/axkit/jobs_schedule.py`
- `packages/axkit/axkit/jobs_runner.py`
- `packages/axkit/axkit/jobs_store.py`
- `packages/axkit/axkit/jobs_dashboard.py`

### axkit・亥､画峩・・

- `packages/axkit/axkit/cli.py`  
  `jobs` 繧ｵ繝悶さ繝槭Φ繝芽ｿｽ蜉:
  - `validate`
  - `list`
  - `run`
  - `run-due`
  - `dashboard`

### docs

- `docs/automation_schedule_registry.json`・医せ繧ｱ繧ｸ繝･繝ｼ繝ｫ螳夂ｾｩ・・
- `docs/automation_schedule_registry.schema.json`・医せ繧ｭ繝ｼ繝橸ｼ・
- `docs/automation_jobs_runbook.md`・磯°逕ｨ謇矩・ｼ・
- `docs/automation_jobs_handover_2026-02-18.md`・医％縺ｮ蠑輔″邯吶℃譖ｸ・・

### skill謾ｹ蝟・

- `skills/kintone-gas-price-notification/scripts/run_flow.py`
- `skills/kintone-gas-price-notification/scripts/run_processing.py`
- `skills/kintone-gas-price-notification/SKILL.md`
- `skills/docs-knowledge-refresh/scripts/run_support.py`
- `skills/docs-knowledge-refresh/scripts/run_processing.py`

## 4. 迴ｾ蝨ｨ縺ｮ逋ｻ骭ｲ繧ｸ繝ｧ繝厄ｼ・docs/automation_schedule_registry.json`・・

1. `gas_price_monthly`
- schedule: `0 9 10 * *`
- timezone: `Asia/Tokyo`
- `preflight_required: true`
- secrets: `kintone`
- command: `python -m scripts.run --post --day 10`・・skills/kintone-gas-price-notification` 縺ｧ螳溯｡鯉ｼ・

2. `knowledge_refresh_weekly`
- schedule: `0 8 * * 1`
- timezone: `Asia/Tokyo`
- command: `python -m scripts.run --scan ../../docs --registry ../../docs/knowledge_refresh_registry.json --fail-on-stale --write-report --apply`・・skills/docs-knowledge-refresh` 縺ｧ螳溯｡鯉ｼ・

## 5. 驥崎ｦ∽ｻ墓ｧ・

### 5.1 螳溯｡後Ο繧ｰ

- 1螳溯｡・JSON縺ｧ菫晏ｭ・
- 菫晏ｭ伜・: `AX_HOME/runs/<job_id>/YYYY/MM/DD/<run_id>.json`
- 荳ｻ隕・・岼:
  - `job_id`, `run_id`, `trigger`, `scheduled_for_utc`
  - `status`, `exit_code`, `error_message`
  - `attempts[]`・・tdout/stderr preview蜷ｫ繧・・
  - `result`・・kill縺ｮ `status/data/error`・・

### 5.2 preflight萓句､夜°逕ｨ縺ｮ逶｣譟ｻ

`kintone-gas-price-notification` 縺ｯ莉･荳九ｒ蠑ｷ蛻ｶ:

- `--skip-preflight` 繧剃ｻ倥￠縺ｦ譛ｬ螳溯｡鯉ｼ・--post`・峨☆繧句ｴ蜷・ 
  `--skip-preflight-reason` 縺悟ｿ・・

蜃ｺ蜉妍SON:
- `data.preflight.skip_requested`
- `data.preflight.skip_reason`

## 6. 蜍穂ｽ懃｢ｺ隱阪さ繝槭Φ繝会ｼ域眠迺ｰ蠅・・蝗橸ｼ・

```powershell
# 0) AX_HOME蛻晄悄蛹・
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets init

# 1) 繝ｬ繧ｸ繧ｹ繝医Μ讀懆ｨｼ
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 jobs validate

# 2) 繧ｸ繝ｧ繝紋ｸ隕ｧ
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 jobs list

# 3) due螳溯｡鯉ｼ医ユ繧ｹ繝域凾蛻ｻ謖・ｮ夲ｼ・
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 jobs run-due --now 2026-02-18T00:01:00+00:00 --dashboard --days 14

# 4) 繝繝・す繝･繝懊・繝臥函謌・
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 jobs dashboard --days 30
```

## 7. 譌｢遏･莠矩・/ 豕ｨ諢冗せ

1. `knowledge_refresh_weekly` 縺ｯ迴ｾ迥ｶ `--fail-on-stale` 縺ｪ縺ｮ縺ｧ縲∝ｯｾ雎｡docs縺ｫ譛滄剞蛻・ｌ縺後≠繧矩剞繧・`error` 縺ｧ邨ゆｺ・☆繧九・ 
   縺薙ｌ縺ｯ縲檎屮隕匁､懃衍縺ｨ縺励※縺ｯ豁｣蟶ｸ蜍穂ｽ懊阪・

2. Windows迺ｰ蠅・〒 `tzdata` 縺後↑縺・ｴ蜷医！ANA timezone隗｣豎ｺ縺ｧ螟ｱ謨励☆繧九％縺ｨ縺後≠繧九・ 
   譛ｬ螳溯｣・・ `Asia/Tokyo` 縺ｨ `UTCﾂｱhh[:mm]` 縺ｮ繝輔か繝ｼ繝ｫ繝舌ャ繧ｯ繧貞ｮ溯｣・ｸ医∩縲・ 
   莉悶ち繧､繝繧ｾ繝ｼ繝ｳ繧剃ｽｿ縺・ｴ蜷医・ `tzdata` 蟆主・繧呈耳螂ｨ縲・

3. secrets / session 縺ｯ蠢・★ `AX_HOME` 蛛ｴ縺ｫ驟咲ｽｮ縺吶ｋ縲・ 
   繝ｪ繝昴ず繝医Μ蜀・↓鄂ｮ縺九↑縺・％縺ｨ縲・

## 8. 谺｡縺ｫ繧・ｋ縺薙→・域耳螂ｨ鬆・ｼ・

1. Task Scheduler 縺ｫ `ax jobs run-due --dashboard --days 30` 繧・5縲・0蛻・俣髫斐〒逋ｻ骭ｲ縲・
2. `knowledge_refresh_weekly` 縺ｮ驕狗畑譁ｹ驥昴ｒ遒ｺ螳壹・ 
   - 譛滄剞蛻・ｌ讀懃衍繧堤ｶｭ謖√☆繧九↑繧臥樟迥ｶ縺ｮ縺ｾ縺ｾ  
   - 縺ｾ縺壽・蜉溽ｳｻ驕狗畑繧貞━蜈医☆繧九↑繧・`--fail-on-stale` 縺ｮ謇ｱ縺・ｒ隱ｿ謨ｴ
3. 霑ｽ蜉繧ｸ繝ｧ繝厄ｼ井ｾ・ gas-price 譛ｬ逡ｪ謚慕ｨｿ・峨・譛牙柑蛹門燕縺ｫ sandbox preflight 縺ｮ螳溷慍遒ｺ隱阪ｒ螳滓命縲・


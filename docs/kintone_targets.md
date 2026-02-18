---
last_reviewed: 2026-02-18
review_source: knowledge_refresh_weekly
---
# kintone 謚慕ｨｿ蜈井ｸ隕ｧ・・pace / thread・・

縺薙・繝ｪ繝昴ず繝医Μ縺ｧ閾ｪ蜍募喧縺吶ｋ kintone 譖ｸ縺崎ｾｼ縺ｿ蜈茨ｼ医せ繝壹・繧ｹ/繧ｹ繝ｬ繝・ラ・峨ｒ縲！D繝吶・繧ｹ縺ｧ邁｡貎斐↓蝗ｺ螳壹☆繧九◆繧√・荳隕ｧ縲・

逶ｮ逧・
- 縲後←縺薙↓譖ｸ縺上°縲阪ｒ莠ｺ髢薙・險俶・縺ｫ萓晏ｭ倥＆縺帙↑縺・
- preflight・・andbox・峨ｒ蠢・亥喧縺励∵悽逡ｪ隱､謚慕ｨｿ縺ｮ繝ｪ繧ｹ繧ｯ繧剃ｸ九￡繧・
- 譁ｰ縺励＞謚慕ｨｿ蜈医′蠅励∴縺ｦ繧ゅ∬ｿｽ蜉謇矩・ｒ荳螳壹↓菫昴▽

蜑肴署:
- secrets・・D/繝代せ繝ｯ繝ｼ繝・繝医・繧ｯ繝ｳ・峨ｄ Playwright 縺ｮ storage_state 縺ｯ `AX_HOME` 驟堺ｸ九〒邂｡逅・＠縲√％縺ｮ繝ｪ繝昴ず繝医Μ縺ｫ縺ｯ鄂ｮ縺九↑縺・
- URL 蠖｢蠑・ `https://{subdomain}.cybozu.com/k/#/space/{space_id}/thread/{thread_id}`

## 謚慕ｨｿ蜈茨ｼ医Μ繝昴ず繝医Μ蜀・〒蜿ら・縺輔ｌ縺ｦ縺・ｋ繧ゅ・・・

### 1) sandbox・・reflight 蟆ら畑・・

- subdomain: `5atx9`
- space_id: `81`
- thread_id: `131`
- 逕ｨ騾・ 譛ｬ逡ｪ謚慕ｨｿ蜑阪・逍朱夂｢ｺ隱搾ｼ・reflight・峨ょ､ｱ謨励＠縺溘ｉ譛ｬ逡ｪ蜃ｦ逅・ｒ荳ｭ豁｢縺吶ｋ縲・
- URL:
  - space: `https://5atx9.cybozu.com/k/#/space/81`
  - thread: `https://5atx9.cybozu.com/k/#/space/81/thread/131`

繝ｪ繝昴ず繝医Μ蜀・・蜿ら・萓・
- `AGENTS.md`
- `skills/kintone-gas-price-notification/skill.yaml`
- `skills/kintone-thread-comment-cleanup/skill.yaml`

### 2) 譛ｬ逡ｪ・井ｾ・ 繧ｬ繧ｽ繝ｪ繝ｳ萓｡譬ｼ 蜻ｨ遏･・・

- subdomain: `5atx9`
- space_id: `24`
- thread_id: `36`
- 逕ｨ騾・ `kintone-gas-price-notification` 縺ｮ譌｢螳壽兜遞ｿ蜈茨ｼ域悽逡ｪ謇ｱ縺・ｼ・
- URL 萓・ `https://5atx9.cybozu.com/k/#/space/24/thread/36`

繝ｪ繝昴ず繝医Μ蜀・・蜿ら・萓・
- `skills/kintone-gas-price-notification/skill.yaml`
- `skills/kintone-gas-price-notification/references/kintone_api.md`
- `skills/kintone-thread-comment-cleanup/SKILL.md`・亥炎髯､萓具ｼ・

## 霑ｽ蜉繝ｻ螟画峩繝ｫ繝ｼ繝ｫ・磯°逕ｨ・・

譁ｰ縺励＞謚慕ｨｿ蜈茨ｼ・pace/thread・峨ｒ蠅励ｄ縺吝ｴ蜷医・縲∽ｻ･荳九ｒ蠢・★陦後≧縲・

1. 蜈医↓ sandbox・・81/131`・峨∈ preflight 謚慕ｨｿ縺ｧ縺阪ｋ縺薙→繧堤｢ｺ隱阪☆繧具ｼ医さ繝｡繝ｳ繝・D蜿門ｾ励∪縺ｧ・・
2. 譛ｬ逡ｪ謇ｱ縺・・謚慕ｨｿ蜈医・縲梧・遉ｺ繝輔Λ繧ｰ縺後↑縺・→譖ｸ縺崎ｾｼ繧√↑縺・崎ｨｭ險医ｒ邯ｭ謖√☆繧具ｼ井ｾ・ `--allow-production`・・
3. 譁ｰ縺励＞謚慕ｨｿ蜈医ｒ霑ｽ蜉縺励◆繧峨√％縺ｮ繝輔ぃ繧､繝ｫ・・docs/kintone_targets.md`・峨↓ `subdomain/space_id/thread_id/逕ｨ騾覗 繧定ｿｽ險倥☆繧・
4. 繧ｹ繧ｭ繝ｫ蛛ｴ縺ｮ譌｢螳壼､縺ｯ `skill.yaml` 縺ｮ `defaults.config` 縺ｫ鄂ｮ縺阪，LI 蠑墓焚縺ｧ荳頑嶌縺阪〒縺阪ｋ蠖｢繧堤ｶｭ謖√☆繧・

蛯呵・
- 繧ｹ繝ｬ繝・ラ蜷阪ｄ驕狗畑荳翫・蜻ｼ遘ｰ縺ｯ UI 縺ｧ螟峨ｏ繧翫≧繧九◆繧√√％縺ｮ荳隕ｧ縺ｯ ID 繧呈ｭ｣縺ｨ縺吶ｋ縲・



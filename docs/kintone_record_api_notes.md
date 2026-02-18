---
last_reviewed: 2026-02-18
review_source: knowledge_refresh_weekly
---
# kintone 繝ｬ繧ｳ繝ｼ繝陰PI・亥渕譛ｬ繝｡繝｢・・

逶ｮ逧・ kintone 繧｢繝励Μ縺ｮ縲後Ξ繧ｳ繝ｼ繝我ｽ懈・/譖ｴ譁ｰ/upsert縲阪ｒ縲√せ繧ｭ繝ｫ縺ｨ縺励※螳牙・縺ｫ閾ｪ蜍募喧縺吶ｋ縺溘ａ縺ｮ譛菴朱剞縺ｮ蜑肴署繧貞崋螳壹☆繧九・

## 菴ｿ縺・PI・域ｦりｦ・ｼ・

- 霑ｽ蜉: `POST /k/v1/record.json`
- 譖ｴ譁ｰ: `PUT /k/v1/record.json`
  - `id` 謖・ｮ壹〒譖ｴ譁ｰ
  - `updateKey`・医Θ繝九・繧ｯ繧ｭ繝ｼ・画欠螳壹〒譖ｴ譁ｰ
- upsert: `PUT /k/v1/records.json`・・upsert: true`・・
  - `records[].updateKey` 縺ｧ譖ｴ譁ｰ蟇ｾ雎｡繧呈欠螳・
  - 縺ｪ縺代ｌ縺ｰ菴懈・・域ｨｩ髯舌′蠢・ｦ・ｼ・

## 隱崎ｨｼ

縺薙・繝ｪ繝昴ず繝医Μ縺ｧ縺ｯ secrets 繧偵Μ繝昴ず繝医Μ蜀・↓鄂ｮ縺九★縲～AX_HOME` 驟堺ｸ九〒驕狗畑縺吶ｋ縲・

- ID/繝代せ繝ｯ繝ｼ繝・ `X-Cybozu-Authorization`・・ase64 `username:password`・・
- API繝医・繧ｯ繝ｳ: `X-Cybozu-API-Token`
- SSO/MFA: Playwright 縺ｧ菫晏ｭ倥＠縺・`storage_state` 繧・`AX_HOME/sessions/*.storage.json` 縺ｫ鄂ｮ縺阪√そ繝・す繝ｧ繝ｳ蜀榊茜逕ｨ

## 繧ｹ繝壹・繧ｹ縺ｨ繧｢繝励Μ

- `apps.json` 縺ｧ蜿門ｾ励〒縺阪ｋ `spaceId` 縺ｯ縲後◎縺ｮ繧｢繝励Μ縺後せ繝壹・繧ｹ驟堺ｸ九↓縺ゅｋ縲榊ｴ蜷医↓險ｭ螳壹＆繧後ｋ縲・
- `spaceId` 縺檎ｩｺ縺ｮ繧｢繝励Μ縺ｯ縲・壼ｸｸ繧｢繝励Μ縺ｨ縺励※蟄伜惠縺励≧繧具ｼ医せ繝壹・繧ｹ荳隕ｧ縺ｮ謗ｨ螳壹↓縺ｯ菴ｿ縺医↑縺・ｼ峨・

## 豕ｨ諢擾ｼ磯°逕ｨ・・

- 譖ｸ縺崎ｾｼ縺ｿ邉ｻ縺ｯ蠢・★ `--dry-run` 繧呈里螳壹↓縺励～--apply` 縺ｧ縺ｮ縺ｿ螳溯｡後☆繧・
- 譛ｬ逡ｪ隱､譖ｴ譁ｰ繧帝∩縺代ｋ縺溘ａ縲∝ｿ・ｦ√↓蠢懊§縺ｦ 窶徭andbox逕ｨ繧｢繝励Μ窶・繧堤畑諢上＠縺ｦ preflight 繧定ｨｭ險医☆繧具ｼ医ヵ繧ｩ繝ｼ繝蟾ｮ蛻・′縺ゅｋ縺ｨ蜊倡ｴ斐さ繝斐・縺ｧ縺ｯ謌千ｫ九＠縺ｪ縺・ｼ・



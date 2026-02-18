---
last_reviewed: 2026-02-18
review_source: knowledge_refresh_weekly
---
# MF繧ｯ繝ｩ繧ｦ繝我ｼ夊ｨ・CSV螂醍ｴ・ｻ墓ｧ假ｼ亥・譫仙燕繝√ぉ繝・け・・
逶ｮ逧・
- 繝槭ロ繝ｼ繝輔か繝ｯ繝ｼ繝・繧ｯ繝ｩ繧ｦ繝我ｼ夊ｨ医°繧牙叙蠕励☆繧気SV繧偵∝・迴ｾ蜿ｯ閭ｽ縺ｪ謇矩・〒蛻・梵蜿ｯ閭ｽ迥ｶ諷九↓縺吶ｋ
- 縲梧枚蟄励さ繝ｼ繝蛾＆縺・阪悟・谺謳阪阪梧悄髢薙★繧後阪ｒ莠句燕縺ｫ讀懷・縺励∝ｾ梧ｮｵ蜃ｦ逅・・螟ｱ謨励ｒ貂帙ｉ縺・
驕ｩ逕ｨ遽・峇:
- 荳ｻ縺ｫ縲御ｻ戊ｨｳ蟶ｳ縺ｮCSV繧ｨ繧ｯ繧ｹ繝昴・繝医阪ｒ蟇ｾ雎｡縺ｫ縺励◆讓呎ｺ門･醍ｴ・- 縺昴・縺ｻ縺九・蟶ｳ逾ｨCSV縺ｯ縲∝・螳夂ｾｩ繧貞ｷｮ縺玲崛縺医※蜷後§讀懆ｨｼ繝ｭ繧ｸ繝・け繧剃ｽｿ縺・
譛邨ら｢ｺ隱肴律:
- 2026-02-17・医％縺ｮ譌･莉俶凾轤ｹ縺ｧ蜈ｬ蠑上ラ繧ｭ繝･繝｡繝ｳ繝医ｒ遒ｺ隱搾ｼ・
## 1. 蜿門ｾ玲焔鬆・ｼ磯°逕ｨ・・
1. MF繧ｯ繝ｩ繧ｦ繝我ｼ夊ｨ育判髱｢縺ｧ蟇ｾ雎｡譛滄俣繧呈欠螳壹＠縲，SV繧偵ム繧ｦ繝ｳ繝ｭ繝ｼ繝峨☆繧・2. 繝繧ｦ繝ｳ繝ｭ繝ｼ繝臥峩蠕後↓ `skills/mf-accounting-csv-export/scripts/run.py` 縺ｧ讀懆ｨｼ縺吶ｋ
3. 讀懆ｨｼOK縺ｮCSV縺ｮ縺ｿ蛻・梵蜃ｦ逅・∈貂｡縺・
陬懆ｶｳ:
- 繝ｭ繧ｰ繧､繝ｳ/繝繧ｦ繝ｳ繝ｭ繝ｼ繝画桃菴懊・UI螟画峩縺ｮ蠖ｱ髻ｿ縺悟､ｧ縺阪＞縺溘ａ縲√∪縺壹・謇句虚驕狗畑繧呈ｭ｣縺ｨ縺吶ｋ
- 閾ｪ蜍募喧縺吶ｋ蝣ｴ蜷医ｂ縲，SV讀懆ｨｼ繧ｹ繝・ャ繝励・蠢・★谿九☆

Playwright蜊願・蜍包ｼ井ｻｻ諢擾ｼ・
- 繝ｭ繧ｰ繧､繝ｳ迥ｶ諷九ｒ `AX_HOME/sessions/mf-accounting.storage.json` 縺ｫ菫晏ｭ倥＠縲～run.py --mode download` 縺ｧCSV繝繧ｦ繝ｳ繝ｭ繝ｼ繝峨ｒ蠕・ｩ溘☆繧・- 萓・
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 playwright login --name mf-accounting --url "https://biz.moneyforward.com/"`
  - `python skills/mf-accounting-csv-export/scripts/run.py --mode download --download-url "https://biz.moneyforward.com/" --apply`

## 2. 譁・ｭ励さ繝ｼ繝牙･醍ｴ・
螂醍ｴ・
- 蜿鈴呂SV縺ｮ譁・ｭ励さ繝ｼ繝峨・ `auto` 縺ｧ蛻､螳夲ｼ・utf-8-sig` / `utf-8` / `cp932` / `shift_jis`・・- 蛻・梵蜈･蜉帙・UTF-8縺ｫ豁｣隕丞喧縺励※菫晄戟縺吶ｋ・亥次譛ｬ縺ｯ菫晄戟・・
蜈ｬ蠑乗ｹ諡:
- 繧ｯ繝ｩ繧ｦ繝我ｼ夊ｨ・lus縺ｮ蟶ｳ逾ｨ險ｭ螳壹・繝ｫ繝励↓縲，SV譁・ｭ励さ繝ｼ繝峨・騾壼ｸｸ險ｭ螳壹→縺励※ Windows=`Shift-JIS` / Mac=`UTF-8` 縺ｮ險倩ｼ峨≠繧奇ｼ域峩譁ｰ譌･ 2025-12-22・・  - https://biz.moneyforward.com/support/ac-plus/guide/output/report-setting.html
- CSV蜃ｺ蜉帛・螳ｹ縺ｮ螟画峩蜻顔衍縺ｮ螳滉ｾ具ｼ井ｻ墓ｧ伜､画峩縺瑚ｵｷ縺薙ｊ蠕励ｋ縺薙→縺ｮ譬ｹ諡・・  - https://biz.moneyforward.com/support/ac-plus/news/20240307.html

## 3. 莉戊ｨｳ蟶ｳCSV縺ｮ蛻怜･醍ｴ・ｼ域ｨ呎ｺ厄ｼ・
蟄伜惠蠢・亥・・域里螳夲ｼ・
- `蜿門ｼ逼o`
- `蜿門ｼ墓律`
- `蜍伜ｮ夂ｧ醍岼`
- `陬懷勧遘醍岼`
- `驛ｨ髢`
- `蜿門ｼ募・`
- `遞主玄蛻・
- `繧､繝ｳ繝懊う繧ｹ`
- `驥鷹｡・蜀・`
- `鞫倩ｦ～
- `繧ｿ繧ｰ`
- `繝｡繝｢`

蛟､蠢・茨ｼ育ｩｺ蛟､NG・牙・・域里螳夲ｼ・
- `蜿門ｼ逼o`
- `蜿門ｼ墓律`
- `驥鷹｡・蜀・`

蜈ｬ蠑乗ｹ諡:
- 莉戊ｨｳ蟶ｳ逕ｻ髱｢繝倥Ν繝励↓荳願ｨ伜・讒区・・・SV蠖｢蠑擾ｼ峨′險倩ｼ会ｼ域峩譁ｰ譌･ 2026-01-28・・  - https://biz.moneyforward.com/support/account/guide/books2/bo01.html

## 3.1 蟶ｳ逾ｨ繝励Μ繧ｻ繝・ヨ・亥ｮ溯｣・ｸ医∩・・
`run.py --preset` 縺ｧ莉･荳九ｒ驕ｸ謚槭〒縺阪ｋ縲・
- `journal_standard`
  - 蟇ｾ雎｡: 繧ｯ繝ｩ繧ｦ繝我ｼ夊ｨ・莉戊ｨｳ蟶ｳ・亥腰蠑城≡鬘榊・・・  - 譬ｹ諡: https://biz.moneyforward.com/support/account/guide/books2/bo01.html
- `journal_plus`
  - 蟇ｾ雎｡: 繧ｯ繝ｩ繧ｦ繝我ｼ夊ｨ・lus 莉戊ｨｳ蟶ｳ・亥滓婿/雋ｸ譁ｹ蛻暦ｼ・  - 譬ｹ諡: https://biz.moneyforward.com/support/ac-plus/news/20230331.html
- `general_ledger_plus`
  - 蟇ｾ雎｡: 繧ｯ繝ｩ繧ｦ繝我ｼ夊ｨ・lus 邱丞鋸螳壼・蟶ｳ / 陬懷勧蜈・ｸｳ / 迴ｾ驥大・邏榊ｸｳ
  - 譬ｹ諡: https://biz.moneyforward.com/support/ac-plus/news/20230331.html
- `trial_balance_plus_core`
  - 蟇ｾ雎｡: 繧ｯ繝ｩ繧ｦ繝我ｼ夊ｨ・lus 谿矩ｫ倩ｩｦ邂苓｡ｨ・医さ繧｢蛻暦ｼ・  - 譬ｹ諡: https://biz.moneyforward.com/support/ac-plus/news/20240307.html
- `transition_plus_core`
  - 蟇ｾ雎｡: 繧ｯ繝ｩ繧ｦ繝我ｼ夊ｨ・lus 謗ｨ遘ｻ陦ｨ・医さ繧｢蛻暦ｼ・  - 譬ｹ諡: https://biz.moneyforward.com/support/ac-plus/news/20240307.html

豕ｨ諢・
- `trial_balance_plus_core` / `transition_plus_core` 縺ｯ縲∫判髱｢險ｭ螳壼ｷｮ蛻・↓蠖ｱ髻ｿ縺輔ｌ縺ｫ縺上＞繧ｳ繧｢蛻暦ｼ亥鋸螳夂ｧ醍岼繧ｳ繝ｼ繝・蜷咲ｧｰ縲∬｣懷勧遘醍岼繧ｳ繝ｼ繝・蜷咲ｧｰ・峨ｒ蠢・亥喧縺吶ｋ縲・- 驥鷹｡榊・繧・怦谺｡蛻励・驕狗畑蛛ｴ縺ｧ `--required-column` / `--amount-column` 繧定ｿｽ蜉縺励※蜴ｳ譬ｼ蛹悶☆繧九・
## 4. 譌･莉俶紛蜷亥･醍ｴ・
螂醍ｴ・
- 譌･莉俶､懆ｨｼ蛻励・譌｢螳壹〒 `蜿門ｼ墓律`
- 險ｱ螳ｹ繝輔か繝ｼ繝槭ャ繝医・ `YYYY-MM-DD` / `YYYY/MM/DD` / `YYYYMMDD` / `YYYY蟷ｴMM譛・D譌･`・域凾蛻ｻ莉倥″繧りｨｱ螳ｹ・・- 蠢・ｦ√↓蠢懊§縺ｦ `min_date` / `max_date` 繧呈欠螳壹＠縲∫ｯ・峇螟冶｡後ｒ讀懷・縺吶ｋ

諢丞峙:
- 譛域ｬ｡蛻・梵縺ｧ縲悟ｯｾ雎｡螟匁悄髢薙・豺ｷ蜈･縲阪ｒ髦ｲ縺・
## 5. 驥鷹｡肴紛蜷亥･醍ｴ・
螂醍ｴ・
- 讀懆ｨｼ蛻励・譌｢螳壹〒 `驥鷹｡・蜀・`
- 謨ｰ蛟､蛻､螳壹・繧ｫ繝ｳ繝槫玄蛻・ｊ縲～蜀・縲∵峡蠑ｧ雋謨ｰ・・(1234)`・峨ｒ險ｱ螳ｹ
- 謨ｰ蛟､蛹悶〒縺阪↑縺・､縺ｯ荳肴ｭ｣縺ｨ縺励※讀懷・縺吶ｋ

## 6. 螟ｱ謨玲凾縺ｮ謇ｱ縺・
莉･荳九・縺・★繧後°繧呈ｺ縺溘＠縺溷ｴ蜷医・讀懆ｨｼNG:
- 蠢・亥・縺御ｸ崎ｶｳ
- 蛟､蠢・亥・縺ｫ遨ｺ蛟､縺ゅｊ
- 譌･莉伜ｽ｢蠑丈ｸ肴ｭ｣
- 譌･莉倡ｯ・峇螟・- 驥鷹｡榊・縺ｮ謨ｰ蛟､荳肴ｭ｣

驕狗畑:
- NG譎ゅ・蠕梧ｮｵ縺ｮ蛻・梵蜃ｦ逅・↓騾ｲ繧√↑縺・- JSON蜃ｺ蜉帙・ `validation.violations` 繧帝°逕ｨ繝ｭ繧ｰ縺ｫ谿九☆

## 7. 螳溯｣・・繝・ヴ繝ｳ繧ｰ

螳溯｣・
- `skills/mf-accounting-csv-export/scripts/run.py`

荳ｻ縺ｪ蠑墓焚:
- `--list-presets` / `--preset`
- `--required-column` / `--non-empty-column`
- `--date-column` / `--min-date` / `--max-date`
- `--amount-column`・郁､・焚謖・ｮ壼庄・・- `--mode validate|watch|download`
- `--download-url` / `--session-name` / `--storage-state`
- `--dry-run` / `--apply`

蜃ｺ蜉・
- 讓呎ｺ門・蜉・ `status/data/error` 縺ｮJSON
- `--apply` 譎・ UTF-8豁｣隕丞喧CSV縺ｨ讀懆ｨｼ繝ｬ繝昴・繝・SON・域里螳・`AX_HOME/reports/mf_accounting_csv/`・・
## 8. 譖ｴ譁ｰ繝ｫ繝ｼ繝ｫ

1. 蜈ｬ蠑上・繝ｫ繝玲峩譁ｰ・亥・螳夂ｾｩ繝ｻ譁・ｭ励さ繝ｼ繝我ｻ墓ｧ假ｼ峨ｒ讀懃衍縺励◆繧画悽譖ｸ繧呈峩譁ｰ
2. 譖ｴ譁ｰ譎ゅ・縲檎｢ｺ隱肴律縲阪→蜿ら・URL繧貞ｿ・★譏手ｨ・3. 螟画峩蠕後↓繧ｵ繝ｳ繝励ΝCSV縺ｧ `run.py` 縺ｮ讀懆ｨｼ邨先棡繧堤｢ｺ隱・

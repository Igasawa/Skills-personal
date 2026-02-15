# 蜈ｬ蠑上・繝九Η繧｢繝ｫ逶｣譟ｻ繝√ぉ繝・け繝ｪ繧ｹ繝茨ｼ磯°逕ｨ迚茨ｼ・
譖ｴ譁ｰ譌･: 2026-02-15
驕ｩ逕ｨ遽・峇:
- skills/mfcloud-expense-receipt-reconcile

## 1. 逶｣譟ｻ縺ｮ逶ｮ逧・- 蜈ｬ蠑城°逕ｨ莉墓ｧ假ｼ・mazon/Rakuten/MF・峨→螳溯｣・ｼ・o_receipt/payment蛻､螳夲ｼ峨ｒ譌･縲・酔譛溘＠縲・  蜿悶ｊ縺薙⊂縺励ｄ隱､螟画鋤繧呈ｸ帙ｉ縺吶・- 螟画峩轤ｹ繧・`references/official_manual_knowledge.yaml` 縺ｨ `references/official_manual_alignment_notes.md` 縺ｫ蜿肴丐縺励∝・迴ｾ諤ｧ縺ｮ縺ゅｋ驕狗畑縺ｫ縺吶ｋ縲・
## 2. 騾ｱ谺｡繝√ぉ繝・け・・蛻・〒螳滓命・・- [ ] 荳ｻ隕ゞRL縺ｮ蛻ｰ驕皮｢ｺ隱搾ｼ・03/503蜷ｫ繧・・  - Amazon HelpNode(201894740)
  - Amazon 豕ｨ譁・ｱ･豁ｴ
  - 讌ｽ螟ｩFAQ `000006734`
  - 讌ｽ螟ｩBooks 繧ｹ繝・・繧ｿ繧ｹ
  - MF AP/蛟倶ｺｺ迚医ぎ繧､繝峨・蟇ｾ雎｡繝ｪ繝ｳ繧ｯ
- [ ] `official_manual_knowledge.yaml` 縺ｮ `last_reviewed` 縺ｨ蟾ｮ蛻・Ο繧ｰ譖ｴ譁ｰ譌･縺悟商縺吶℃縺ｪ縺・％縺ｨ繧堤｢ｺ隱・- [ ] `official_manual_alignment_notes.md` 縺ｮ縲梧峩譁ｰ譌･縲阪そ繧ｯ繧ｷ繝ｧ繝ｳ縺梧怙譁ｰ縺狗｢ｺ隱・
## 3. 譛域ｬ｡繝√ぉ繝・け・域悽逡ｪ螳溯｡悟燕・・- [ ] `payment_method` 蛻､螳壹し繝ｳ繝励Ν繧定ｿｽ蜉縺ｾ縺溘・隕狗峩縺・  - Amazon: 莉｣蠑輔″邉ｻ・井ｻ｣蠑輔″/莉｣驥大ｼ墓鋤/COD邉ｻ・・  - 讌ｽ螟ｩ: 莉｣蠑輔″繝ｻkobo繝ｻ繝・ず繧ｿ繝ｫ髢｢騾｣繝ｻ驫陦・繧ｫ繝ｼ繝我ｻ･螟悶・萓句､・- [ ] `status=no_receipt` 縺ｨ `error_reason=no_receipt_payment_method` 縺後～include=false` 縺ｸ豬√ｌ縺ｦ縺・ｋ縺薙→繧堤｢ｺ隱・- [ ] `document_type` 縺ｮ `invoice` / `receipt` 縺梧怙譁ｰ繝ｫ繝ｼ繝ｫ縺ｫ荳閾ｴ縺励※縺・ｋ縺狗｢ｺ隱・  - 迚ｹ縺ｫ讌ｽ螟ｩ縺ｮ `classifyRakutenReceiptDocumentType` 邉ｻ
- [ ] 逡ｰ蟶ｸ邇・屮隕・ no_receipt莉ｶ謨ｰ/隧ｲ蠖捺怦蜿冶ｾｼ莉ｶ謨ｰ縺ｮ豈皮紫縺碁明蛟､蜀・°

## 4. 蜈ｬ蠑丞､画峩譎ゅ・蟇ｾ蠢懈焔鬆・1. URL縺ｮ譛ｬ譁・莉墓ｧ伜､画峩蟾ｮ蛻・ｒ遒ｺ隱・2. `references/official_manual_knowledge.yaml` 縺ｮ `scope` 縺ｸ蜿肴丐
3. `references/official_manual_alignment_notes.md` 縺ｫ譖ｴ譁ｰ螻･豁ｴ繧定ｿｽ險・4. 繝・せ繝医・隧ｲ蠖薙す繝翫Μ繧ｪ・・test_amazon_download_logic.py`, `test_rakuten_download_logic.py`・峨ｒ譖ｴ譁ｰ
5. 蠖ｱ髻ｿ遽・峇縺ｫ蠢懊§縺ｦ螳溯｡・ `python -m pytest <target tests>`
6. 螳滓命邨先棡縺ｯ `references/official_manual_review_log_template.md` 繧偵・繝ｼ繧ｹ縺ｫ繝ｭ繧ｰ蛹悶☆繧・7. 逶｣譟ｻ螳溯｡・ `python scripts/review_official_manual.py --review-type weekly`・・owerShell 蛻ｩ逕ｨ譎ゅ・ `.\scripts\review_official_manual.ps1`・・
## 4.a. knowledge_alignmentの照合・対処
- [ ] review_official_manual.py 実行後、`knowledge_alignment.in_sync` が `False` の場合は、まず `status_check` 単位の差分を確認。
- [ ] 不足 URL が出た場合
  - `references/official_manual_knowledge.yaml` の `official_sources[*].url` 追加対象かを確認
  - `review_official_manual.py` の `CHECK_TARGETS` 追加対象かを確認
- [ ] 過剰 URL が出た場合
  - `references/official_manual_knowledge.yaml` または `CHECK_TARGETS` から削除候補を確認
- [ ] 該当ステータスカテゴリ（`manual`/`internal_scraping_target`）の差分を解消後、再実行して `in_sync=true` を確認

## 5. 繝医Λ繝悶Ν譎ゅ・蛻・ｊ蛻・￠鬆・- `status=no_receipt` 縺梧･蠅・  1. `payment_method` 縺ｮ謚ｽ蜃ｺ邊ｾ蠎ｦ菴惹ｸ九°遒ｺ隱搾ｼ域眠隕剰｡ｨ險倥・譛臥┌・・  2. Amazon / 讌ｽ螟ｩ縺ｮ莉墓ｧ伜ｷｮ蛻・ｒ蜈ｬ蠑丞盾辣ｧ縺ｧ蜀咲｢ｺ隱・  3. 縺ｾ縺壹・ `references/official_manual_knowledge.yaml` 縺ｮ `key_rules.signals` / `exclude_signals` 譖ｴ譁ｰ
- `error_reason` 縺・`auth_required` 繧・`document_validation_failed` 縺ｫ蛛上ｋ蝣ｴ蜷・  1. 逕ｻ髱｢UI螟画峩/隱崎ｨｼ迥ｶ諷具ｼ・torage_state・峨ｒ遒ｺ隱・  2. debug/html蜃ｺ蜉帙→繧ｹ繧ｯ繧ｷ繝ｧ縺ｧ逕ｻ髱｢蟾ｮ蛻・｢ｺ隱・
## 6. 蜿ら・繧ｨ繝ｳ繝医Μ
- `references/official_manual_knowledge.yaml`
- `references/official_manual_alignment_notes.md`
- `skills/mfcloud-expense-receipt-reconcile/scripts/amazon_download.mjs`
- `skills/mfcloud-expense-receipt-reconcile/scripts/rakuten_download.mjs`


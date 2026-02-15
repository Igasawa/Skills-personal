# 公式マニュアル監査チェックリスト（運用版）

更新日: 2026-02-15
適用範囲:
- skills/mfcloud-expense-receipt-reconcile

## 1. 監査の目的
- 公式運用仕様（Amazon/Rakuten/MF）と実装（no_receipt/payment判定）を日々同期し、
  取りこぼしや誤変換を減らす。
- 変更点を `references/official_manual_knowledge.yaml` と `references/official_manual_alignment_notes.md` に反映し、再現性のある運用にする。

## 2. 週次チェック（5分で実施）
- [ ] 主要URLの到達確認（403/503含む）
  - Amazon HelpNode(201894740)
  - Amazon 注文履歴
  - 楽天FAQ `000006734`
  - 楽天Books ステータス
  - MF AP/個人版ガイドの対象リンク
- [ ] `official_manual_knowledge.yaml` の `last_reviewed` と差分ログ更新日が古すぎないことを確認
- [ ] `official_manual_alignment_notes.md` の「更新日」セクションが最新か確認

## 3. 月次チェック（本番実行前）
- [ ] `payment_method` 判定サンプルを追加または見直す
  - Amazon: 代引き系（代引き/代金引換/COD系）
  - 楽天: 代引き・kobo・デジタル関連・銀行/カード以外の例外
- [ ] `status=no_receipt` と `error_reason=no_receipt_payment_method` が、`include=false` へ流れていることを確認
- [ ] `document_type` の `invoice` / `receipt` が最新ルールに一致しているか確認
  - 特に楽天の `classifyRakutenReceiptDocumentType` 系
- [ ] 異常率監視: no_receipt件数/該当月取込件数の比率が閾値内か

## 4. 公式変更時の対応手順
1. URLの本文/仕様変更差分を確認
2. `references/official_manual_knowledge.yaml` の `scope` へ反映
3. `references/official_manual_alignment_notes.md` に更新履歴を追記
4. テストの該当シナリオ（`test_amazon_download_logic.py`, `test_rakuten_download_logic.py`）を更新
5. 影響範囲に応じて実行: `python -m pytest <target tests>`
6. 実施結果は `references/official_manual_review_log_template.md` をベースにログ化する

## 5. トラブル時の切り分け順
- `status=no_receipt` が急増
  1. `payment_method` の抽出精度低下か確認（新規表記の有無）
  2. Amazon / 楽天の仕様差分を公式参照で再確認
  3. まずは `references/official_manual_knowledge.yaml` の `key_rules.signals` / `exclude_signals` 更新
- `error_reason` が `auth_required` や `document_validation_failed` に偏る場合
  1. 画面UI変更/認証状態（storage_state）を確認
  2. debug/html出力とスクショで画面差分確認

## 6. 参照エントリ
- `references/official_manual_knowledge.yaml`
- `references/official_manual_alignment_notes.md`
- `skills/mfcloud-expense-receipt-reconcile/scripts/amazon_download.mjs`
- `skills/mfcloud-expense-receipt-reconcile/scripts/rakuten_download.mjs`

# 公式マニュアル監査ログ（テンプレート）

更新日: 2026-02-15
対象: mfcloud-expense-receipt-reconcile

## 1. 基本情報
- 実施日: YYYY-MM-DD
- 種別: `weekly_precheck` / `monthly_full_review` / `change_response`
- 実施者:
- 担当:

## 2. 監査対象の到達確認
- [ ] Amazon HelpNode (nodeId=201894740)
- [ ] Amazon 注文履歴
- [ ] 楽天FAQ `000006734`
- [ ] 楽天Books 配送/領収書画面
- [ ] MF AP/個人版ガイド

## 3. 公式差分確認
- 公式ページの見出し/文言変更（Yes/No）
- 変更要約（URLごと）
- `references/official_manual_knowledge.yaml` 更新有無（Yes/No）
- `references/official_manual_alignment_notes.md` 更新有無（Yes/No）

## 4. ルール差分の影響確認
- 追加/変更した `signal`:
- 追加/除外した `signal`:
- `payment_method` 境界条件追加（COD/代引き・電子マネーなど）
- `document_type` 判定変更（invoice/receipt）
- 閾値異常の有無（no_receipt比率）

## 5. テスト
- 変更対象テスト:
- 実行コマンド:
- 結果:

## 6. 監査結果
- 異常なし: Yes / No
- 課題:
- 次アクション:
- 優先度: P0 / P1 / P2
- 完了予定日:

## 7. 記録
- `official_manual_knowledge.yaml` 更新日:
- `official_manual_alignment_notes.md` 更新日:
- 監査ログ保存先（`reports/...`）:
## 8. 最終更新日ルール
- `official_manual_knowledge.yaml` と `official_manual_alignment_notes.md` の `last_reviewed` は以下を許容する。
  - `last_reviewed: YYYY-MM-DD`
  - `last_reviewed = YYYY/MM/DD`
  - `最終更新: YYYY-MM-DD`
  - `最終更新日= YYYY-MM-DD`
  - `最終検証日: YYYY-MM-DD`
- テンプレートの `YYYY-MM-DD` は記入しやすさ優先の標準表記。必要に応じて `/` も許容対象に含まれる。

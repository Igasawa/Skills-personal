# Phase 1 / 1.5 MVPチェックリスト（Amazon/楽天 + MF下書き作成）

このチェックリストは `2026-01` のような対象月ごとに使う。
確定チェックは「自動テストで担保済み」または「現物ファイル確認済み」の項目のみに限定する。

## 1. ダッシュボード基本フロー
- [x] `preflight` が成功し、Step 1以降が解放される
- [ ] Amazonダウンロード実行中に進捗ログが更新される
- [ ] 楽天ダウンロード実行中に進捗ログが更新される
- [x] ダウンロード失敗時はStep状態が「未完了」のまま維持される
- [x] ダウンロード成功時はStep状態が「完了」になる

## 2. Amazon取得品質
- [x] 指定月の対象注文が `amazon/orders.jsonl` に出力される
- [x] 対象注文のPDFが `amazon/pdfs/` に保存される
- [x] `orders.jsonl` の金額が注文概要の請求額と整合する
- [ ] 取得不能注文は理由付きで記録される（黙って欠損しない）

## 3. 楽天取得品質
- [x] 指定月の対象注文が `rakuten/orders.jsonl` に出力される
- [x] 対象注文のPDFが `rakuten/pdfs/` に保存される
- [ ] 楽天ブックスなど領収書非対応ケースが `no_receipt` として処理される
- [x] 失敗トーストが出る場合は `audit_log.jsonl` と `_runs/*.log` で原因追跡できる

## 4. 除外設定と印刷準備
- [x] 除外設定保存で `confirm` が記録される
- [x] 印刷準備で `print_manifest.json` / `print_list.txt` / `print_all.ps1` が生成される
- [x] 印刷準備は自動印刷せず、手動実行コマンドのみ提示される
- [x] 手動印刷完了後に `print_complete` を記録できる

## 5. 消込・提出資料（Step 5）
- [x] `missing_evidence_candidates.csv/json` が生成される
- [x] `monthly_thread.md` が生成される
- [x] `quality_gate.json` の内容を確認できる
- [x] 監査ログ `reports/audit_log.jsonl` が揃う

## 6. 運用安定性
- [x] Stepリセット後に再実行しても整合が崩れない
- [x] ランニング中断時に次回実行へ悪影響を残さない
- [ ] 「保存して印刷準備」の体験で誤表示（成功/失敗）がない

## 7. Phase 1.5（MF下書き作成）
- [ ] Step0（preflight + 連携更新）後に `https://expense.moneyforward.com/outgo_input` へ遷移し、対象月の連携明細が表示される
- [x] 突合済み候補に対して `編集登録` を押下できる
- [ ] 候補PDFを領収書として添付できる
- [x] 添付後、画面中央の `OCR入力` にチェックを入れる
- [x] `作成する` を押して下書き作成まで完了できる（申請はしない）
- [ ] 経費科目など未入力の状態でも下書き作成できることを現物で確認できる
- [ ] 失敗時は `audit_log.jsonl` と `_runs/*.log` で行単位に原因追跡できる

## 8. 完了判定（MVP）
- [ ] 1〜7がすべて満たされる
- [ ] Amazon/楽天の月次処理を同じ手順で再現できる
- [ ] MF提出用の証憑・候補資料と下書き作成を毎月安定して揃えられる


## Update: Bulk Print UX (Source Split)
- [x] Amazon/Rakuten bulk print buttons are separated on the run page.
- [x] Bulk print opens merged PDF only (manual print policy).
- [x] No automatic printer output is triggered by bulk print.


# MFクラウド経費：実装ロードマップ

## 目的
Amazon/楽天 + MF下書き作成のMVPを完了し、同一手順で毎月安定運用できる状態を維持する。

## 現状（完了）
更新日: 2026-02-11
根拠ログ: `references/mvp_checklist.md`（未完了 0件）

完了事項:
- Amazon/楽天の長時間実行ログ（heartbeat）と、取得不能時の理由コード記録を実装済み
- 楽天の領収書非対応ケースを `no_receipt` に正規化済み
- Step0（preflight + MF再取得）で「取得中」表示確認までの導線を安定化済み
- Step5の下書き作成で `reports/mf_draft_create_actions.jsonl` に行単位ログを出力し、`_runs/*.log` とあわせて追跡可能
- Step 4.5（手動取り込み）で `manual/inbox/` 直下ルールを適用し、`manual/orders.jsonl` 連携まで運用可能

## フェーズ構成（ステータス）

### Phase 1（MVP）: Amazon/楽天
ステータス: 完了

完了条件:
1. `orders.jsonl` / `pdfs/` への出力が欠損なく行える
2. `print_manifest.json` / `print_list.txt` / `print_all.ps1` を安定生成できる
3. 印刷は「準備まで自動、最終実行は手動」を維持できる
4. `missing_evidence_candidates.csv/json` を出力できる
5. 月次メモ・監査ログを揃えられる

### Phase 1.5（MVP拡張）: MF下書き作成
ステータス: 完了

完了条件:
1. 突合済み明細から `編集登録` へ遷移できる
2. 領収書PDF添付と `OCR入力` チェックを実行できる
3. `作成する` で下書き作成まで完了できる（申請はしない）
4. 失敗時に `needs_review` を残しつつ処理継続できる
5. `reports/audit_log.jsonl` / `reports/mf_draft_create_actions.jsonl` / `_runs/*.log` で追跡できる

### Phase 2（他サービス自動取得拡張）
ステータス: 今回はスコープ外（実施しない）

補足:
- 他サービス領収書は Step 4.5 の手動取り込みで運用する
- 自動取得拡張が必要になった時点で別ロードマップとして再定義する

## 運用上の固定ルール
- 印刷は常に「手前まで自動」「最終実行は手動」
- 監査可能性維持のため、`reports/audit_log.jsonl` と `reports/mf_draft_create_actions.jsonl` に記録する
- 仕様変更時は本ファイルと `operation_policy.md` を同時更新する

## 実行チェックリスト
- 実行確認は `references/mvp_checklist.md` を利用する

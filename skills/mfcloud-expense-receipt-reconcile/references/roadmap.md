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
- Step 4.5（手動取り込み）で `manual/inbox/` 取り込み運用（直下 + providerサブフォルダ許可）を実装し、`manual/orders.jsonl` 連携まで運用可能

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

## 現在の最優先
- Phase 1 / Phase 1.5 完了後の現行優先は、運用安定化（監査性・月次クローズ品質の維持）とする

## 運用上の固定ルール
- 印刷は常に「手前まで自動」「最終実行は手動」
- 監査可能性維持のため、`reports/audit_log.jsonl` と `reports/mf_draft_create_actions.jsonl` に記録する
- 仕様変更時は本ファイルと `operation_policy.md` を同時更新する

## 実行チェックリスト
- 実行確認は `references/mvp_checklist.md` を利用する

## 短期実行計画（2026-02-20 開始）

対象期間: 2026-02-20 から 2026-03-06 まで

### 優先度A（今すぐ着手）

1. 既定社名の抽象化（期限: 2026-02-23）
- 対象: `skill.yaml` の既定値、`scripts/run_core.py` の既定定数、`README.md` / `SKILL.md` の設定例
- 実施内容: 固有社名のハードコードをプレースホルダー化し、実運用値は `AX_HOME/configs/...json` で与える方針に統一
- 完了条件: 既定値に固有社名が残っていないこと、最小テストが通ること

2. `tenant` 一本化の移行レーン定義（期限: 2026-02-26）
- 対象: 旧設定（`config.receipt_name` / `config.urls.*`）の互換読み込み箇所
- 実施内容: 旧キー利用時に非推奨警告を出し、廃止予定日を明記した移行手順をドキュメント化
- 完了条件: 移行手順の文書化、警告出力の追加、既存テストの更新

3. Playwright スモーク定期実行の PoC（期限: 2026-03-01）
- 対象: `scripts/playwright_smoke_workflow.ps1` と GitHub Actions
- 実施内容: self-hosted runner 前提で週次スケジュール実行を追加し、結果レポートを artifact 化
- 完了条件: 少なくとも1回の定期実行成功ログを確認し、失敗時の運用手順を追記

### 優先度B（A完了後すぐ）

1. OS運用方針の明確化（期限: 2026-03-04）
- 実施内容: 「Windows優先運用」か「クロスプラットフォーム対応」かを明文化し、README のコマンド例を方針に合わせて統一
- 完了条件: README/SKILL の実行例と運用方針が矛盾していないこと

2. コミットガード運用の一本化判断（期限: 2026-03-06）
- 実施内容: 現行（`.githooks` / `.husky` / `safe_commit_push.ps1`）継続か、`pre-commit` 導入かを決定
- 完了条件: 採用案をドキュメント化し、不要な二重運用を残さないこと

### 進捗メモ（2026-02-20）

- A-1 既定社名の抽象化: 実装完了
  - `run_core.py` / `skill.yaml` / `README.md` / `SKILL.md` の既定社名を `YOUR_COMPANY_NAME` 系プレースホルダーへ統一
- A-2 tenant一本化の移行レーン定義: 実装完了
  - 旧キーが実際に採用された場合のみ、CLIで非推奨警告を表示
  - 非推奨開始日（2026-02-20）と廃止目標日（2026-06-30）をドキュメントへ明記
- A-3 Playwrightスモーク定期実行 PoC: 実装完了（定期実行ログ確認待ち）
  - `.github/workflows/workflow-smoke-self-hosted.yml` を追加
  - 成果物artifact化と停止処理を含む最小運用フローを定義

# MFクラウド経費：実装ロードマップ

## 目的
Amazon/楽天の領収書処理をまずMVPとして完成させ、その後に他サービス領収書の自動取得を同じ運用方針で拡張する。

## 現状（ログ反映）
更新日: 2026-02-11
根拠ログ: `references/mvp_checklist.md`（未完了 14件）

Phase 1（Amazon/楽天）で残っていること:
- （完了）長時間実行でも状態が追える進捗ログ（heartbeat）を出す（Amazon/楽天）
- （完了）取得不能注文を「理由コード + 詳細」で記録する（Amazon/楽天）
- （完了）楽天ブックス等の領収書非対応を `no_receipt` として正規化する

Phase 1.5（MF下書き作成）で残っていること:
- Step0（preflight + 連携更新）で「取得中」表示が出ればOK（`outgo_input` の表示確認は必須ではない）
- 候補PDFの領収書添付が安定して完了すること（現物確認）
- 経費科目など未入力の状態でも下書き作成できること（現物確認）
- 失敗時に `reports/mf_draft_create_actions.jsonl` と `_runs/*.log`（および debug snapshot）で「行単位」に原因追跡できること

運用（Step 4.5 手動取り込み）で残っていること:
- `manual/inbox/` 直下配置ルールの運用徹底（サブフォルダ禁止）
- 「4サービス一括取り込み」で `manual/orders.jsonl` に反映され、Step5で突合対象になること

## フェーズ構成

### Phase 1（MVP）: Amazon/楽天を完遂
対象:
- Amazon
- 楽天

到達目標:
- 指定対象月・指定範囲の領収書を漏れなく取得する
- PDFとして保存する
- 印刷は「手前まで自動（印刷準備）」で統一し、最終実行は手動にする
- MFの消込対象を抽出し、添付に進める資料を出力する

MVP完了条件（Done）:
1. 対象月のAmazon/楽天注文について、取得対象の領収書が欠損なく `orders.jsonl` と `pdfs/` に反映される
2. 除外設定保存後に `print_manifest.json` / `print_list.txt` / `print_all.ps1` が安定生成される
3. 自動印刷は行わず、手動印刷完了を記録できる
4. 消込候補（未添付候補）が `missing_evidence_candidates.csv/json` に出力される
5. MF添付作業に必要な資料（候補一覧、監査ログ、月次メモ）が揃う

MVPでの非対象:
- Amazon/楽天以外のサービス領収書自動取得
- MFへの最終申請ボタン押下の自動化

### Phase 1.5（MVP拡張）: MF下書き作成まで自動化
対象:
- `https://expense.moneyforward.com/outgo_input`（連携サービスから登録）

前提:
- Step0で連携更新が完了しており、対象月の連携明細が `outgo_input` に表示されている

到達目標:
- Step5で突合候補から該当明細を特定する
- `編集登録` から経費登録モーダルを開く
- 候補PDFを領収書添付する
- 添付後に `OCR入力` をオンにする
- `作成する` で下書きを作成する（申請はしない）

Phase 1.5完了条件（Done）:
1. 突合済み明細に対して `編集登録` まで自動で遷移できる
2. 領収書PDF添付と `OCR入力` チェックが安定して実行される
3. `作成する` 押下で下書き作成が完了する
4. 失敗時は対象明細を `needs_review` として残し、処理全体は継続できる
5. すべての操作結果を `reports/audit_log.jsonl` と実行ログで追跡できる

### Phase 2: 他サービス領収書の自動取得拡張
対象候補:
- Aqua Voice
- ChatGPT
- Claude
- Replit

方針:
- Amazon/楽天で確立した共通フローを流用する
- 印刷ポリシーは共通で「印刷準備まで自動、最終印刷は手動」
- 新規ソースはアダプタ方式で追加し、ダッシュボードの操作体験を統一する

Phase 2完了条件（各ソース共通）:
1. 指定期間の請求/領収書を取得できる
2. PDF保存とメタデータ（発生日、金額、取引ID、取得元URL）を出力できる
3. 除外設定・印刷準備・完了記録のフローに統合できる
4. 消込候補抽出に取り込める

## 実装優先順位
1. 「保存して印刷準備」体験で誤表示（成功/失敗）が出ないことを保証する（運用安定性）
2. Phase 1（Amazon/楽天）のMVP受け入れテスト整備（チェックリストの自動化/現物確認手順の固定）
3. Phase 1.5（MF下書き作成）: 領収書添付の安定化と、失敗時の行単位ログ追跡（`reports/mf_draft_create_actions.jsonl` + `_runs/*.log`）
4. Step 4.5（手動取り込み）: `manual/orders.jsonl` 反映とStep5突合までの導線を受け入れ条件として固定
5. Phase 2の共通アダプタ仕様策定
6. Aqua Voice -> ChatGPT -> Claude -> Replit の順で実装

## 運用上の固定ルール
- 印刷は常に「手前まで自動」「最終実行は手動」
- 監査可能性を維持するため、各アクションを `reports/audit_log.jsonl`（ダッシュボード操作）と `reports/mf_draft_create_actions.jsonl`（MF下書き作成）に記録する
- 仕様変更時は本ファイルと `operation_policy.md` の両方を更新する

## 実行チェックリスト
- Phase 1 / 1.5の実行確認は `references/mvp_checklist.md` を利用する

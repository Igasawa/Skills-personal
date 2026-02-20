# Phase 3 計画: 外部イベント実行（`trigger_kind=external_event`）

最終更新: 2026-02-20  
前提: MVPスケルトンを維持しつつ、段階導入で安全性と運用性を上げる。

## 1. ゴール
- 外部イベント（Webhook/連携イベント）で先頭手順を安全に起動できる。
- 重複イベントを抑止し、失敗時も再送・追跡ができる。
- UI/API/監査ログで「起動された理由」と「起動されなかった理由」を説明できる。

## 2. 現状（2026-02-20）
- `/api/workflow-events` は実装済み。
- `external_event` の先頭手順テンプレートを解決し、`idempotency_key` で重複抑止する。
- `reports/audit_log.jsonl` へ `event_type=workflow_event` を記録する。
- Phase 3.1 の契約固定として `references/workflow_external_event_contract.md` を追加済み。
- Phase 3.1 の異常系テスト（未対応アクション/invalid ym/event_name解決/Bearer token）を追加済み。
- Phase 3.2 の先行実装として、受信レシートTTL/件数上限クリーンアップを追加済み。
- Phase 3.2 の先行実装として、`workflow_event` 監査に `reason_class`/`reason_code` を追加済み。
- Phase 3.2 の運用文書として `references/workflow_external_event_runbook.md` を追加済み。
- Phase 3.2 の可視化基盤として `GET /api/workflow-events/summary` を追加済み。
- Phase 3.2 の可視化UIとして、`/expense-workflow-copy` に監査サマリーカードを追加済み。
- Phase 3.3 先行として、監査 `details` に `retry_advice` を追加済み。

## 3. 段階導入

### Phase 3.1（契約固定）
- スコープ:
  - `workflow-events` リクエスト契約（必須/任意/デフォルト）を文書化。
  - テンプレート解決ルール（`template_id` 優先、fallback禁止条件）を固定。
  - `idempotency_key` の最大長・許可文字・衝突時レスポンスを固定。
- 完了条件:
  - 契約ドキュメント + APIテストで「期待/拒否」を再現可能。

### Phase 3.2（保護強化）
- スコープ:
  - トークン検証（`X-Workflow-Event-Token` / `Authorization`）運用を標準化。
  - 受信レシートに TTL/件数上限を導入し、肥大化を防止。
  - 不正イベント（不正テンプレート・未対応アクション）の監査項目を拡張。
  - 監査ログの可視化基盤として集計APIを提供する。
- 完了条件:
  - 認証/認可の異常系テストが通る。
  - レシート保守（削除・上限）動作が自動テストで担保される。
  - 集計APIの契約と集計テストが固定される。

### Phase 3.3（運用拡張）
- スコープ:
  - 再送戦略（一時失敗時の再試行 or 呼び出し側再送前提）を明文化。
  - 失敗理由の分類コード化（validation / conflict / infra）と `retry_advice` の整合。
  - 運用ダッシュボード表示用の集計キーを定義。
- 完了条件:
  - 障害時の一次切り分けに必要な情報が `audit_log.jsonl` だけで揃う。

## 4. API契約（MVP固定案）
- エンドポイント: `POST /api/workflow-events`
- 主要入力:
  - `template_id`（推奨）
  - `event_id` または `idempotency_key`（重複抑止キー）
  - `year` / `month`（省略時はテンプレート値を採用）
  - `source` / `event_name` / `mfcloud_url` / `notes`（任意）
- 主要出力:
  - `duplicate=true/false`
  - `triggered=true/false`
  - `run_id`
  - `template_id` / `action_key`

## 5. テスト計画
1. 正常系: `external_event` テンプレートで `triggered=true` + `run_id` 返却。
2. 重複系: 同一 `idempotency_key` 再送で `duplicate=true`。
3. 異常系: 無効トークン / 不正テンプレート / 未対応アクション。
4. 監査: `workflow_event` の success/rejected/failed が `audit_log.jsonl` に記録される。

## 6. リスクと対策
- リスク: 呼び出し側が `idempotency_key` を付与しない。
  - 対策: `event_id` をfallback採用し、欠如時の警告ログを残す。
- リスク: テンプレート更新で起動対象が意図せず変わる。
  - 対策: 受信時に解決テンプレートID/updated_atを監査へ記録。
- リスク: 失敗理由が利用者に伝わらない。
  - 対策: `toFriendlyMessage` 対応キーを増やし、UIトースト文言を統一。

## 7. 直近実装タスク
1. 完了: 受信レシートTTL/上限の運用値をランブックへ反映。
2. 完了: `workflow_event` 監査分類の集計APIと表示要件を定義。
3. 継続: 失敗時の再送・再実行フロー（呼び出し側手順 + 運用ドキュメント）を整備。
4. 次: Phase 3.3 の日次トレンド/通知要件を確定。

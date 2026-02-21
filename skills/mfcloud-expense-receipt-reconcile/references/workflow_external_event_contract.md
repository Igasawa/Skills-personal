# Workflow Events API 契約（Phase 3.1/3.2/3.3）

最終更新: 2026-02-20  
対象: `POST /api/workflow-events`, `GET /api/workflow-events/summary`, `GET /api/workflow-events/retry-jobs`, `POST /api/workflow-events/retry-jobs/drain`, `GET/POST /api/workflow-events/notification-settings`, `POST /api/workflow-events/notification-settings/test`

## 1. 目的
- `trigger_kind=external_event` のテンプレートを、外部イベントで安全に起動する。
- 重複イベントを `idempotency_key` で抑止する。
- 起動結果を `reports/audit_log.jsonl`（`event_type=workflow_event`）へ記録する。

## 2. 認証
- 環境変数 `AX_WORKFLOW_EVENT_TOKEN` が未設定: トークン検証なし。
- `AX_WORKFLOW_EVENT_TOKEN` が設定済み: 一致必須。
- トークン解決順:
  1. クエリ `token`
  2. ヘッダ `x-workflow-event-token`
  3. `Authorization: Bearer <token>`
- 不一致時: `401 Invalid workflow event token.`

## 3. リクエスト契約

### 必須（実質）
- テンプレート解決情報（以下のいずれか）
  - `template_id` / `templateId`
  - `event_name` / `eventName`
  - または external_event テンプレートが1件だけ存在する状態

### 任意
- `idempotency_key` / `idempotencyKey` / `event_id` / `eventId` / `x-idempotency-key`
- `year`, `month`（省略時はテンプレート値へフォールバック）
- `source` / `event_source`
- `event_name` / `eventName`
- `mfcloud_url`
- `notes`

### `idempotency_key` 正規化
- 最大長: 128
- 許可文字: `A-Za-z0-9._:@-`
- 不正形式は無効化（空扱い）

## 4. テンプレート解決ルール
1. `template_id` 指定時
- 該当テンプレートの先頭手順が `external_event` なら採用。
- 該当が存在するが先頭手順が `external_event` でなければ `409`。
- テンプレート自体が存在しなければ `404`。

2. `event_name` 指定時（`template_id` 未指定）
- `external_event` テンプレート群の先頭手順 `action` と一致するものを検索。
- 0件: `404`
- 複数件: `409`
- 1件: 採用。

3. どちらも未指定時
- `external_event` テンプレートが1件なら採用。
- 0件: `404`
- 複数件: `409`

## 5. 実行ルール
- 先頭手順 `action` はMVP対応キーのみ許可。
- 非対応アクションは `409 external_event action is not executable in MVP: ...`。
- `year/month` は以下順で決定:
  1. リクエスト `year/month`
  2. テンプレート `year/month`
- 最終的に `year < 2000` または `month not in 1..12` は `400 Workflow event requires valid year/month.`

## 6. レスポンス契約

### 成功（新規起動）
- `status=ok`
- `duplicate=false`
- `triggered=true`
- `template_id`
- `template_name`
- `action_key`
- `idempotency_key`（解決できた場合）
- `run_id`

### 成功（重複抑止）
- `status=ok`
- `duplicate=true`
- `triggered=false`
- `run_id`（初回実行のID）

## 7. 監査ログ
- 成功起動: `event_type=workflow_event`, `status=success`
- 重複抑止: `event_type=workflow_event`, `status=skipped`（`duplicate=true`）
- 起動拒否/失敗: `status=rejected` または `failed`
- `details` には最低限以下を含める:
  - `template_id`, `template_name`, `event_name`, `source`, `idempotency_key`
- Phase 3.2 追加:
  - `reason_class`（例: `auth` / `validation` / `template_conflict` / `run_conflict` / `unsupported_action` / `infra`）
  - `reason_code`（例: `http_401`, `http_409`, `invalid_year_month`, `duplicate_idempotency_key`）
  - `retry_advice`（`do_not_retry` / `retry_after_fix` / `retry_with_backoff`）
  - `duplicate`（`true/false`）

## 8. 代表エラー
- `400` `Workflow event requires valid year/month.`
- `401` `Invalid workflow event token.`
- `404` `Workflow template not found.`
- `404` `No external_event workflow template was found.`
- `404` `No external_event workflow template matched event_name.`
- `409` `Template step 1 must use trigger_kind=external_event.`
- `409` `Multiple external_event templates found. Specify template_id.`
- `409` `Multiple templates matched event_name. Specify template_id.`
- `409` `external_event action is not executable in MVP: ...`

## 9. レシート保持（Phase 3.2）
- 保存場所: `artifacts/mfcloud-expense-receipt-reconcile/_workflow_events/receipts.json`
- 既定保持件数: `1000`（環境変数 `AX_WORKFLOW_EVENT_MAX_RECEIPTS` で上書き）
- 既定TTL: `90日`（環境変数 `AX_WORKFLOW_EVENT_RECEIPT_TTL_DAYS` で上書き）
- 読み取り時と保存時にクリーンアップ:
  - TTL超過レシートを削除
  - 保持件数超過時は古い順に削除
- `idempotency_key` 付きイベントのみレシート保持対象。

## 10. 集計API契約（Phase 3.2）
- エンドポイント: `GET /api/workflow-events/summary`
- クエリ:
  - `ym`（必須, `YYYY-MM`）
  - `recent_limit`（任意, 既定20, 範囲1..200）
- レスポンス主要項目:
  - `status=ok`
  - `ym`
  - `event_type=workflow_event`
  - `total`
  - `by_status`（`success/skipped/rejected/failed/unknown`）
  - `by_reason_class`（件数降順）
  - `by_reason_code`（件数降順）
  - `by_retry_advice`（件数降順）
  - `retry_queue`（再送キュー件数・due件数・状態別件数）
  - `duplicate`（`true/false/unknown`）
  - `recent`（時刻降順）
  - `receipt_retention`（`ttl_days`, `max_receipts`）

### `recent` 要素
- `at`, `status`, `action`, `run_id`
- `template_id`, `template_name`, `event_name`, `source`
- `idempotency_key`, `reason`, `reason_class`, `reason_code`, `retry_advice`, `duplicate`

## 11. 再送ジョブAPI契約（Phase 3.3）

### キュー保存ルール
- `POST /api/workflow-events` の失敗時に `retry_advice=retry_with_backoff` の場合のみ再送ジョブを作成。
- 安全性のため `idempotency_key` が解決できないイベントは自動再送対象外。
- 保存先: `artifacts/mfcloud-expense-receipt-reconcile/_workflow_events/retry_jobs.json`

### 再送ジョブ一覧
- エンドポイント: `GET /api/workflow-events/retry-jobs`
- クエリ:
  - `limit`（任意, 既定20, 範囲1..200）
- 主要レスポンス:
  - `status=ok`
  - `total`, `due`
  - `by_status`（`pending` / `retrying` / `succeeded` / `discarded` / `escalated`）
  - `jobs`（更新時刻降順）
  - `policy`（`max_attempts`, `base_delay_seconds`, `terminal_ttl_days`, `max_jobs`）

### 再送ジョブ実行
- エンドポイント: `POST /api/workflow-events/retry-jobs/drain`
- リクエスト（任意）:
  - `limit`（既定10, 範囲1..50）
  - `force`（`true` で `next_retry_at` を無視して実行）
- 主要レスポンス:
  - `status=ok`
  - `processed`, `succeeded`, `retrying`, `escalated`, `discarded`
  - `remaining_due`
  - `queue`（実行後スナップショット）

### 再送ポリシー（既定値）
- `AX_WORKFLOW_EVENT_RETRY_MAX_ATTEMPTS=3`
- `AX_WORKFLOW_EVENT_RETRY_BASE_DELAY_SECONDS=30`
- `AX_WORKFLOW_EVENT_RETRY_TERMINAL_TTL_DAYS=30`
- `AX_WORKFLOW_EVENT_RETRY_MAX_JOBS=2000`
- `AX_WORKFLOW_EVENT_RETRY_WORKER_ENABLED=1`
- `AX_WORKFLOW_EVENT_RETRY_WORKER_POLL_SECONDS=30`
- 3回失敗で `escalated` とし、自動再送を停止（手動対応へ移行）。

## 12. 通知設定API契約（Phase 3.3）

### Webhook設定取得
- エンドポイント: `GET /api/workflow-events/notification-settings`
- 返却:
  - `status=ok`
  - `configured`（`true/false`）
  - `webhook_url_masked`（常にマスク済み）
  - `source`（`file` / `env` / `none`）
  - `updated_at`
- 生のWebhook URLは返却しない。

### Webhook設定保存/クリア
- エンドポイント: `POST /api/workflow-events/notification-settings`
- 入力:
  - `webhook_url`（必須、空文字でクリア）
- 検証:
  - `https://chat.googleapis.com/v1/spaces/.../messages?key=...&token=...` の形式のみ許可
- 解決優先順位:
  1. 設定ファイル（`_workflow_events/notification_settings.json`）
  2. 環境変数 `AX_GOOGLE_CHAT_WEBHOOK_URL`
- 返却:
  - `status=ok`
  - `configured`, `webhook_url_masked`, `source`, `updated_at`

### テスト送信
- エンドポイント: `POST /api/workflow-events/notification-settings/test`
- 動作:
  - 現在有効なWebhookへ Google Chat テスト通知を1件送信する。
  - 未設定時は `400`（`Google Chat webhook is not configured.`）。
- 返却:
  - 成功: `status=ok`, `sent=true`, `http_status`, `message`
  - 失敗: `status=error`, `sent=false`, `http_status`, `message`
- 監査:
  - `event_type=workflow_event_notification`
  - `action=notification_settings_test`
  - `status=success/failed/skipped`

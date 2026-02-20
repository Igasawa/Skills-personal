# Workflow Events 運用ランブック（Phase 3.2）

最終更新: 2026-02-20
対象: `POST /api/workflow-events`

## 1. 運用値（確定）

### 推奨デフォルト
- `AX_WORKFLOW_EVENT_RECEIPT_TTL_DAYS=90`
- `AX_WORKFLOW_EVENT_MAX_RECEIPTS=1000`

### 高トラフィック環境の目安
- `AX_WORKFLOW_EVENT_RECEIPT_TTL_DAYS=30`（再送期間が短い場合）
- `AX_WORKFLOW_EVENT_MAX_RECEIPTS=5000`（イベント量が多い場合）

### 小規模/検証環境の目安
- `AX_WORKFLOW_EVENT_RECEIPT_TTL_DAYS=14`
- `AX_WORKFLOW_EVENT_MAX_RECEIPTS=500`

## 2. 値の決め方
- TTLは「呼び出し側の再送可能期間 + 監査確認バッファ」で決める。
- MAXは「1日平均イベント数 × TTL日数 × 安全係数(1.2〜1.5)」を上限目安にする。
- TTLを短くする場合は、呼び出し側の再送期間より短くしない。

## 3. 監視項目（最低限）
- `workflow_event` の `status` 比率（success / skipped / rejected / failed）
- `reason_class` の上位内訳
- `duplicate=true` の件数推移
- レシート件数（`_workflow_events/receipts.json`）
- 集計API `GET /api/workflow-events/summary?ym=YYYY-MM` の取得可否

## 3.1 集計APIの確認コマンド
```powershell
curl "http://127.0.0.1:8000/api/workflow-events/summary?ym=2026-02&recent_limit=20"
```
- `status=ok` を確認。
- `by_status` と `by_reason_class` が監査ログの実態と一致することを確認。

## 4. 異常時の一次対応
1. `status=failed` が増えたら `reason_class=infra` を優先調査。
2. `status=rejected` が増えたら `reason_class` を確認し、以下で切り分け。
   - `auth`: トークン設定/ヘッダ形式
   - `validation`: year/month や payload形式
   - `template_conflict`: `template_id` / `event_name` 解決条件
   - `unsupported_action`: テンプレート先頭 action
   - `run_conflict`: 同時実行衝突
3. `duplicate` 急増時は呼び出し側の idempotency_key 生成規約を確認。

## 4.1 再送判断（`retry_advice`）
- `do_not_retry`
  - 例: `reason_class=duplicate`
  - 対応: 同一イベントの再送を止める（重複送信元を修正）
- `retry_after_fix`
  - 例: `auth`, `validation`, `template_conflict`, `unsupported_action`
  - 対応: 設定・データを修正してから再送
- `retry_with_backoff`
  - 例: `run_conflict`, `infra`, `failed`
  - 対応: 指数バックオフで再送（例: 30s, 60s, 120s）

## 4.2 再送・再実行フロー（運用手順）
1. `GET /api/workflow-events/summary?ym=YYYY-MM` で `by_retry_advice` と `recent` を確認。
2. `retry_after_fix` は設定修正を先に実施（トークン、template_id、year/month など）。
3. `retry_with_backoff` は同一 `idempotency_key` を保持したまま再送する。
4. 3回連続で `retry_with_backoff` が失敗した場合は運用エスカレーション。
5. 再送後に `status=success` を確認し、運用記録へ残す。

## 5. 運用チェックリスト（月次）
- `workflow_event` の `reason_class` 上位3件を記録。
- `failed` が0でない場合は原因と再発防止を記録。
- レシート件数が上限に近い場合は TTL/MAX の見直しを検討。

## 6. 変更ルール
- TTL/MAXを変更する場合は、`workflow_trigger_execution_progress.md` に日付付きで追記。
- 変更当日は `workflow_events` テスト（最低 `-k "workflow_events"`）を再実行する。

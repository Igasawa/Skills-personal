# Workflow Events ダッシュボード要件（Phase 3.2）

最終更新: 2026-02-20  
対象API: `GET /api/workflow-events/summary`  
目的: `workflow_event` の失敗傾向を UI 上で即時把握し、一次切り分けを短時間化する。

## 1. 表示対象
- 期間: 月次（`ym=YYYY-MM`）
- データソース: `reports/audit_log.jsonl` の `event_type=workflow_event`
- 主キー:
  - `status`（`success` / `skipped` / `rejected` / `failed`）
  - `details.reason_class`
  - `details.reason_code`
  - `details.retry_advice`
  - `details.duplicate`

## 2. MVP表示コンポーネント
1. KPIカード（必須）
- 総イベント数（`total`）
- 成功数（`by_status.success`）
- 拒否数（`by_status.rejected`）
- 失敗数（`by_status.failed`）
- 重複スキップ数（`by_status.skipped`）

2. 失敗内訳（必須）
- `by_reason_class` の上位5件を棒グラフまたはランキングで表示。
- `rejected + failed` の増加時に最上位理由を強調表示。

3. 重複状況（必須）
- `duplicate.true / false / unknown` を表示。
- `duplicate.true` 比率が閾値を超えた場合に注意表示。

4. 直近イベント一覧（必須）
- `recent` を時刻降順で表示。
- 表示列: `at`, `status`, `template_name`, `event_name`, `reason_class`, `reason_code`, `duplicate`, `run_id`

5. 再送判断（必須）
- `by_retry_advice` を表示。
- `retry_after_fix` / `retry_with_backoff` / `do_not_retry` を区別できること。

6. 再送キュー（Phase 3.3 MVP）
- `retry_queue.total` / `retry_queue.due` / `retry_queue.by_status` を表示。
- 少なくとも `pending` / `retrying` / `escalated` の件数を即時確認できること。
- `POST /api/workflow-events/retry-jobs/drain` を呼ぶ手動実行導線（ボタン）を提供する。

## 3. API利用契約（UI側）
- エンドポイント: `GET /api/workflow-events/summary?ym=YYYY-MM&recent_limit=20`
- `ym` は画面で選択中の年月を必ず渡す。
- `recent_limit` は 20 を既定、最大 200。
- 画面更新:
  - 初回ロードで1回取得
  - 手動リロードボタンで再取得
  - 自動更新は Phase 3.3 で追加（MVPでは未実装）

## 4. 異常時の表示方針
- APIエラー時は「集計取得失敗」を表示し、最後の成功取得時刻を残す。
- `total=0` の場合は「該当イベントなし」を表示し、エラー扱いしない。
- `reason_class` 空の場合は「未分類」として集計せず、`reason_code` を優先表示する。

## 5. 受け入れ基準（Phase 3.2）
1. `workflow_event` 集計をAPIから取得し、KPIカードへ表示できる。
2. `reason_class` 上位表示で、少なくとも `auth/validation/run_conflict/infra` を識別できる。
3. `by_retry_advice` から再送判断を即時に確認できる。
4. 直近一覧から `run_id` を辿って監査ログ調査に移れる。
5. API未取得時でも既存画面機能を阻害しない（表示ブロックのみ劣化）。

## 6. 次フェーズ拡張（Phase 3.3）
- 再送キュー（`retry_queue.total/due/by_status`）の可視化
- 日次トレンド（7日/30日）推移
- テンプレート別ヒートマップ（`template_id` 軸）
- SLO閾値監視（`failed` 率 / `duplicate` 率）
- 自動リロードと通知連携（Google Chat、将来の通知チャネル拡張を考慮）

## 7. 実装状況（2026-02-20）
- API: `GET /api/workflow-events/summary` 実装済み。
- API: `GET /api/workflow-events/retry-jobs`, `POST /api/workflow-events/retry-jobs/drain` 実装済み。
- UI: `/expense-workflow-copy` の schedulerパネル内にサマリーカード実装済み（再送判断/再送キュー/再送実行ボタン）。
- テスト: API集計・ページDOM・ルート契約の回帰テスト実装済み。

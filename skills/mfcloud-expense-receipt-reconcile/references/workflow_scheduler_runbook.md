# Scheduler 運用ランブック（Phase 2.3）

最終更新: 2026-02-21
対象: `GET/POST /api/scheduler/state`, `GET /api/scheduler/health`

## 1. 運用値（推奨）

### 推奨デフォルト（本番）
- `AX_SCHEDULER_POLL_SECONDS=15`
- `AX_SCHEDULER_FAILURE_RETRY_SECONDS=60`
- `AX_SCHEDULER_FAILURE_RETRY_MAX_ATTEMPTS=1`

### 検証環境（E2E短縮）
- `AX_SCHEDULER_POLL_SECONDS=5`
- `AX_SCHEDULER_FAILURE_RETRY_SECONDS=3`
- `AX_SCHEDULER_FAILURE_RETRY_MAX_ATTEMPTS=1`

## 2. 値の決め方
- `AX_SCHEDULER_POLL_SECONDS`
  - 小さいほど検知は速いが、常時ポーリング負荷が上がる。
  - 目安: 本番 `10-30`、検証 `3-10`。
- `AX_SCHEDULER_FAILURE_RETRY_SECONDS`
  - 起動失敗後の再試行待機。
  - 一時的な競合吸収を優先するなら短め、外部依存の復旧待ちを優先するなら長めに設定。
- `AX_SCHEDULER_FAILURE_RETRY_MAX_ATTEMPTS`
  - 同一スロットでの再試行回数。
  - 副作用の重い処理を想定し、MVPでは `1` 固定を推奨。

## 3. 変更手順（Windows）
1. セッションで環境変数を設定する。
```powershell
$env:AX_SCHEDULER_POLL_SECONDS = "5"
$env:AX_SCHEDULER_FAILURE_RETRY_SECONDS = "3"
$env:AX_SCHEDULER_FAILURE_RETRY_MAX_ATTEMPTS = "1"
```
2. ダッシュボードを再起動する。
```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_dashboard.ps1 -NoOpen -BindHost 127.0.0.1 -Port 8779 -Restart -WaitSeconds 120
```
3. health APIで反映値を確認する。
```powershell
curl "http://127.0.0.1:8779/api/scheduler/health?limit=1"
```
4. `failure_retry_seconds`, `failure_retry_max_attempts` が想定通りであることを確認する。

## 4. 検証手順（Playwright）
```powershell
powershell -ExecutionPolicy Bypass -File scripts/playwright_smoke_scheduler_phase23.ps1 -BaseUrl http://127.0.0.1:8779 -TemplateId e2e_scheduler_phase23_retry_fast
```
- 成功時はレポートに以下が出力される。
  - `check=retry_scheduled:pass`
  - `check=retry_exhausted:pass`
  - `retry_seconds=<設定値>`
  - `retry_max_attempts=<設定値>`

## 5. トラブルシュート
- `retry_scheduled` のまま進まない
  - `AX_SCHEDULER_FAILURE_RETRY_SECONDS` が長すぎないか確認。
  - `GET /api/scheduler/health` の `worker_running=true` を確認。
- すぐ `failed` になる
  - `failure_retry_max_attempts` が `1` 未満になっていないか確認（無効値は既定値にフォールバック）。
  - 失敗原因は `last_result.detail` と監査ログ `event_type=scheduler` を確認。
- 二重起動が疑われる
  - `active_locks` / `stale_locks` を `GET /api/scheduler/health` で確認。
  - `reports/audit_log.jsonl` の同一 `scheduled_for` / `template_id` の重複有無を確認。

## 6. 変更時の注意
- `AX_SCHEDULER_POLL_SECONDS` を極端に短くすると、監査ログが増え運用ノイズが高まる。
- `AX_SCHEDULER_FAILURE_RETRY_MAX_ATTEMPTS` を増やすと、外部連携の副作用リスクが上がる。
- 値変更後は必ず `/api/scheduler/health` の実値確認とPlaywrightスモークを実行する。

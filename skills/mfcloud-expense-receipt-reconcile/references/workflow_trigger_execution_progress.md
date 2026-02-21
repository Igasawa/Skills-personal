# ワークフロー手順トリガー実装 進捗トラッカー

最終更新: 2026-02-21
対象画面: `/expense-workflow-copy`
対象仕様: 手順ごとの「開始条件（trigger）」と「実行方法（execution mode）」

## 1. 目的
- UI文言の混同（自動 vs 前手順完了後）を解消し、MVP時点で誤設定を防ぐ。
- MVPはスケルトン優先とし、スケジューラや外部イベント連携は後続フェーズで増設する。
- 開発・検証・運用の進捗を、このファイルだけで時系列追跡できる状態にする。

## 2. フェーズ定義（アジャイル段階導入）

| フェーズ | 目的 | スコープ | 完了条件 | 状態 |
| --- | --- | --- | --- | --- |
| Phase 0 | 用語とUIの整流化 | ラベル、ヘルプ文言、バリデーション、プレビュー表記 | `開始条件` / `実行方法` が画面上で明示される | 完了 |
| Phase 1 | MVPのルール固定 | 先頭手順と後続手順の開始条件制約、タイプ別実行方法制約 | 不正組み合わせを入力時に防止できる | 完了 |
| Phase 2 | スケジュール実行増設 | scheduler UI/API/ジョブ実行基盤 | 指定日時/周期で先頭手順を起動できる | 進行中 |
| Phase 3 | 外部イベント増設 | webhook/event受信、署名検証、再送制御 | 外部イベントで先頭手順を起動できる | 進行中 |
| Phase 4 | 堅牢化 | 監査ログ、再実行戦略、運用メトリクス | 障害時の原因追跡と再処理が可能 | 未着手 |

## 3. 現在の実装ポリシー（MVP）
- `trigger_kind` は「いつ開始するか（開始条件）」を示す。
- `execution_mode` は「開始後にどう進めるか（実行方法）」を示す。
- 後続手順の開始条件は `after_previous` 固定。
- 人ステップ（`manual`）の実行方法は `manual_confirm` 固定。
- スケジューラ・外部イベントの本実行は後続フェーズで実装する。

## 4. 進捗ログ

### 2026-02-20
- 実装:
  - `index.state.js`
    - 手順詳細の選択UIをラベル付きに変更（`担当タイプ` / `開始条件` / `実行方法`）。
    - ARIAラベルを `開始条件` / `実行方法` ベースへ更新。
    - バリデーション文言を `トリガー` から `開始条件` に統一。
  - `index.constants.js`
    - 実行方法の選択肢ラベル `auto` を `自動実行` に更新。
  - `index.api.js`
    - 手順プレビュー表示に `開始条件` / `実行方法` の文脈ラベルを追加。
  - `expense_workflow_card.html`
    - MVPノートに「開始条件」と「実行方法」の意味を明記。
  - `pages.css`
    - ラベル付き選択フィールド用スタイルを追加。
  - `references/workflow_trigger_execution_contract.md`
    - 開始条件/実行方法の制約マトリクスを実装準拠で固定化。
    - 手順位置・ステップタイプ・タイマーの許可条件を契約として明文化。
  - `common.js`
    - APIの制約エラーを `toFriendlyMessage` で利用者向け文言へ統一（Phase 1B）。
  - `tests/test_dashboard_api.py`
    - 制約マトリクスの不足ケースを追加（Phase 1C）。
    - 追加ケース:
      - 先頭手順で `trigger_kind=after_previous` を拒否すること
      - `execution_mode=auto` + `timer_minutes=0` を拒否すること
  - `scripts/playwright_smoke_trigger_execution.ps1`
    - UI制約を自動確認するPlaywrightスモークを追加（Phase 1C）。
    - 確認項目:
      - 手順詳細の選択フィールド表示
      - プレビュー形式（手順要約の区切り）
      - `agent` で `execution_mode=auto` が選択可能
      - `manual` で `execution_mode=manual_confirm` のみ
      - 2手順目の `trigger_kind=after_previous` 固定
  - `expense_workflow_copy.html`
    - schedulerパネルを再導入し、`/expense-workflow-copy` で状態参照/保存UIを提供（Phase 2.1）。
    - scheduler用の hidden フィールド（`mfcloud_url` / `notes`）を追加。
  - `scheduler.js`
    - template_id必須の安全制御（template未選択時は保存不可）を追加。
    - 手順1アクションに追従して `action_key` を同期する処理を追加。
  - `core_scheduler.py`
    - `once` 用の永続 idempotency キー（`template_id + run_date + run_time`）を `once_trigger_receipts` として追加。
    - 同一スロット再実行時は `skipped_duplicate` として抑止し、`enabled=false` へ収束させる処理を追加。
    - scheduler評価結果（started / skipped / deferred / failed）を `reports/audit_log.jsonl` へ `event_type=scheduler` で記録。
    - テンプレート削除時に対象テンプレートの `once_trigger_receipts` を掃除する処理を追加。
  - `tests/test_dashboard_api.py`
    - `once` の再arm時に同一時刻が二重起動しないことを確認するテストを追加。
    - テンプレート削除時に `once_trigger_receipts` が除去されることを確認するテストを追加。
  - `index.api.js` / `scheduler.js` / `expense_workflow_copy.html`
    - テンプレート保存レスポンスの `scheduler_sync.reason` を `sessionStorage` 経由で引き継ぎ、schedulerカード上に表示。
    - `scheduler_sync.status=error` の場合は保存時トーストでも通知。
    - 表示要素 `#scheduler-sync-reason` を追加。
  - `tests/test_dashboard_pages.py`
    - `#scheduler-sync-reason` の描画有無をページテストで検証。
  - `references/workflow_external_event_phase3_plan.md`
    - Phase 3（external_event）を 3.1/3.2/3.3 に分割した計画書を追加。
  - `references/workflow_external_event_contract.md`
    - `POST /api/workflow-events` の契約（認証、解決順、idempotency、エラーコード、監査ログ）を固定化。
    - Phase 3.2 の保持ポリシー（TTL/上限）と監査分類（`reason_class`/`reason_code`）を追記。
  - `tests/test_dashboard_api.py`
    - `workflow-events` 異常系を追加（未対応アクション、invalid year/month、event_name不一致/重複、Bearerトークン）。
    - `workflow-events` Phase 3.2 ケースを追加（レシートTTL失効、保持件数上限、auth分類監査、run_conflict分類監査）。
  - `api_workspace_routes.py`
    - `workflow-events` 受信レシートに TTL/上限クリーンアップを追加（`AX_WORKFLOW_EVENT_RECEIPT_TTL_DAYS`, `AX_WORKFLOW_EVENT_MAX_RECEIPTS`）。
    - `workflow_event` 監査 `details` に `reason_class` / `reason_code` / `duplicate` を追加。
    - `GET /api/workflow-events/summary` を追加し、`status/reason_class/reason_code/duplicate/recent` を集計返却。
  - `pages.py`
    - `expense-workflow-copy` 読み込み時にテンプレートの `year/month` をフォーム既定値へ反映。
  - `tests/test_dashboard_pages.py` / `tests/test_dashboard_contract.py`
    - schedulerパネル表示・script読み込み・テンプレート文脈反映のテストへ更新。
  - `tests/test_dashboard_api.py`
    - `workflow-events/summary` の集計検証テストを追加（集計値、時刻降順、空データ）。
  - `references/workflow_external_event_dashboard_requirements.md`
    - `workflow_event` 監査分類のダッシュボード表示要件（MVP）を新規作成。
  - `references/workflow_external_event_runbook.md`
    - 集計APIの運用確認手順を追記。
  - `expense_workflow_copy.html` / `scheduler.js` / `pages.css`
    - `workflow-events/summary` を表示する外部イベント監査サマリーカード（KPI/理由分類/重複/直近イベント）を実装。
    - schedulerパネルから集計更新ボタンで再取得できるように実装。
  - `tests/test_dashboard_pages.py` / `tests/test_dashboard_contract.py`
    - サマリーカードDOMの存在確認と `/api/workflow-events/summary` ルート契約を追記。
  - `references/workflow_scheduler_phase2_plan.md`
    - Phase 2.3（daily/weekly/monthly, catch-up, retry）の受け入れ条件を具体化。
- 検証:
  - JS構文チェック
    - `node --check dashboard/static/js/index.constants.js`: 成功
    - `node --check dashboard/static/js/index.state.js`: 成功
    - `node --check dashboard/static/js/index.api.js`: 成功
  - pytest（対象テスト）
    - `pytest tests/test_dashboard_pages.py -k "expense_workflow_copy_page_shows_shared_wizard or expense_workflow_copy_step_card_script_supports_timer_and_default_clone"`: 2 passed
    - `pytest tests/test_dashboard_contract.py -k "dashboard_index_js_exports_contract or dashboard_templates_reference_expected_script_chunks"`: 2 passed
    - `pytest tests/test_dashboard_api.py -k "rejects_invalid_first_trigger_kind or rejects_auto_mode_with_zero_timer or rejects_invalid_trigger_by_position or rejects_manual_auto_execution_mode or rejects_auto_mode_without_timer"`: 5 passed
    - `pytest tests/test_dashboard_pages.py -k "expense_workflow_copy_page_shows_shared_wizard or expense_workflow_copy_template_loads_scheduler_panel_with_template_context or expense_workflow_copy_step_card_script_supports_timer_and_default_clone"`: 3 passed
    - `pytest tests/test_dashboard_contract.py -k "dashboard_templates_reference_expected_script_chunks"`: 1 passed
    - `pytest tests/test_dashboard_api.py -k "api_scheduler_state_get_returns_default or api_scheduler_state_post_persists_context_fields"`: 2 passed
    - `pytest tests/test_dashboard_api.py -k "scheduler"`: 11 passed
    - `pytest tests/test_dashboard_pages.py -k "expense_workflow_copy_page_shows_shared_wizard or expense_workflow_copy_template_loads_scheduler_panel_with_template_context"`: 2 passed
    - `pytest tests/test_dashboard_contract.py -k "dashboard_templates_reference_expected_script_chunks"`: 1 passed
    - `pytest tests/test_dashboard_api.py`: 106 passed
    - `pytest tests/test_dashboard_api.py -k "workflow_events"`: 9 passed
    - `pytest tests/test_dashboard_api.py -k "workflow_events"`: 13 passed
    - `pytest tests/test_dashboard_api.py`: 115 passed
    - `pytest tests/test_dashboard_api.py -k "workflow_events"`: 15 passed
    - `pytest tests/test_dashboard_api.py`: 117 passed
    - `node --check dashboard/static/js/scheduler.js`: 成功
    - `pytest tests/test_dashboard_pages.py -k "expense_workflow_copy_page_shows_shared_wizard or expense_workflow_copy_template_loads_scheduler_panel_with_template_context"`: 2 passed
    - `pytest tests/test_dashboard_contract.py -k "api_router_registers_expected_routes or dashboard_templates_reference_expected_script_chunks"`: 2 passed
  - Playwright（実画面確認）
    - ページ: `http://127.0.0.1:8011/expense-workflow-copy`
    - 確認項目:
      - 手順詳細に `担当タイプ` / `開始条件` / `実行方法` が表示されること
      - 作成プレビューに `開始条件:` / `実行方法:` を含むこと
      - AIタイプ選択時、実行方法候補に `自動実行` が表示されること
    - 取得物:
      - `.playwright-cli/page-2026-02-20T02-54-56-429Z.png`
      - `.playwright-cli/page-2026-02-20T02-54-23-820Z.yml`
  - Playwright（再現可能スモーク）
    - コマンド:
      - `powershell -ExecutionPolicy Bypass -File scripts/playwright_smoke_trigger_execution.ps1 -BaseUrl http://127.0.0.1:8012`
    - 結果:
      - `workflow_trigger_execution_smoke_20260220_122318.txt` で全チェック `pass`
    - 取得物:
      - `output/playwright/workflow_trigger_execution_smoke_20260220_122318.txt`
      - `.playwright-cli/page-2026-02-20T03-23-26-493Z.png`
    - 追試（2026-02-21）:
      - `workflow_trigger_execution_smoke_20260221_055814.txt` で全チェック `pass`
      - 取得物: `output/playwright/workflow_trigger_execution_smoke_20260221_055814.txt`
  - Playwright（Phase 2.1 UI/API往復）
    - ページ: `http://127.0.0.1:8013/expense-workflow-copy?template=3d0477ae024d4591a1dbf6e7`
    - 操作: schedulerの `run_date/run_time` を更新して保存
    - API再取得: `/api/scheduler/state?template_id=3d0477ae024d4591a1dbf6e7` で反映を確認
    - 確認結果:
      - `enabled=true`
      - `year=2026`, `month=2`
      - `run_date=2099-02-03`, `run_time=09:45`
    - 取得物:
      - `.playwright-cli/page-2026-02-20T03-44-31-942Z.png`
  - Playwright（Phase 3.2 サマリーUI確認）
    - ページ: `http://127.0.0.1:8014/expense-workflow-copy`
    - 確認項目:
      - `#workflow-event-summary-panel` が表示されること
      - `集計更新` 押下で `#workflow-event-summary-meta` が更新されること
      - `#workflow-event-summary-recent` に最低1行（空データ行含む）が表示されること
    - 実行結果:
      - `workflow_event_summary_smoke_20260221_070747.txt` で全チェック `pass`
    - 取得物:
      - `output/playwright/workflow_event_summary_smoke_20260221_070747.txt`
      - `output/playwright/workflow_event_summary_ui_20260221_070821.png`
  - Phase 1A（仕様固定）:
    - 完了（契約ドキュメントを作成し、MVPの判断基準を固定）
  - Phase 1B（UI/APIエラー契約統一）:
    - 完了（主要制約エラーの利用者向け文言を統一）
  - Phase 1C（回帰テスト追加）:
    - 完了（APIケース追加 + UIスモーク自動化まで実施）
  - Phase 2.1（scheduler状態のAPI/UI往復）:
    - 完了（UI再導入 + API往復 + Playwright保存確認まで実施）
  - Phase 2.2（once安全起動 + 二重実行防止）:
    - 完了（永続idempotencyキー + scheduler監査ログ + 回帰テストまで実施）
  - Phase 2.2補完（`scheduler_sync.reason` 可視化）:
    - 完了（保存レスポンス→schedulerカード表示まで実装）
  - Phase 3.1（external_event 契約固定）:
    - 完了（契約ドキュメント + 異常系テスト追加まで実施）
  - Phase 3.2（保護強化）:
    - 完了（TTL/上限 + 監査分類 + 集計API + 運用ランブック/要件定義まで実施）
  - Phase 3.3（再送運用のMVP実装）:
    - `api_workspace_routes.py` に `retry_advice` 自動分類を追加（`do_not_retry` / `retry_after_fix` / `retry_with_backoff`）。
    - `GET /api/workflow-events/summary` に `by_retry_advice` 集計と `recent[].retry_advice` を追加。
    - `retry_jobs` キュー（`_workflow_events/retry_jobs.json`）を追加。
    - `GET /api/workflow-events/retry-jobs` と `POST /api/workflow-events/retry-jobs/drain` を追加。
    - `retry_with_backoff` 失敗時のみ再送ジョブを自動登録し、最大試行到達時は `escalated` へ遷移。
    - `AX_WORKFLOW_EVENT_RETRY_WORKER_ENABLED` / `AX_WORKFLOW_EVENT_RETRY_WORKER_POLL_SECONDS` で制御する自動drainワーカーを追加。
    - アプリ起動ライフサイクルに再送ワーカーの start/stop を接続。
    - `expense_workflow_copy.html` / `scheduler.js` に再送キュー表示（total/due/status別）と手動 `drain` ボタンを追加。
    - `expense_workflow_copy.html` / `scheduler.js` に「再送判断」ブロックを追加し、集計表示を実装。
    - `tests/test_dashboard_api.py` と `tests/test_dashboard_pages.py` を更新し、分類/表示/再送ジョブ挙動を検証。
    - `workflow_external_event_contract.md` / `workflow_external_event_dashboard_requirements.md` / `workflow_external_event_runbook.md` に契約・運用手順を追記。
  - 追加検証（Phase 3.3 先行実装分）:
    - `node --check skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/scheduler.js`: 成功
    - `pytest skills/mfcloud-expense-receipt-reconcile/tests/test_shared_runtime_modules.py -k "dashboard_app_factory_mounts_and_calls_stop_worker or dashboard_app_factory_calls_start_and_stop_worker"`: 2 passed
    - `pytest skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_api.py -k "workflow_events_auth_failure_writes_classified_audit or workflow_events_run_conflict_writes_classified_audit or workflow_events_summary_returns_aggregated_counts or workflow_events_summary_returns_empty_when_audit_not_found"`: 4 passed
    - `pytest skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_pages.py -k "expense_workflow_copy_page_shows_shared_wizard or expense_workflow_copy_template_loads_scheduler_panel_with_template_context"`: 2 passed
    - Playwright（最小実画面確認）:
      - `#workflow-event-summary-retry-advice` のDOM存在を `playwright-cli eval` で確認（`present`）。
      - 取得物:
        - `output/playwright/workflow_retry_advice_smoke_20260221_072639.txt`
        - `.playwright-cli/page-2026-02-20T22-26-44-146Z.png`
    - `pytest skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_api.py`: 120 passed
    - `pytest skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_pages.py`: 32 passed
    - `pytest skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_contract.py`: 5 passed
    - `node --check skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/scheduler.js`: 成功
    - Playwright（再送キューUI確認）:
      - `#workflow-event-retry-drain` と `#workflow-event-summary-retry-queue` のDOM存在を確認（pass）。
      - 取得物:
        - `output/playwright/workflow_retry_queue_ui_smoke_20260221_074559.txt`
        - `.playwright-cli/page-2026-02-20T22-46-07-366Z.png`
  - 未解決:
    - Phase 2.3（繰り返し運用）の retry policy（起動失敗時1回再試行）は未対応
    - Phase 3.3（再送・再実行運用）の `escalated` 通知連携（Slack/メール）は未対応

### 2026-02-21
- 実装:
  - `core_scheduler.py`
    - `monthly_anchor_day` を内部状態に追加し、`monthly` の日付進行で「元の日付アンカー」を保持するよう更新。
    - 31日指定の月次スケジュールで、2月補正後も次回以降に31日基準へ復帰できるよう修正。
    - APIレスポンスには `monthly_anchor_day` を露出しないよう `enrich` 時に除外。
    - 起動失敗時の最小retry policyを追加（同一スロットで1回だけ再試行し、再失敗時は `retry_exhausted` で `failed` 確定）。
    - retry内部状態（`failure_retry_signature/attempts/next_at`）を導入し、APIレスポンスからは非公開化。
  - `tests/test_dashboard_api.py`
    - `weekly` 起動後に `run_date` が 7日進行するケースを追加。
    - `monthly` 31日指定が短月を挟んでもアンカー日を維持するケースを追加。
    - 起動失敗が1回再試行されること、再試行成功/再失敗の確定挙動を検証するケースを追加。
  - `scripts/playwright_smoke_scheduler_phase23.ps1`
    - schedulerの recurrence 選択肢（once/daily/weekly/monthly）と weekly/monthly 保存のUI/API往復を確認するスモークを追加。
- 検証:
  - `pytest -q skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_api.py -k "weekly_recurrence_advances_by_week or monthly_recurrence_preserves_anchor_day_after_short_month"`: 2 passed
  - `pytest -q skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_api.py -k "run_failure_retries_once_then_fails or run_failure_retry_succeeds_on_second_attempt"`: 2 passed
  - `pytest -q skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_api.py -k "scheduler"`: 28 passed
  - `pytest -q skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_pages.py -k "expense_workflow_copy_page_shows_shared_wizard or expense_workflow_copy_template_loads_scheduler_panel_with_template_context"`: 2 passed
  - `pytest -q skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_contract.py -k "api_router_registers_expected_routes or dashboard_templates_reference_expected_script_chunks"`: 2 passed
  - `powershell -ExecutionPolicy Bypass -File skills/mfcloud-expense-receipt-reconcile/scripts/playwright_smoke_scheduler_phase23.ps1 -BaseUrl http://127.0.0.1:8778`: pass
    - レポート: `output/playwright/workflow_scheduler_phase23_smoke_20260221_125404.txt`
- 未解決:
  - Phase 2.3 の Playwright実画面検証（retry失敗→再試行→確定失敗の可視シナリオ追加）

## 5. 直近タスク（次の更新対象）
1. Phase 3.3拡張: `escalated` 通知連携（Slack/メール）を追加
2. Phase 2.3完了検証: retry失敗→再試行→確定失敗の Playwrightシナリオ追加
3. 可視化拡張: `workflow-events/summary` を基に日次トレンド/通知要件を具体化

## 6. 更新ルール
- 実装または検証を行った日付ごとに「進捗ログ」を追記する。
- 各エントリには最低限 `実装`, `検証`, `未解決` を記録する。
- フェーズ状態の更新は、実装完了時ではなく「検証完了時」に変更する。

## 7. 関連計画書
- Phase 2（スケジュール実行増設）: `references/workflow_scheduler_phase2_plan.md`
- Phase 3（外部イベント増設）: `references/workflow_external_event_phase3_plan.md`
- Phase 3契約（external_event）: `references/workflow_external_event_contract.md`
- 制約契約（MVP）: `references/workflow_trigger_execution_contract.md`

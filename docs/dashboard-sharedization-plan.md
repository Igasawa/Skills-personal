# Dashboard Sharedization Plan

Updated: 2026-02-20  
Scope: `skills/mfcloud-expense-receipt-reconcile` から社内共通化可能な基盤を段階抽出

## Goal

- スキル固有ロジック（Amazon/Rakuten/MF業務処理）を残しつつ、再利用可能なダッシュボード基盤を共通ライブラリ化する。
- 既存運用を壊さないため、互換ラッパー方式で段階移行する。

## Step Plan

### Step 1: Runtime共通関数の抽出（Completed）

- Added: `scripts/lib/skill_runtime_common.py`
- Updated: `skills/mfcloud-expense-receipt-reconcile/common.py`（互換ラッパー化）
- Outcome:
- `AX_HOME` 解決、artifact/runs path、JSON/JSONL I/O、補助関数をスキル外へ移動
- 既存 import 互換を維持

### Step 2: Dashboard app shellの抽出（Completed）

- Added: `scripts/lib/dashboard_app_factory.py`
- Updated: `skills/mfcloud-expense-receipt-reconcile/dashboard/app.py`
- Outcome:
- FastAPI app 生成、static mount、templates/router 組み立て、worker停止フックを共通化
- FastAPI lifespan 方式へ更新（`on_event` 非推奨対策）

### Step 3: Workflow Template Store分離（Completed）

- Target:
- `dashboard/routes/api_workflow_endpoints.py`
- `dashboard/routes/api_workspace_routes.py`
- `dashboard/routes/pages.py`
- Added:
- `scripts/lib/workflow_template_store_common.py`
- Updated:
- `skills/mfcloud-expense-receipt-reconcile/common.py`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/services/core_shared.py`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/services/core.py`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/routes/api_workflow_endpoints.py`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/routes/pages.py`
- `skills/mfcloud-expense-receipt-reconcile/tests/test_shared_runtime_modules.py`
- Outcome:
- workflow template の path/read/write/sort を `scripts/lib` の共通実装へ移行
- route 層は正規化と業務バリデーションに専念
- Acceptance:
- APIレスポンス互換
- 既存 dashboard tests 緑維持

### Step 4: Run Registry/Audit基盤分離（Completed）

- Target:
- `dashboard/services/core_runs_*`
- `dashboard/services/core_artifacts.py`
- Added:
- `scripts/lib/run_registry_common.py`
- `scripts/lib/artifact_archive_common.py`
- Updated:
- `skills/mfcloud-expense-receipt-reconcile/common.py`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/services/core_shared.py`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/services/core_runs_paths.py`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/services/core_runs_audit.py`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/services/core_runs_engine.py`
- `skills/mfcloud-expense-receipt-reconcile/dashboard/services/core_artifacts.py`
- `skills/mfcloud-expense-receipt-reconcile/tests/test_shared_runtime_modules.py`
- Outcome:
- run registry の整数正規化・actor正規化・audit JSONL 追記・tail 読み取り・running job 判定を `scripts/lib` に共通化
- archive history / archived receipts 走査を `scripts/lib` に共通化
- スキル側は workflow 制約・実行モード判定・業務固有処理を維持

## Guardrails

- 互換優先: 既存CLI/API/ファイル出力形式を変更しない
- 小さい単位で移行: 1ステップごとにテスト通過を必須
- スキル固有ロジックは共通化しない

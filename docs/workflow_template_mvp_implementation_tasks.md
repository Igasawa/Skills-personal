# ワークフロー作成テンプレート MVP 実装タスク分解

- 作成日: 2026-02-19
- 対象仕様: `docs/workflow_template_mvp_spec.md`
- 実装方針: 最小変更でMVP成立。既存のワークフロー実行機能は壊さない。

## 1. 変更対象ファイル

1. `skills/mfcloud-expense-receipt-reconcile/dashboard/templates/components/expense_workflow_card.html`
2. `skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/index.js`
3. `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/pages.css`
4. `skills/mfcloud-expense-receipt-reconcile/dashboard/routes/api.py`
5. `skills/mfcloud-expense-receipt-reconcile/dashboard/routes/pages.py`
6. `skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_pages.py`
7. `skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_api.py`

## 2. 実装スコープ(今回)

1. タスクカード追加
2. 表示番号の連番再計算
3. DnD並び替え
4. `autoRun` トグル
5. タイマー入力UI(保存のみ、実行なし)
6. 実行ログの最小表示(最新1件)
7. 内部ID固定(`stepUid`相当)と表示番号分離

## 3. フロント実装タスク

## 3.1 タスクカードUI追加

対象: `skills/mfcloud-expense-receipt-reconcile/dashboard/templates/components/expense_workflow_card.html`

1. タスク一覧上にMVP注意文言を追加  
   例: `タイマーはMVPでは自動実行されません`
2. カード内で以下の要素を持てるようにする
   - ドラッグハンドル
   - 表示番号
   - タイトル入力
   - アクション選択(既存互換のため維持)
   - `autoRun` トグル
   - タイマー入力(分)
   - 削除ボタン
   - 最新実行ログ表示領域

## 3.2 ステップモデル/収集ロジック更新

対象: `skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/index.js`

1. ステップ正規化に次の項目を追加
   - `id`(内部ID、既存継続)
   - `order`
   - `auto_run`
   - `timer_minutes`
   - `execution_log`
2. 表示番号は `order` から再計算して描画(保存時に `order` 付与)
3. `autoRun=ON` 時のみタイマー必須にする
4. `autoRun=OFF` 時はタイマーUIを非活性化
5. 実行ログは編集不可・表示のみ(最新1件表示)

## 3.3 DnD並び替え

対象: `skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/index.js`

1. HTML5 DnDでカード並び替えを実装
2. ドロップ確定時に `order` と表示番号を再計算
3. 並び替え時に `id` は変更しない
4. 並び替え後に `template-steps-changed` を発火(既存連携維持)

## 3.4 スタイル調整

対象: `skills/mfcloud-expense-receipt-reconcile/dashboard/static/styles/pages.css`

1. タスク行を「カード見た目」に寄せる
2. ドラッグ中/ドロップ先ハイライトを追加
3. モバイル時の折り返し崩れを防止

## 4. API実装タスク

## 4.1 ステップ正規化拡張

対象: `skills/mfcloud-expense-receipt-reconcile/dashboard/routes/api.py`

1. `_normalize_workflow_template_steps` で以下を受理・正規化
   - `id` (既存)
   - `order`
   - `auto_run` / `autoRun`
   - `timer_minutes` / `timer`
   - `execution_log` / `executionLog`
2. `execution_log` は最小項目のみ保持
   - `executed_at`
   - `result(success|failed)`
   - `message`
3. `auto_run=true` で不正タイマーの場合は安全な既定値へ補正
4. 互換性維持: 既存データ(旧キーのみ)も受け入れる

## 4.2 表示用正規化拡張

対象: `skills/mfcloud-expense-receipt-reconcile/dashboard/routes/pages.py`

1. `_normalize_template_steps_for_view` で新項目を透過
2. 旧データからの欠損は安全デフォルトで補完
3. 画面へ返すJSONに `order/auto_run/execution_log` を含める

## 5. テスト実装タスク

## 5.1 ページテスト

対象: `skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_pages.py`

1. WF作成ページに以下要素があることを検証
   - DnDハンドル属性
   - `autoRun` トグル属性
   - タイマー入力属性
   - MVP注記文言

## 5.2 APIテスト

対象: `skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_api.py`

1. 新フィールド保存/再取得の往復テスト
2. 旧フォーマット入力の互換テスト
3. `auto_run=true` + 不正タイマー補正テスト
4. `execution_log` 正規化テスト(結果値/件数上限)

## 5.3 回帰テスト

対象: 既存のワークフローテンプレート関連テスト

1. テンプレート保存
2. ワークフローページ作成
3. スケジューラモード再構築(`scheduler.js`連携)

## 6. 実装順序(着手順固定)

1. API正規化拡張 (`api.py`, `pages.py`)
2. フロントモデル拡張 (`index.js`)
3. UI/スタイル更新 (`expense_workflow_card.html`, `pages.css`)
4. DnD実装 (`index.js`)
5. テスト追加/更新 (`test_dashboard_api.py`, `test_dashboard_pages.py`)
6. 回帰実行

## 7. 受け入れチェック(実装完了条件)

1. カード追加・削除・編集ができる
2. DnD後に連番が崩れない
3. `id` が並び替えで変化しない
4. `autoRun` OFF時はタイマー未入力でも保存可
5. `autoRun` ON時はタイマー不正値が拒否または補正される
6. タイマー実行は発火しない(UIのみ)
7. 実行ログ最新1件がカードに表示される

## 8. リスクと対策

1. 既存ステップ必須化ロジックとの衝突  
   対策: 必須ステップは維持しつつ、並び順はユーザー順を優先
2. 旧データ読込時の項目欠損  
   対策: サーバー側でデフォルト補完
3. runページとの共通JS影響  
   対策: `wizard-copy` 画面でのDOM存在チェックを厳格化

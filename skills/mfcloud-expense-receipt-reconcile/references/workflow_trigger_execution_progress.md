# ワークフロー手順トリガー実装 進捗トラッカー

最終更新: 2026-02-20
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
| Phase 1 | MVPのルール固定 | 先頭手順と後続手順の開始条件制約、タイプ別実行方法制約 | 不正組み合わせを入力時に防止できる | 進行中 |
| Phase 2 | スケジュール実行増設 | scheduler UI/API/ジョブ実行基盤 | 指定日時/周期で先頭手順を起動できる | 未着手 |
| Phase 3 | 外部イベント増設 | webhook/event受信、署名検証、再送制御 | 外部イベントで先頭手順を起動できる | 未着手 |
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
- 検証:
  - JS構文チェック
    - `node --check dashboard/static/js/index.constants.js`: 成功
    - `node --check dashboard/static/js/index.state.js`: 成功
    - `node --check dashboard/static/js/index.api.js`: 成功
  - pytest（対象テスト）
    - `pytest tests/test_dashboard_pages.py -k "expense_workflow_copy_page_shows_shared_wizard or expense_workflow_copy_step_card_script_supports_timer_and_default_clone"`: 2 passed
    - `pytest tests/test_dashboard_contract.py -k "dashboard_index_js_exports_contract or dashboard_templates_reference_expected_script_chunks"`: 2 passed
  - Playwright（実画面確認）
    - ページ: `http://127.0.0.1:8011/expense-workflow-copy`
    - 確認項目:
      - 手順詳細に `担当タイプ` / `開始条件` / `実行方法` が表示されること
      - 作成プレビューに `開始条件:` / `実行方法:` を含むこと
      - AIタイプ選択時、実行方法候補に `自動実行` が表示されること
    - 取得物:
      - `.playwright-cli/page-2026-02-20T02-54-56-429Z.png`
      - `.playwright-cli/page-2026-02-20T02-54-23-820Z.yml`

## 5. 直近タスク（次の更新対象）
1. Phase 1の残タスクを分解（制約ルールの仕様明文化と回帰テスト追加）
2. Phase 2（スケジューラ増設）の詳細実装計画を分解して着手
3. Phase 3（外部イベント増設）で必要な受信API契約を先行定義

## 6. 更新ルール
- 実装または検証を行った日付ごとに「進捗ログ」を追記する。
- 各エントリには最低限 `実装`, `検証`, `未解決` を記録する。
- フェーズ状態の更新は、実装完了時ではなく「検証完了時」に変更する。

# ワークフロー開始条件/実行方法 契約（MVP）

最終更新: 2026-02-20  
対象画面: `/expense-workflow-copy`  
対象API: `/api/workflow-templates`, `/api/workflow-pages`

## 1. 用語
- 開始条件（`trigger_kind`）: 手順を開始するきっかけ。
- 実行方法（`execution_mode`）: 開始後に手動確認で進めるか、自動実行で進めるか。

## 2. データ契約
- `trigger_kind`（enum）
  - `manual_start`
  - `scheduled`
  - `external_event`
  - `after_previous`
- `execution_mode`（enum）
  - `manual_confirm`
  - `auto`
- `timer_minutes`（number | null）
  - `execution_mode=auto` の場合のみ必須（範囲制約あり）。

## 3. 制約マトリクス（確定）

### 3.1 手順位置 × 開始条件
| 手順位置 | 許可される `trigger_kind` |
| --- | --- |
| 先頭手順（Step 1） | `manual_start` / `scheduled` / `external_event` |
| 2手順目以降（Step 2+） | `after_previous` のみ |

### 3.2 ステップタイプ × 実行方法
| `step_type` | 許可される `execution_mode` |
| --- | --- |
| `manual` | `manual_confirm` のみ |
| `agent` | `manual_confirm` / `auto` |
| `browser` | `manual_confirm` / `auto` |

### 3.3 自動実行時のタイマー
| 条件 | 制約 |
| --- | --- |
| `execution_mode=auto` | `timer_minutes` 必須 |
| `timer_minutes` 範囲 | `1` 以上 `10080` 以下（分） |

## 4. 追加フィールド制約
- `step_type=browser` の場合は `target_url` 必須（`http://` または `https://`）。
- `step_type=agent` の場合は `agent_prompt` 必須。

## 5. レイヤ別の責務
- UI（`dashboard/static/js/index.state.js`）
  - 許可されない選択肢を原則表示しない。
  - 入力時に即時バリデーションし、保存前に弾く。
- API（`dashboard/routes/api_workflow_endpoints.py`）
  - 最終防衛線として厳格に検証し、`400` を返す。
  - UIからの不正入力や将来クライアント差分を吸収する。

## 6. 互換ルール（legacy）
- `trigger` 互換値は `trigger_kind` に正規化して扱う。
- `auto_run` 互換値は `execution_mode` に正規化して扱う。
- 永続化時は `trigger_kind` / `execution_mode` を主契約とする。

## 7. MVPスコープ外（明示）
- `scheduled` のジョブ起動基盤（本格スケジューラ）
- `external_event` の受信基盤（Webhook署名検証/再送制御）
- 実行エンジンの高度なリトライ/再開戦略

## 8. 参照実装
- UI制約: `dashboard/static/js/index.state.js`
- API制約: `dashboard/routes/api_workflow_endpoints.py`
- 進捗トラッカー: `references/workflow_trigger_execution_progress.md`

## 9. エラー契約（UI表示）
- API `detail` は `dashboard/static/js/common.js` の `toFriendlyMessage` で利用者向け文言へ変換する。
- MVP時点の主要変換対象:
  - `Step 1 trigger_kind must ...` → 先頭手順の開始条件エラー
  - `trigger_kind must be after_previous` → 後続手順の開始条件エラー
  - `manual step must use execution_mode=manual_confirm` → 人ステップ実行方法エラー
  - `execution_mode=auto requires timer_minutes ...` → 自動実行タイマー範囲エラー
  - `browser step requires a valid target_url` → Browser遷移URL必須エラー
  - `agent step requires agent_prompt` → AIプロンプト必須エラー

# リファクタリング提案（洗練・シンプル・堅牢）

## 1. 調査サマリー

本リポジトリは `skills/` を中心に複数スキルを併設する構成で、特に `skills/mfcloud-expense-receipt-reconcile` に機能が集中している。

- スキル構造チェック: `python scripts/check_skill_structure.py --json` の結果、16スキル中1件のみ違反（`skills/playwright` が `scripts/*.py` を持つが `tests/` なし）。
- 大型ファイル集中:
  - `dashboard/routes/api_workspace_routes.py`（3,320行）
  - `dashboard/static/js/workspace.js`（3,129行）
  - `tests/test_dashboard_api.py`（6,474行）

現状でも動作要件は満たしているが、責務集中により「変更コスト」「レビュー難度」「障害切り分け」が上がりやすい。

---

## 2. 優先度付き提案

## P0（最優先）: APIとフロントの責務分割

### 2-1. `api_workspace_routes.py` の分割

**現状課題**
- 設定定数、バリデーション、HTTP処理、バックグラウンドリトライ、通知関連が同居している。
- `Any` を多用し、入力境界の型意図が読み取りにくい。

**提案**
- 以下へ分割し、ルーターを薄くする。
  - `dashboard/routes/workspace/router.py`（FastAPIルート定義のみ）
  - `dashboard/routes/workspace/validators.py`（正規化・入力検証）
  - `dashboard/routes/workspace/retry_worker.py`（再送ワーカー）
  - `dashboard/routes/workspace/notifications.py`（Google Chat連携）
  - `dashboard/routes/workspace/constants.py`（定数集約）

**期待効果**
- 変更差分が小さくなりレビューしやすい。
- 単体テストで副作用領域を独立検証できる。

### 2-2. `workspace.js` のモジュール化

**現状課題**
- DOM操作、LocalStorage、API通信、差分表示、Undo制御が単一IIFEに集中。

**提案**
- `dashboard/static/js/workspace/` 配下に機能分割。
  - `state-store.js`（state + localStorage I/O）
  - `prompt-editor.js`（プロンプト編集/最適化）
  - `links-manager.js`（リンクCRUD/ピン留め）
  - `ui-bindings.js`（イベント接続）
  - `api-client.js`（`/api/workspace/*` 通信）

**期待効果**
- UI不具合の切り分けが高速化。
- 将来のSSE/WS導入時、`api-client.js` 差し替えで影響局所化。

---

## P1（高）: バックエンド/フロント共通ロジックの重複排除

### 3-1. 目的抽出ロジックの重複統合

**現状課題**
- 「目的抽出」相当の正規表現・フォールバックがPython側とJS側で重複。
- 仕様改定時に片方だけ更新され、挙動不一致になりうる。

**提案**
- 仕様を `docs/prompt-goal-extraction-spec.md` で固定化。
- テストベクタを `tests/__tests__/prompt_goal_vectors.json` に集約し、Python/JS双方で同一ベクタ検証。
- 実装は各言語で維持しつつ、「仕様とテスト入力」を単一ソース化。

**期待効果**
- 境界仕様が明文化され、回帰を防止。
- 失敗時フォールバック要件を確実に維持。

### 3-2. API I/Oスキーマ化

**提案**
- FastAPIのrequest/responseをPydanticモデルで明示。
- JS側はレスポンス型ガード（最低限のランタイムバリデーション）を追加。

**期待効果**
- 暗黙仕様の排除。
- 破壊的変更をレビュー時に検知しやすい。

---

## P2（中）: テスト構造の再編（`__tests__` 標準化）

### 4-1. 超巨大テストの分割

**現状課題**
- `tests/test_dashboard_api.py` が非常に巨大で、失敗時の探索コストが高い。

**提案**
- `tests/__tests__/dashboard_api/` に責務別再配置。
  - `test_workspace_api.py`
  - `test_workflow_api.py`
  - `test_retry_worker_api.py`
  - `test_error_contracts.py`
- 共通fixtureは `tests/__tests__/conftest.py` に移動。

**期待効果**
- 失敗箇所の局所化、並列実行効率の改善。
- カバレッジ上の未検証領域が見えやすくなる。

### 4-2. `skills/playwright` への最小テスト追加

**提案**
- `skills/playwright/tests/__tests__/test_run_smoke.py` を追加し、最低1本のimport/smokeを常設。

**期待効果**
- リポジトリ基準（scriptsがあるならtestsあり）と整合。

---

## P3（中〜低）: 運用面の堅牢化

### 5-1. 境界レイヤの規約化

以下を `docs/architecture-boundary-rules.md` に明記。

- parse系は純粋関数（I/O禁止）
- 優先順位決定はサービス層で一元化
- 境界層でデータ変換
- 失敗時フォールバック必須

### 5-2. 定数・設定の集中管理

- 環境変数名、上限値、TTLを `constants.py` に集約。
- 「設定の定義場所」と「参照場所」を1対多に固定し、散逸を防止。

---

## 3. 実行順（2週間の例）

1. **Week 1 前半**: `api_workspace_routes.py` 分割（機能変更なし）
2. **Week 1 後半**: `workspace.js` 分割（機能変更なし）
3. **Week 2 前半**: 目的抽出仕様・テストベクタ統一
4. **Week 2 後半**: `__tests__` 再編と `skills/playwright` 最小テスト追加

---

## 4. 完了判定（Definition of Done）

- 主要巨大ファイルが責務分割され、単一ファイルが1,000行超にならない。
- `python scripts/check_skill_structure.py --strict` が常時成功。
- API契約テストとUIロジックテストが `__tests__` 配下で分類される。
- 目的抽出の仕様テストがPython/JSで同一ベクタを通過する。


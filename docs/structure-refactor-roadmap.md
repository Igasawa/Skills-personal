# リポジトリ構造リファクタリング 実行ガイド

このガイドは、Skillpersonal のディレクトリ構造を壊さずに安全に整理するためのステップ順です。

## 進め方（Step by Step）

### Step 1: ノイズ除去の土台
1. 一時ファイル/生成物を `.gitignore` で除外
   - 対象: `tmp_*`, `_tmp_*`, `workspace_*.js`, `ws.diff`
2. `git status` を見て、未追跡の実験ファイルが増えない状態を確認

### Step 2: `skills` の最低メタ要件を機械チェック
1. `scripts/check_skill_structure.py` を実行して、全 `skills/*` の現状を一覧化
   - メタ情報ファイル (`SKILL.md`/`skill.yaml`/`README.md`) の有無を確認
   - `scripts/*.py` があるスキルで `tests/` が欠けているかを確認
2. 指摘があったスキルのみ個別に分解・追加

### Step 3: 大規模スキルから分離
1. 体積の大きい `skills/mfcloud-expense-receipt-reconcile` を対象に、以下を分離
   - `scripts`（実行ロジック）
   - `dashboard`（UI/API）
   - `tests`（テスト）
   - `references`（知識ベース）
   - `reports`（レポート/成果物）
2. `reports` の内容が履歴保存用途なら retention ルールを決め、必要なら履歴を圧縮保管。

### Step 4: ワークフロー整備
1. `docs/repository` のルールと一致する形で CI を順序化
2. 変更時に `python scripts/check_skill_structure.py` を必須実行項目へ追加

## 実行コマンド
- `python scripts/check_skill_structure.py`
- `python scripts/check_skill_structure.py --json`
- `python scripts/check_skill_structure.py --strict`（CIやPRゲート用）

## 受け入れ条件
- 未追跡の一時生成物が作業ごとに積み上がらない
- `skills/*` のメタ要件が可視化され、欠損が追跡可能
- 大規模スキルの責務分離方針が文書化されている

---

## ローカル実行注意
- `.gitignore` に追加した除外パターンを活用しているため、既存の一時ファイルは再表示されません。
- 実務で必要に応じて除外ルールを緩める場合は、まずこのガイドに追記して運用ルールを揃えてください。

## ステップ4の実行結果（基準スナップショット）
- `skills/*` の現状品質は `docs/skill-structure-baseline.json` に保存しました。
- 以後の変更はこのスナップショットを起点に、差分としてレビューします。

## ステップ5（次アクション）
- `scripts/*.py` があるが `tests/` がないスキルへの最小テスト追加を優先します。
- 追加後、上記スナップショット再生成し、`violations` の減少を確認します。
- `python scripts/check_skill_structure.py --json > docs/skill-structure-baseline.json` を Step完了ごとに実行します。

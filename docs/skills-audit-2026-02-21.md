# Skills監査レポート（2026-02-21）

## 1. 調査サマリ

- 対象: `skills/` 配下のローカル Skill 一式
- 調査観点: 構成整合性（必須ファイル/ディレクトリ）、テスト有無、ドキュメント分割性、運用保守性
- 実施コマンド:
  - `python scripts/check_skill_structure.py`
  - `python` ワンライナー（`SKILL.md` 行数・ディレクトリ構成集計）

### 結論（要約）

- **全16 Skill中15 Skillは構成チェックを通過**し、基礎的な運用可能性は高い。
- 一方で、**`skills/playwright` が `scripts/*.py` を持ちながら `tests/` 欠落**で構成ポリシー違反。
- 大型Skill（`mfcloud-expense-receipt-reconcile`）は機能が豊富だが、`SKILL.md` が長く（319行）運用時の認知負荷が高い。
- テスト配置は現状 `tests/` 方式が中心で、`__tests__` 標準化方針との差分がある。

## 2. 機能性評価

### 2.1 構成健全性

- `scripts/check_skill_structure.py` の結果:
  - `skills: 16`
  - `violations: 1`
- 多くの Skill は `SKILL.md` + `skill.yaml`（必要に応じて）+ `scripts/tests/references/assets` の構成を満たしている。

### 2.2 拡張性・再利用性

- `kintone-*` / `mf-*` / `docs-*` 等、ドメイン単位で Skill が分割されており再利用しやすい。
- `scripts/` と `tests/` が揃っている Skill が多く、運用自動化・回帰検証に向いた設計。

### 2.3 運用実効性

- `README.md` 側で文字コード方針、セットアップ、テスト、運用ガードが整理されており、導入障壁は低い。
- 既存の運用スクリプト群（encodingチェック、safe commit 等）があり、品質管理フローは有効。

## 3. 課題（優先度つき）

### [P1] `skills/playwright` のテスト欠落

- 現状: `scripts/*.py` があるのに `tests/` がないため、構成チェックで唯一NG。
- 影響: 仕様変更時の破壊検知が難しく、メンテコスト増。

### [P2] 大型Skillの説明肥大化

- 対象: `skills/mfcloud-expense-receipt-reconcile/SKILL.md`（319行）。
- 影響: 読み込みコスト増、更新時の差分把握が難化。
- 補足: 500行以内という一般ガイドラインには収まるが、将来的な肥大化予防が必要。

### [P3] テストディレクトリ規約の不一致（`tests/` vs `__tests__/`）

- 現状: Skill群はほぼ `tests/`。
- 方針差分: チーム標準として `__tests__` 方式を採用する場合、将来的な統一方針を決める必要がある。
- 影響: 新規参加者の認知負荷、ツール設定分岐。

## 4. 改善提案

### 提案A（即時）: `skills/playwright` に最小回帰テストを追加

- `tests/test_run.py`（または標準化方針に合わせ `__tests__/`）を追加。
- 少なくとも以下を検証:
  - スクリプト引数のバリデーション
  - エラー時終了コード
  - 代表的成功パス

### 提案B（短期）: 大型Skillの段階的分割（Progressive Disclosure強化）

- `mfcloud-expense-receipt-reconcile/SKILL.md` は概要+導線に寄せ、詳細は `references/` に移す。
- 例:
  - `references/setup.md`
  - `references/troubleshooting.md`
  - `references/runbook.md`
- 効果: 更新容易性・可読性改善、モデル入力コンテキストの最適化。

### 提案C（短期）: テスト配置ポリシーを明文化

- どちらかに統一:
  - 既存互換重視: `tests/` 維持
  - 標準化重視: `__tests__/` へ移行
- 併せて `scripts/check_skill_structure.py` で許容パターンを宣言し、CIで自動検証。

### 提案D（中期）: 監査自動化の拡充

- 現行の構成チェックに加え、次を機械判定:
  - `SKILL.md` 行数閾値（例: 300超で警告）
  - `scripts/` がある Skill のテスト必須
  - frontmatter の `name/description` 品質（空/短すぎ/重複）

## 5. 推奨アクションプラン（30日）

1. Week 1: `skills/playwright` に回帰テスト追加。
2. Week 2: テストディレクトリ規約（`tests` か `__tests__`）を決定。
3. Week 3: `mfcloud-expense-receipt-reconcile` の説明分割PRを作成。
4. Week 4: `check_skill_structure.py` に監査ルールを追加してCI反映。

---

本レポートは、現時点のリポジトリ状態に基づく静的監査結果。

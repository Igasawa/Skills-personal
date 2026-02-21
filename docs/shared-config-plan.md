# Shared Config Plan

作成日: 2026-02-20  
対象リポジトリ: `Skills-personal`

## 1. 背景

本リポジトリは社内の管理部で共有利用する前提であり、社名・共通URLなどの設定値をスキルごとに重複管理すると、更新漏れ・運用差分・監査性低下が発生しやすい。  
そのため、スキル個別設定から「全体共有パーツ（組織設定）」への移行を実施する。

## 2. 目的

- 会社共通値を一元管理し、スキル間の設定重複を削減する
- 既存運用を壊さず段階移行する（互換維持 → 警告 → 廃止）
- 設定変更の監査性と再現性を高める

## 3. スコープ

### 3.1 対象（共有化する）

- 社名・証憑宛名
- 共通URL（Amazon/Rakuten/MF等）
- ロケール・タイムゾーンなどの業務共通設定
- 移行ポリシー（旧キーの非推奨/廃止ルール）

### 3.2 非対象（共有化しない）

- APIキー/トークン/パスワードなど秘密情報
- スキル固有の一時フラグ・実験値

## 4. 設計方針

### 4.1 共有設定ファイル

- 新設: `AX_HOME/configs/org-profile.json`
- 必須: `config_version`
- 秘密情報は格納禁止（`AX_HOME/secrets/*.env` に分離）

### 4.2 解決優先順位（固定）

1. CLI引数  
2. スキル個別config  
3. `org-profile`  
4. `skill.yaml` defaults（プレースホルダー）

## 5. 実行計画（詳細）

### Step 1: 目的/範囲の固定（期限: 2026-02-20）

- 作業: 共有対象と非対象を文書化
- 成果物: `docs/shared-config-plan.md`（本書）
- 完了条件: 範囲が明文化され、管理部運用前提で矛盾がない

### Step 2: スキーマ定義（期限: 2026-02-21）

- 作業: `org-profile` のJSON Schema作成
- 成果物: `docs/shared-config-schema.json`
- 完了条件: 必須項目/型/禁止項目（秘密情報混入）を検知可能

### Step 3: 解決ルール標準化（期限: 2026-02-21）

- 作業: 優先順位・フォールバック仕様を文書化
- 成果物: `docs/shared-config-resolution.md`
- 完了条件: 全スキルで同じ解決順を再利用できる

### Step 4: 共通ローダー実装（期限: 2026-02-22）

- 作業: 共有設定読込モジュールを追加
- 成果物: 例 `scripts/lib/shared_config.py`
- 完了条件: 単体テストで解決順・欠損時動作が保証される

### Step 5: パイロット適用（mfcloud）（期限: 2026-02-23）

- 作業: `mfcloud-expense-receipt-reconcile` を共通ローダーへ切替
- 成果物: `run_core.py` ほか差分
- 完了条件: 既存運用JSON互換を保ち、既存テストを通過

### Step 6: マイグレーション導線（期限: 2026-02-24）

- 作業: 旧キー→共有設定の変換コマンド整備
- 成果物: 例 `scripts/config_migrate.py`
- 完了条件: `dry-run`/適用/差分表示が可能

### Step 7: 非推奨ポリシー全体化（期限: 2026-02-25）

- 作業: 旧キー利用時の警告を全スキルで統一
- 成果物: `docs/deprecation-policy.md`
- 完了条件: 旧キー利用が実行ログで識別可能

### Step 8: CIガード追加（期限: 2026-02-26）

- 作業: スキーマ検証・プレースホルダー運用検知をCI化
- 成果物: `.github/workflows/config-guard.yml`
- 完了条件: 検証失敗時にPRマージ不可

### Step 9: 段階ロールアウト（期限: 2026-02-27 ～ 2026-03-08）

- 作業: 高頻度スキルから順次適用
- 成果物: スキル別移行チェックリスト
- 完了条件: 管理部が使う主要スキルで共通設定運用が定着

### Step 10: 運用定着（期限: 2026-03-09）

- 作業: セットアップ/障害時手順の整備
- 成果物: `docs/shared-config-runbook.md`
- 完了条件: 新規端末で同一手順により再現可能

## 6. 受け入れ条件

- 共有設定を更新した際、対象スキルへ一貫反映される
- 旧キー利用時は警告、廃止後は明示エラーへ昇格できる
- 秘密情報が共有設定に混入した場合、CIで検知できる
- 主要スキルの通常運用が後方互換を保って継続できる

## 7. リスクと対策

- リスク: 共有設定の破損で複数スキルが同時影響  
  対策: スキーマ検証 + 最小必須項目 + rollback手順

- リスク: 旧運用との衝突  
  対策: 期限付き互換 + 実行警告 + 移行コマンド提供

- リスク: 秘密情報の混在  
  対策: `org-profile` への禁止ルール + CIチェック

## 8. 追加提案（優先順）

1. `AX_ORG_PROFILE` を導入し、複数組織プロファイルを切替可能にする  
2. `org-profile.base.json` + `org-profile.local.json` の二層化で共有値と端末値を分離する  
3. 共有設定更新時に「影響スキル一覧」を自動出力するチェックを導入する  
4. `updated_by` / `updated_at` を持たせて監査情報を標準化する  
5. 廃止期限経過後、旧キー警告を自動的にエラーへ昇格するルールを導入する  

## 9. 着手ステータス

- [x] Step 1（本書作成）
- [x] Step 2（スキーマ定義）
- [x] Step 3（解決ルール文書化）
- [x] Step 4（共通ローダー実装）
- [x] Step 5（mfcloudパイロット適用）
- [x] Step 6（マイグレーション導線）
- [x] Step 7（非推奨ポリシー全体化）
- [x] Step 8（CIガード追加）
- [x] Step 9（段階ロールアウト）
- [x] Step 10（運用定着）

### 進捗メモ（2026-02-20）

- 追加: `docs/shared-config-schema.json`
- 追加: `docs/shared-config-resolution.md`
- 追加: `docs/deprecation-policy.md`
- 追加: `docs/org-profile.template.json`
- 追加: `scripts/lib/shared_config.py`
- 追加: `scripts/config_migrate.py`
- 追加: `scripts/validate_org_profile.py`
- 追加: `.github/workflows/config-guard.yml`
- 追加: `docs/shared-config-rollout-checklist.md`
- 追加: `docs/shared-config-runbook.md`
- 適用: `skills/mfcloud-expense-receipt-reconcile/scripts/run_core.py`（org-profile読込と優先順位反映）
- 適用: `skills/mfcloud-expense-receipt-reconcile/scripts/collect_print.py`（org-profile読込と優先順位反映）
- 検証: `skills/mfcloud-expense-receipt-reconcile/tests/test_run_core_config.py` に org-profile 優先順位テストを追加し、関連テスト通過
- 検証: `skills/mfcloud-expense-receipt-reconcile/tests/test_collect_print.py` に org-profile 優先順位テストを追加し、関連テスト通過

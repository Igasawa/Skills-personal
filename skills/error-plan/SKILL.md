---
name: error-plan
description: `skills/mfcloud-expense-receipt-reconcile/reports/error_inbox` の未解決インシデントを分析し、`reports/error_plans/incident_id/` に詳細な復旧計画を作成する。失敗確認、ログ調査、根本原因仮説の整理、実装前の修正計画作成を依頼されたときに使う。これは計画専用スキルで、コード変更は実施しない。
---

# エラープラン

インシデント束から復旧計画を作成し、実行フェーズに引き渡せる状態を作る。

## ワークフロー

1. インシデントを選択する。
- ユーザーから `incident_id` が指定された場合はそれを優先する。
- 指定がない場合は、次の場所から未解決の最新インシデントを選ぶ:
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_inbox`
- キュー確認コマンド:
```powershell
python skills/mfcloud-expense-receipt-reconcile/scripts/error_status.py --json
```

2. 根拠ファイルを次の順で読む。
- `incident.json`
- `status.txt`
- `log_tail.txt`
- `audit_tail.jsonl`
- `context.json`
- 欠損ファイルがあっても処理を止めず、前提不足として明示する。

3. 計画成果物を作る。
- 出力先:
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_plans/<incident_id>/plan.md`
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_plans/<incident_id>/plan.json`
- 形式は `references/workflow.md` のスキーマと例に従う。
- 計画には次を含める:
  - 根拠に紐づく根本原因仮説
  - 優先度付き対応（`P0`, `P1`, `P2`）
  - 正確な検証コマンド
  - ロールバック方針
  - 完了条件

4. インシデント状態を `planned` に更新する。
- `skills/mfcloud-expense-receipt-reconcile/reports/error_inbox/<incident_id>/status.txt` を `planned` に更新。
- `incident.json` の更新項目:
  - `status: "planned"`
  - `plan_path`
  - `planned_at`
  - `updated_at`

5. 実行判断用の要約を返す。
- 上位3アクションを要約する。
- 最初に実行すべきコマンドを明示する。
- 実行承認を明示的に求める:
  - `GO <incident_id>`

## ガードレール

- このスキルは計画専用とし、コード変更を実施しない。
- このスキル内でインシデントをアーカイブしない。
- 計画対象のコード範囲は次に限定する:
  - `skills/mfcloud-expense-receipt-reconcile/**`

---
name: error-exec-loop
description: 明示的な `GO incident_id` 指示を受けた後、`skills/mfcloud-expense-receipt-reconcile/reports/error_inbox` のインシデントに対して承認済み復旧計画を実行する。制限付きリトライ・制限付き実行時間で、解消またはエスカレーションまで自律ループを回す依頼に使用する。
---

# エラー実行ループ

上限付きの修正ループを実行し、インシデントを inbox からクローズする。

## 事前条件

- 明示的なユーザー承認が必須:
  - `GO <incident_id>`
- 既存の計画が必須:
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_plans/<incident_id>/plan.json`
- インシデントフォルダが次に存在すること:
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_inbox/<incident_id>/`

## ループ方針

- `max_loops = 8`
- `max_runtime_minutes = 45`
- `same_error_limit = 3`
- コード変更範囲:
  - `skills/mfcloud-expense-receipt-reconcile/**`

いずれかの上限に到達した場合、結果は `escalated` として終了する。

## 実行ワークフロー

1. インシデントを実行中にする。
- `status.txt` を `running` に更新。
- `incident.json.status` と `incident.json.updated_at` を更新。

2. ループ1回分を実行する。
- `plan.json` から最優先の未対応アクションを選ぶ。
- 最小限のコード/設定変更を適用する。
- 計画記載の検証コマンドを実行する。
- 試行結果を次へ保存:
  - `skills/mfcloud-expense-receipt-reconcile/reports/error_runs/<incident_id>/attempt_XX.json`

3. 試行結果を判定する。
- 検証が通り、対象エラーが再現しなければ `resolved` で終了。
- 同一シグネチャの失敗が続く場合は反復カウンタを増やす。
- 反復カウンタが `same_error_limit` に達したら `escalated` で終了。

4. インシデントをクローズする。
- 成功時:
```powershell
python skills/mfcloud-expense-receipt-reconcile/scripts/error_archive.py --incident-id <incident_id> --result resolved --reason "loop completed"
```
- エスカレーション時:
```powershell
python skills/mfcloud-expense-receipt-reconcile/scripts/error_archive.py --incident-id <incident_id> --result escalated --reason "needs manual intervention"
```

5. 最終サマリを出力する。
- `skills/mfcloud-expense-receipt-reconcile/reports/error_runs/<incident_id>/run_result.json`

## ガードレール

- 破壊的な git コマンドは使わない。
- 自律ループ内で月次締め処理の完了操作を実行しない。
- 認証/セッション/資格情報で詰まった場合は、手動手順を明確にして速やかにエスカレーションする。

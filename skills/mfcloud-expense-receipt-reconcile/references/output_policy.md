# 成果物整理ルール（mfcloud-expense-receipt-reconcile）

## 1. 既定の出力先

`AX_HOME/artifacts/mfcloud-expense-receipt-reconcile/YYYY-MM/`

例: `%USERPROFILE%\.ax\artifacts\mfcloud-expense-receipt-reconcile\2026-01\`

## 2. 必須成果物（毎回確認）

- `reports/missing_evidence_candidates.csv`
- `reports/missing_evidence_candidates.json`
- `reports/monthly_thread.md`
- `reports/audit_log.jsonl`
- `amazon/orders.jsonl`
- `mfcloud/expenses.jsonl`
- `run_config.resolved.json`

## 3. 任意成果物

- `amazon/pdfs/`（Amazon領収書PDF）
- `rakuten/pdfs/`（楽天領収書PDF）
- `debug/`（スクリーンショット・HTML）

## 4. アーカイブ運用（定例）

月次処理の結果は毎月必ずアーカイブし、次回作業前に入力フォルダをクリーン化する。
標準手順は `references/archive_baseline_policy.md` を正本として扱う。

現行運用の実行コマンド（手動実行時）:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\\archive_outputs.ps1" -Year 2026 -Month 1
```

PDFやデバッグ情報も保存する場合は `-IncludePdfs` / `-IncludeDebug` を付ける。
クリーンアップを無効化する場合のみ `-NoCleanup` を付ける。

## 5. クリーンアップポリシー（必須）

- 次回開始前に `manual/inbox/` と `mf_bulk_upload/inbox/` は空にする
- `debug/` は原則クリーンアップ対象（障害調査時のみ一時保持）
- 保管期間の目安は次の通り
- PDFとdebug: 容量を見て必要期間のみ
- CSV/JSON/markdown: 12か月を目安

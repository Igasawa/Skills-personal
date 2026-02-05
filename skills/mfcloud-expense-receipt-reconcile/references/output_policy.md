# 成果物整理ルール（mfcloud-expense-receipt-reconcile）

## 1. 既定の出力先

`AX_HOME/artifacts/mfcloud-expense-receipt-reconcile/YYYY-MM/`

例: `C:\Users\<user>\.ax\artifacts\mfcloud-expense-receipt-reconcile\2026-01\`

## 2. 必須成果物（毎回確認）

- `reports/missing_evidence_candidates.csv`
- `reports/missing_evidence_candidates.json`
- `reports/monthly_thread.md`
- `amazon/orders.jsonl`
- `mfcloud/expenses.jsonl`
- `run_config.resolved.json`

## 3. 任意成果物

- `amazon/pdfs/`（Amazon領収書PDF）
- `rakuten/pdfs/`（楽天領収書PDF）
- `debug/`（スクリーンショット・HTML）

## 4. アーカイブ運用

月次処理の結果を保全したい場合、`scripts/archive_outputs.ps1` を使って
時刻付きのフォルダにコピーする。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\\archive_outputs.ps1" -Year 2026 -Month 1
```

PDFやデバッグ情報も保存する場合は `-IncludePdfs` / `-IncludeDebug` を付ける。

## 5. 破棄ポリシー（推奨）

- PDFとdebugは容量が大きいため、月次確認が終わったら削除して良い
- CSV/JSON/markdownは 12 か月分を目安に保持する

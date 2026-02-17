---
name: docs-knowledge-refresh
description: ドキュメントの鮮度（最終確認日・期限切れ・要更新）を定期監査するスキル。Markdown群を走査し、更新期限超過を検出してレポート化する。「この資料が古くないか確認」「ナレッジの定期更新を仕組み化したい」「更新期限を超えたドキュメントを一覧化して」などの依頼で使用。
---

# Docs Knowledge Refresh

## Overview

`scripts/run.py` で Markdown ドキュメントをスキャンし、`最終確認日` などの日付マーカーから鮮度を判定する。  
既定は `--dry-run` で、`--apply --write-report` のときだけレポートファイルを書き出す。

## 監査対象ルール

このスキルは次を優先して日付を読む。

1. YAML frontmatter の `last_verified` / `last_reviewed` / `最終確認日` など  
2. 本文中の `最終確認日: YYYY-MM-DD` / `Last Verified: YYYY-MM-DD`

期限ルールは `docs/knowledge_refresh_registry.json` でファイルごとに上書きできる。

## クイックスタート

```powershell
# 1) 監査（読み取りのみ）
python skills/docs-knowledge-refresh/scripts/run.py `
  --scan docs `
  --registry docs/knowledge_refresh_registry.json `
  --fail-on-stale

# 2) 監査＋レポート出力（AX_HOME/reports/knowledge_refresh）
python skills/docs-knowledge-refresh/scripts/run.py `
  --scan docs `
  --registry docs/knowledge_refresh_registry.json `
  --write-report `
  --apply
```

## JSON I/O（標準入口）

`scripts/run.py` は `config/params` JSON を受け取り、`status/data/error` を返す。

入力例:
```json
{
  "config": {
    "dry_run": true,
    "targets": { "paths": ["docs"], "extensions": [".md"] },
    "policy": { "default_max_age_days": 30, "warn_within_days": 7 },
    "registry": { "path": "docs/knowledge_refresh_registry.json" }
  },
  "params": {
    "fail_on_stale": true
  }
}
```

主な出力:
- `data.summary.stale`: 期限切れ件数
- `data.stale_items[]`: 更新対象の詳細
- `data.warning_items[]`: 期限接近
- `data.report.path`: `--apply --write-report` 時のレポートパス

## 定期実行例（Windows Task Scheduler）

```powershell
schtasks /Create /F /SC WEEKLY /D MON /TN "AX-Knowledge-Refresh" /TR "powershell -NoProfile -ExecutionPolicy Bypass -Command `"cd C:\Users\Tatsuo-2023\Projects\Skills; python skills/docs-knowledge-refresh/scripts/run.py --scan docs --registry docs/knowledge_refresh_registry.json --fail-on-stale --write-report --apply`""
```

## 運用のコツ

1. 外部仕様に依存する資料は `最終確認日` と出典 URL を必ず記載する  
2. 期限が短い資料（価格/API/UI変更が多いもの）は `registry` で `max_age_days` を短くする  
3. CI や定期タスクでは `--fail-on-stale` を付け、期限切れを見逃さない

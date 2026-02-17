---
name: kintone-record-crud
description: kintone アプリのレコードを追加/更新/アップサートする基本スキル。入力（フィールドコードと値）を固定し、`--dry-run` で事前確認してから `--apply` で書き込みを行う。「kintoneのアプリにレコード追加」「このレコードを編集」「キーでupsertして更新」などの依頼で使用。
---

# kintone レコード作成/編集（基本）

このスキルは kintone REST API でレコードの基本操作（追加/更新/upsert）を行う。

## 安全運用

- 既定は `--dry-run`（書き込みしない）
- 書き込みは `--apply` が必要
- secrets は必ず `AX_HOME/secrets/kintone.env` に置く（リポジトリに置かない）

## 認証（優先順位）

1. `KINTONE_USERNAME` / `KINTONE_PASSWORD`（推奨）
2. `KINTONE_API_TOKEN`（必要な場合）
3. Playwright storage_state（`AX_HOME/sessions/kintone.storage.json`）

## レコード入力形式

2種類をサポートする。

1) “kintone形式”の record:
```json
{
  "field_code": { "value": "text" },
  "amount": { "value": 1000 }
}
```

2) “simple形式”の dict（`--simple` 指定時に自動変換）:
```json
{
  "field_code": "text",
  "amount": 1000
}
```

注意:
- PowerShell から `--record` でJSON文字列を渡すと、クォートが崩れるケースがあるため `--record-file` を推奨。
- `--record-file` は UTF-8(BOMあり) でも読み取れる。

## 実行例

### 1) 追加（dry-run）
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-record-crud/scripts/run.py --app-id 28 --action add --record-file .\\input_record.json --simple --dry-run
```

### 2) 追加（apply）
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-record-crud/scripts/run.py --app-id 28 --action add --record-file .\\input_record.json --simple --apply
```

### 3) 更新（record_id指定）
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-record-crud/scripts/run.py --app-id 28 --action update --record-id 123 --record '{"memo":"updated"}' --simple --apply
```

### 4) upsert（ユニークキーで更新/なければ作成）
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-record-crud/scripts/run.py --app-id 28 --action upsert --update-key-field customer_code --update-key-value C001 --record '{"memo":"x"}' --simple --apply
```

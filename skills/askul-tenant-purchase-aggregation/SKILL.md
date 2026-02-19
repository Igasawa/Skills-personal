---
name: askul-tenant-purchase-aggregation
description: アスクル購入CSVをテナント（部署/拠点）単位で集計し、金額・件数を返却する。
---

# アスクル 購入履歴テナント集計

このスキルは、アスクルの購入明細CSVを入力に、テナント名単位で集計を行い、テナント別金額・件数を算出します。

## 1. 事前確認（必要）
- このスキルが使う公式情報の確認ルールは `docs/askul_purchase_aggregation_knowledge.md` を参照してください。
- アスクルCSV自体にテナントIDが直接載らない場合があるため、実運用では「規約化されたテナント識別キー」を商品名・備考・コメント側に埋めるか、`tenant_rules`/`tenant_map`で事前ルール化してください。

## 2. 実行

```powershell
# 1) ドライラン（実行はしない）
python skills/askul-tenant-purchase-aggregation/scripts/run.py `
  --csv-path "C:\work\askul_purchase.csv" `
  --dry-run

# 2) ルールを指定してドライラン
python skills/askul-tenant-purchase-aggregation/scripts/run.py `
  --csv-path "C:\work\askul_purchase.csv" `
  --tenant-default "UNKNOWN" `
  --tenant-rule "営業部:在庫:営業" `
  --tenant-rule "開発部:DEV" `
  --tenant-rule "本部:本部" `
  --apply

# 3) tenant_map.json を使う
python skills/askul-tenant-purchase-aggregation/scripts/run.py `
  --csv-path "C:\work\askul_purchase.csv" `
  --tenant-map ".\tenant_map.json" `
  --apply
```

## 3. パラメータ
- `--csv-path`（必須）
  - アスクルCSVのパス
- `--mode aggregate|validate`
  - `aggregate`（既定）: 集計実行
  - `validate`: 列有無/変換失敗だけを検証
- `--amount-column`
  - 金額列名。既定は自動推定。
- `--date-column`
  - 日付列名。指定がなければ候補から推定。
- `--item-column`, `--comment-column`
  - 明細名・備考列名。分類精度向上用。
- `--tenant-column`
  - CSVに直接テナント列がある場合に指定。
- `--tenant-default`
  - 未分類時の既定テナント名。
- `--tenant-rule "tenant:pattern[:field1,field2,...]"`
  - ルール追加。patternは正規表現可。fieldは未指定なら商品名/コメント/備考を対象。
- `--tenant-map <path>`
  - JSONで `tenant_default` / `tenant_column` / `rules` を一括指定。
- `--min-tenant-confidence`
  - ルール一致の最低信頼度（0.0〜1.0）。既定: 0.6
- `--min-date`, `--max-date`
  - 集計対象期間（YYYY-MM-DD）
- `--dry-run` / `--apply`
  - `--dry-run`（既定）: 集計JSONのみ（ファイル未作成）
  - `--apply`: レポートCSV/JSONを `AX_HOME/reports/askul_tenant_purchase` に出力
- `--output-dir`
  - 出力先上書き

## 4. tenant_map.json 例

```json
{
  "tenant_default": "UNKNOWN",
  "tenant_column": "",
  "rules": [
    { "tenant": "営業部", "pattern": "営業", "fields": ["商品名", "備考"] },
    { "tenant": "開発部", "pattern": "DEV-", "fields": ["商品名"] },
    { "tenant": "本部",   "pattern": "本部", "fields": ["コメント"] }
  ]
}
```

## 5. 出力
- JSON標準: `status/data/error`
- `--apply`時:
  - `AX_HOME/reports/askul_tenant_purchase/tenant_summary_YYYYMMDD_HHMMSS.csv`
  - `AX_HOME/reports/askul_tenant_purchase/tenant_summary_YYYYMMDD_HHMMSS.json`
  - `--include-item-breakdown`時: `tenant_item_breakdown_YYYYMMDD_HHMMSS.csv`

## 6. 注意
- テナントキーがCSVに無い場合は、ルール誤分類防止のため運用側でテナント識別キーのルールを固定してください。
- 返却JSONの`warnings`に未分類・日付不一致等が出るため、異常値がある場合は自動保存前に確認してください。

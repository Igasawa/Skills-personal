# Shared Config Resolution Rule

更新日: 2026-02-20

## 目的

共有設定（`org-profile`）とスキル個別設定が混在しても、毎回同じ優先順位で解決されるようにする。

## 解決優先順位（高い順）

1. CLI引数
2. スキル個別config（`AX_HOME/configs/<skill>.json` または `--input`）
3. 共有config（`AX_HOME/configs/org-profile.json`）
4. `skill.yaml` defaults（プレースホルダー含む）

## 代表キーの解決例

### 宛名（領収書名義）

- 解決順:
  1. `--receipt-name`
  2. `config.tenant.receipt.name`
  3. `config.receipt_name`（互換）
  4. `org-profile.organization.receipt.name`
  5. `skill.yaml` / コード既定値

### URL

- Amazon注文履歴:
  1. `--amazon-orders-url`
  2. `config.tenant.urls.amazon_orders`
  3. `config.urls.amazon_orders`（互換）
  4. `org-profile.urls.amazon_orders`
  5. 既定URL

### テナント名

- 解決順:
  1. `config.tenant.name`
  2. `config.tenant_name`（互換）
  3. `org-profile.organization.name`
  4. 宛名解決結果
  5. `default`

## 非推奨キーの扱い

- 旧キー（例: `config.receipt_name`, `config.urls.*`）は互換のため一時的に読込む。
- 実際に旧キーが採用された実行では、警告を出す。
- 廃止目標日以降は段階的に error 化する。

## ガード方針

- プレースホルダー値（`YOUR_COMPANY_NAME` など）のまま通常実行する場合は error で停止する。
- ただし `--dry-run` や `--skip-receipt-name` の場合はガード対象外とする。

# Deprecation Policy

更新日: 2026-02-20

## 目的

共有設定移行時に、旧キーの利用を安全に段階廃止する。

## 対象

- `config.receipt_name`
- `config.receipt_name_fallback`
- `config.urls.*`
- `config.rakuten.orders_url`
- `config.tenant_name`
- `config.tenant_key`

## フェーズ

1. `warning` フェーズ（開始: 2026-02-20）
- 旧キーが実際に採用された実行のみ警告を出す
- 既存運用は継続可能

2. `strict warning` フェーズ（予定: 2026-04-01）
- CIで旧キー利用を検知して警告を集約
- 週次レポートで未移行箇所を可視化

3. `error` フェーズ（廃止目標: 2026-06-30）
- 旧キー採用時は実行エラー
- 移行完了を必須化

## 実行ルール

- 新規設定追加時は `org-profile` と `config.tenant.*` のみを使う
- 旧キーは新規ドキュメントに記載しない
- 旧キー修正を行う場合は、同一PRで移行先キーも更新する

## 監査

- 実行ログで `resolved_sources` を記録し、旧キー採用有無を追跡する
- 月次で未移行キー件数をレビューする

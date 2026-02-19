---
name: mf-accounting-csv-export
description: マネーフォワード クラウド会計のCSV運用（ダウンロード後の検証・正規化・分析前チェック）を標準化するスキル。「MFクラウド会計のCSVを検証したい」「文字コードを揃えたい」「欠損列や日付範囲をチェックしたい」などの依頼で使用。
---

# MFクラウド会計 CSV運用スキル

このスキルは、マネーフォワード クラウド会計から出力した CSV を、分析前に安全に検証するための標準入口です。

ポイント:
- 既定は `--dry-run`（読み取りのみ）
- 実行系（監視待ち、Playwright ダウンロード、レポート/正規化ファイル書き出し）は `--apply`
- 文字コード自動判定（`utf-8-sig` / `utf-8` / `cp932` / `shift_jis`）
- 列存在チェック、必須列の空値チェック、日付形式、日付範囲、金額列の数値検証
- 帳票ごとの列契約プリセットを搭載（`--preset`）

## クイックスタート

```powershell
# 1) 既存CSVを検証（読み取りのみ）
python skills/mf-accounting-csv-export/scripts/run.py `
  --csv-path "C:\work\mf\journal.csv" `
  --required-column "取引No" --required-column "取引日" --required-column "金額(円)" `
  --non-empty-column "取引No" --non-empty-column "取引日" --non-empty-column "金額(円)" `
  --dry-run
```

```powershell
# 2) CSVを検証し、UTF-8正規化ファイルとJSONレポートを出力
python skills/mf-accounting-csv-export/scripts/run.py `
  --csv-path "C:\work\mf\journal.csv" `
  --apply
```

```powershell
# 3) ダウンロードフォルダを監視して新規CSVを検証（手動エクスポート運用）
python skills/mf-accounting-csv-export/scripts/run.py `
  --mode watch `
  --watch-dir "$env:USERPROFILE\Downloads" `
  --timeout-seconds 300 `
  --apply
```

```powershell
# 4) MF画面を開いて半自動でCSVダウンロード→そのまま検証
# 事前に storage_state を作成:
# powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 playwright login --name mf-accounting --url "https://biz.moneyforward.com/"
python skills/mf-accounting-csv-export/scripts/run.py `
  --mode download `
  --download-url "https://biz.moneyforward.com/" `
  --preset journal_plus `
  --apply
```

```powershell
# 5) 利用可能な帳票プリセットを確認
python skills/mf-accounting-csv-export/scripts/run.py --list-presets
```

## 入出力

標準入口は `scripts/run.py`。  
JSON入力（`config` / `params`）またはCLI引数を受け取り、`status/data/error` の JSON を返します。

主なパラメータ:
- `--csv-path`: 検証対象CSV
- `--mode validate|watch|download`（動作モード）:
  - `validate`: 指定CSVを検証
  - `watch`: 新規CSV出現待ち
  - `download`: Playwrightで画面を開いてCSVダウンロード待機（セッション再利用）
- `--preset`: 列契約プリセット（例: `journal_standard`, `journal_plus`, `general_ledger_plus`, `trial_balance_plus_core`, `transition_plus_core`）
- `--required-column`: 存在必須の列（複数指定可）
- `--non-empty-column`: 値が空でないことを要求する列（複数指定可）
- `--date-column`: 日付検証対象列（既定: `取引日`）
- `--amount-column`: 数値検証対象列（複数指定可）
- `--download-url`: ダウンロード画面URL
- `--session-name` / `--storage-state`: Playwright セッション指定
- `--min-date` / `--max-date`: 許容日付範囲（`YYYY-MM-DD`）
- `--dry-run` / `--apply`: 安全実行フラグ

## 運用前提

- 認証情報はリポジトリに置かない（`AX_HOME` 配下で管理）
- 本スキルはCSVの検証・正規化を担い、MF画面でのログイン/ダウンロード操作は手動または別自動化で実施

## 参照

- 契約仕様: `docs/mf_cloud_accounting_csv_contract.md`
- 公式の更新は定期的に見直す（変更があり得るため）

---
name: mfcloud-expense-receipt-reconcile
description: MFクラウド経費の経費明細（証憑未添付）と、Amazon.co.jp（個人）/楽天市場の注文履歴から取得した領収書/購入明細PDFを突き合わせて候補を提示するスキル。「MFクラウド経費 証憑 未添付」「Amazon 領収書 PDF 先月」「楽天 領収書 PDF」「経費精算 証憑 突き合わせ」などの依頼で使用。
---

# MFクラウド経費：Amazon/楽天領収書PDF一括取得＋未添付突き合わせ（MVP）

Amazon.co.jp（個人）/楽天市場の注文履歴から「領収書/購入明細ページ」をPDF化して保存し、MFクラウド経費（経費明細一覧）の証憑未添付明細と突き合わせて、候補PDFをランキングして出力する。

## 重要（秘密情報）

- ログイン情報は **リポジトリに置かない**（`AX_HOME` 配下のみ）
- SSO/MFA 前提で **storage_state 再利用**（`AX_HOME/sessions/*.storage.json`）

## セットアップ（初回のみ）

```powershell
# ランタイムディレクトリ作成（~/.ax）
$env:AX_HOME = "$env:USERPROFILE\\.ax"
New-Item -ItemType Directory -Force -Path "$env:AX_HOME\\sessions" | Out-Null

# Playwrightブラウザ導入（大きいDLが入る）
npx playwright install chromium

# 手動ログイン→セッション保存
npx playwright open -b chromium "https://www.amazon.co.jp/gp/your-account/order-history" --save-storage "$env:AX_HOME\\sessions\\amazon.storage.json"
npx playwright open -b chromium "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order" --save-storage "$env:AX_HOME\\sessions\\rakuten.storage.json"
npx playwright open -b chromium "<貴社のMFクラウド経費URL>" --save-storage "$env:AX_HOME\\sessions\\mfcloud-expense.storage.json"
```

## クイックスタート

`config.tenant.urls.mfcloud_expense_list` は環境ごとに異なるため、**必ず指定**する（経費明細一覧URL）。

```powershell
Set-Location c:\Users\TatsuoIgasawa\.vscode\Skillpersonal\skills\mfcloud-expense-receipt-reconcile

# 例: 2026-01 を実行（通常運用は先月がデフォルト）
python scripts/run.py --year 2026 --month 1 --mfcloud-expense-list-url "<経費明細一覧URL>" --notes "出張多め・特定PJ集中"
```

### 楽天を有効化

```powershell
python scripts/run.py --year 2026 --month 1 --mfcloud-expense-list-url "<経費明細一覧URL>" --enable-rakuten `
  --rakuten-orders-url "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order"
```

`--input` を省略した場合、`AX_HOME/configs/mfcloud-expense-receipt-reconcile.json` が存在すれば自動で読み込む。

### 領収書の宛名

Amazon領収書の宛名は既定で **「株式会社ＨＩＧＨ－ＳＴＡＮＤＡＲＤ＆ＣＯ．」** を設定する。変更する場合は `--receipt-name` を指定する。

```powershell
python scripts/run.py --year 2026 --month 1 --mfcloud-expense-list-url "<経費明細一覧URL>" --receipt-name "株式会社ＨＩＧＨ－ＳＴＡＮＤＡＲＤ＆ＣＯ．"
```

宛名が入力できない場合は半角表記にフォールバックする（既定：`株式会社HIGH-STANDARD&CO.`）。明示指定は `--receipt-name-fallback`。

### テナント設定（推奨）

会社/部署ごとの設定は `config.tenant` にまとめる。既存の `config.receipt_name` / `config.urls.*` も互換のため読み込む。

```json
{
  "config": {
    "tenant": {
      "key": "corp-a",
      "name": "株式会社Example",
      "receipt": {
        "name": "株式会社Example",
        "name_fallback": "Example Inc."
      },
      "urls": {
        "amazon_orders": "https://www.amazon.co.jp/gp/your-account/order-history",
        "rakuten_orders": "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order",
        "mfcloud_accounts": "https://expense.moneyforward.com/accounts",
        "mfcloud_expense_list": "https://expense.moneyforward.com/..."
      }
    }
  }
}
```

### 認証で詰まった場合（引継ぎ）

`--interactive` を付けて実行すると、ログイン画面が出たタイミングで **ユーザーに引き継いでログイン** できる。

```powershell
python scripts/run.py --year 2026 --month 1 --mfcloud-expense-list-url "<経費明細一覧URL>" --interactive
```

## 登録済み領収書の一括取得・一括印刷（MVP）

前月分の **Amazon/Rakuten ローカルPDF** を集めて、印刷用リスト/スクリプトを作成する。

1) 一括印刷リスト作成
```powershell
python scripts/collect_print.py --year 2026 --month 1
```

2) 一括印刷（OSの既定アプリで印刷）
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\<user>\.ax\artifacts\mfcloud-expense-receipt-reconcile\2026-01\reports\print_all.ps1"
```

出力:
- `reports/print_manifest.json`：印刷対象ファイル一覧
- `reports/print_list.txt`：ファイルパス一覧
- `reports/print_all.ps1`：一括印刷スクリプト

※ 画像(JPG/PNG)はそのまま保存し、PDF変換は行わない。  
※ MF添付証憑は**デフォルトで印刷対象外**。必要なら `--download-mfcloud --include-mfcloud --interactive` を指定。

### ドライラン（オフライン突き合わせ）

すでに `output_root/amazon/orders.jsonl` と `output_root/mfcloud/expenses.jsonl` がある場合、ブラウザ操作なしで突き合わせだけ実行できる。

```powershell
python scripts/run.py --year 2026 --month 1 --dry-run --output-dir "C:\Users\<user>\.ax\artifacts\mfcloud-expense-receipt-reconcile\2026-01"
```

## 出力

既定の `output_root`:

`AX_HOME/artifacts/mfcloud-expense-receipt-reconcile/YYYY-MM/`

- `amazon/pdfs/`：領収書PDF
- `amazon/orders.jsonl`：注文メタデータ
- `mfcloud/expenses.jsonl`：明細メタデータ
- `reports/missing_evidence_candidates.csv`：未添付明細→候補PDF一覧
- `reports/missing_evidence_candidates.json`：同内容のJSON
- `reports/monthly_thread.md`：月次処理スレッド用の下書き（テンプレ出力）
- `reports/audit_log.jsonl`：実行・確認・印刷などの操作監査ログ

## トラブルシュート

- storage_state の期限切れ：`scripts/ax.ps1 playwright login --name amazon` / `--name mfcloud-expense` をやり直す
- MFの画面構造が違う：`--mfcloud-expense-list-url` を「経費明細一覧」かつ「一覧が表示される状態」のURLにする（フィルタ付きURL推奨）
- AmazonのUIが変わった：`output_root/debug/` のスクリーンショット/HTMLを確認し、抽出ロジックを更新する

## テスト（開発者向け）

```powershell
Set-Location c:\Users\TatsuoIgasawa\.vscode\Skillpersonal\skills\mfcloud-expense-receipt-reconcile
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## 成果物整理（任意）

同月の成果物を時刻付きでアーカイブする場合は次を使う（既定で入力フォルダをクリーンアップする）。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\\archive_outputs.ps1" -Year 2026 -Month 1
```

PDFやデバッグ情報も残す場合:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\\archive_outputs.ps1" -Year 2026 -Month 1 -IncludePdfs -IncludeDebug
```

クリーンアップを無効化する場合:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\\archive_outputs.ps1" -Year 2026 -Month 1 -NoCleanup
```

## ダッシュボード（ローカル）

成果物の可視化と実行依頼ができるローカルUI。

```powershell
Set-Location c:\Users\TatsuoIgasawa\.vscode\Skillpersonal\skills\mfcloud-expense-receipt-reconcile
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_dashboard.ps1"
```

ブラウザで `http://127.0.0.1:8765/` を開く。

オプション例:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_dashboard.ps1" -NoOpen
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_dashboard.ps1" -BindHost 127.0.0.1 -Port 8765 -WaitSeconds 120
```

### 実行パターン

- Amazonのみ（印刷準備まで自動、プリントアウト実行は手動）
- 楽天のみ（印刷準備まで自動、プリントアウト実行は手動）
- MF抽出+突合（既存の `orders.jsonl` が必要）

※ ダッシュボードAPIはワークフロー順序を検証し、順序外の実行依頼は `409 Workflow order violation` で拒否する。
※ 印刷フローの統一方針は `references/operation_policy.md` の「8. 印刷フロー統一ポリシー」を参照。

## 運用ルール（参照）

- 恒久ルール：`references/operation_policy.md`
- 月次アーカイブ基本設定：`references/archive_baseline_policy.md`
- フェーズ計画：`references/roadmap.md`
- 自動登録OK例外一覧：`references/auto_register_exceptions.yaml`
- 月次スレッドテンプレ：`assets/monthly_thread_template.md`
- 成果物整理ルール：`references/output_policy.md`
- Webフォーム実装は「調査 → 計画 → 実装 → 検証」を標準手順とする（`references/operation_policy.md` の「10. Webフォーム実装の調査・計画先行ルール」）

## UI言語方針

- ダッシュボードのエンドユーザー向けUI文言（見出し、ボタン、説明、トースト、エラー表示）は、原則として日本語に統一する。
- ダッシュボードの文言は、機能に合う内容を短く平易に書き、できるだけわかりやすくシンプルにする。
- 英語を許容するのは、コード識別子・APIキー・ログ解析用の固定判定文字列など、機械処理上必要な箇所のみ。
- UI文言を追加・変更する際は、日本語表示になっていることを確認してから反映する。

## Official manual review (automated)
- Run periodic checks: `python scripts/review_official_manual.py --review-type weekly`
- Monthly run: `python scripts/review_official_manual.py --review-type monthly --max-age-days 30`
- Use PowerShell wrapper: `pwsh -File scripts\review_official_manual.ps1 -ReviewType weekly`
- Output log: `references/review_logs/official_manual_review_<review_type>_YYYY-MM-DD_HHMMSS.md`
- Always align findings into `references/official_manual_alignment_notes.md` and `references/official_manual_knowledge.yaml`.
- CI workflow: `.github/workflows/official-manual-review.yml`
  - defaults to `review_type=weekly`, `max_age_days=14`, `skip_url_check=true`
  - manual run can override these fields from workflow_dispatch inputs

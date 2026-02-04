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

`config.urls.mfcloud_expense_list` は環境ごとに異なるため、**必ず指定**する（経費明細一覧URL）。

```powershell
Set-Location c:\Users\Tatsuo-2023\Projects\PersonalSkills\skills\mfcloud-expense-receipt-reconcile

# 例: 2026-01 を実行（通常運用は先月がデフォルト）
python scripts/run.py --year 2026 --month 1 --mfcloud-expense-list-url "<経費明細一覧URL>" --notes "出張多め・特定PJ集中"
```

### 楽天を有効化（私用除外: 支払い方法の許可リスト）

楽天は **支払い方法の許可リスト** で私用を除外する。許可リストが空の場合は **全件フィルタ** される（安全側）。

```powershell
python scripts/run.py --year 2026 --month 1 --mfcloud-expense-list-url "<経費明細一覧URL>" --enable-rakuten `
  --rakuten-allow-payment-methods "楽天ビジネスカード,法人カード" `
  --rakuten-orders-url "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order"
```

`--input` を省略した場合、`AX_HOME/configs/mfcloud-expense-receipt-reconcile.json` が存在すれば自動で読み込む。

### 領収書の宛名

Amazon領収書の宛名は既定で **「株式会社ＨＩＧＨ－ＳＴＡＮＤＡＲＤ＆ＣＯ．」** を設定する。変更する場合は `--receipt-name` を指定する。

```powershell
python scripts/run.py --year 2026 --month 1 --mfcloud-expense-list-url "<経費明細一覧URL>" --receipt-name "株式会社ＨＩＧＨ－ＳＴＡＮＤＡＲＤ＆ＣＯ．"
```

宛名が入力できない場合は半角表記にフォールバックする（既定：`株式会社HIGH-STANDARD&CO.`）。明示指定は `--receipt-name-fallback`。

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

## トラブルシュート

- storage_state の期限切れ：`scripts/ax.ps1 playwright login --name amazon` / `--name mfcloud-expense` をやり直す
- 楽天で私用が混じる：`--rakuten-allow-payment-methods` を設定（未設定なら全件フィルタされる）
- MFの画面構造が違う：`--mfcloud-expense-list-url` を「経費明細一覧」かつ「一覧が表示される状態」のURLにする（フィルタ付きURL推奨）
- AmazonのUIが変わった：`output_root/debug/` のスクリーンショット/HTMLを確認し、抽出ロジックを更新する

## 運用ルール（参照）

- 恒久ルール：`references/operation_policy.md`
- 自動登録OK例外一覧：`references/auto_register_exceptions.yaml`
- 月次スレッドテンプレ：`assets/monthly_thread_template.md`

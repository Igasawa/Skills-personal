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
- `workflow：経費精算（複製）` 画面を含むすべてのダッシュボード表示項目は、既定で日本語表示とする。

## 公式マニュアルレビュー（自動実行）
- 定期チェック実行: `npm run review:manual -- --review-type weekly`
- 実行場所はリポジトリルートでよい（スクリプトは既定で `skills/mfcloud-expense-receipt-reconcile/references/...` を参照）
- 月次実行: `npm run review:manual -- --review-type monthly --max-age-days 30`
- URL確認の再試行を有効化する場合: `npm run review:manual -- --review-type weekly --url-retries 2 --url-retry-delay-seconds 1.5`
- PowerShellラッパー: `pwsh -File scripts\review_official_manual.ps1 -ReviewType weekly`
- 出力ログ: `references/review_logs/official_manual_review_<review_type>_YYYY-MM-DD_HHMMSS.md`
- 指摘事項は必ず `references/official_manual_alignment_notes.md` と `references/official_manual_knowledge.yaml` の両方へ反映する
- CIワークフロー: `.github/workflows/official-manual-review.yml`
  - 既定値: `review_type=weekly`, `max_age_days=14`, `skip_url_check=true`
  - 手動実行時は workflow_dispatch の inputs で上書き可能

## Official manual review（月次運用テンプレ）
- 1. 月初1営業日: `Set-Location C:\Users\...\Skillpersonal` で実行環境に移動
- 2. 月次実行（参照日更新チェックを30日上限で確認）:
  - `npm run review:manual -- --review-type monthly --max-age-days 30`
  - オプションでURL疎通も確認する場合: `npm run review:manual -- --review-type monthly --max-age-days 30 --url-retries 3 --url-retry-delay-seconds 2`
- 3. レポート確認:
  - `knowledge_alignment.in_sync` が `true` か
  - `knowledge.stale` / `alignment_notes.stale` が `false` か
  - `missing_in_targets` / `extra_in_targets` が空か
- 4. 差分がある場合:
  - `official_manual_knowledge.yaml` と `official_manual_alignment_notes.md` のURL一覧・最終レビュー日を更新
  - `--json` 付きで再実行して再チェック
  - `last_reviewed` を更新（2ファイルとも）
- 5. 成果物保存:
  - 当日分ログの有無を確認し、必要ならチケット/月次ノートへサマリ連携
  - コード変更があれば通常運用の更新手順に従い PR 対応

## Official manual review（knowledge_alignment差分対応フロー：3ステップ）
- 1) 検知
  - `npm run review:manual -- --review-type weekly --json` 実行時に `knowledge_alignment.in_sync=false` を起点に抽出。
  - 先に `status_check` 単位 (`manual` / `internal_scraping_target`) の差分を確認する。
- 2) 対応先確定
  - `missing_in_targets` が出たURLは `references/official_manual_knowledge.yaml` に `official_sources` 追加漏れか運用対象追加漏れとして扱う。
  - `extra_in_targets` が出たURLは `references/official_manual_alignment_notes.md` の運用記録（対象範囲）か `CHECK_TARGETS` 側の不要URL混入かを判定する。
  - いずれも対象URLの現況を確認して、更新方針を1文で決定し保存する。
- 3) 通知・再検証
  - 更新先（`official_manual_knowledge.yaml` or `official_manual_alignment_notes.md`）を1件ずつ反映。
  - `last_reviewed` を更新し、同じコマンドを再実行して `knowledge_alignment.in_sync=true` を確認。
  - 差分解消結果と最終確認日時を運用ノートへ通知。

## Official manual review（差分通知テンプレ）
- 月次・週次で差分検知が発生した場合の報告用テンプレを運用ノート/チケットにそのまま貼れるように使う。

```text
[公式マニュアル整合チェック結果]
日付: <YYYY-MM-DD>
実行コマンド: npm run review:manual -- --review-type <weekly|monthly> [--max-age-days N]
結果:
- knowledge_alignment.in_sync: <true/false>
- stale: knowledge=<true/false>, alignment_notes=<true/false>
- status_check別差分:
  - manual: missing_in_targets=<...>, extra_in_targets=<...>
  - internal_scraping_target: missing_in_targets=<...>, extra_in_targets=<...>

対応:
- 対象URL/原因: <要約>
- 更新ファイル:
  - official_manual_knowledge.yaml: <更新有無 + 追加/削除URL>
  - official_manual_alignment_notes.md: <更新有無 + 追加/削除URL>
- 再実行結果: <in_sync=true / false>

最終確認者: <氏名>
最終確認日時: <YYYY-MM-DD HH:mm>
```

## Official manual review（最終更新日ルール）
- `official_manual_knowledge.yaml` と `official_manual_alignment_notes.md` の `last_reviewed` は下記の形式を受け付ける。
  - `last_reviewed: YYYY-MM-DD`（基本形）
  - `last_reviewed = YYYY/MM/DD`（区切り文字の揺れを許容）
  - `最終更新: YYYY-MM-DD`
  - `最終更新日= YYYY-MM-DD`
  - `最終検証日: YYYY-MM-DD`
- 手動更新時は、2ファイルとも上記いずれかで更新し、`weekly/monthly/change_response` の実行後に `stale=false` を確認すること。

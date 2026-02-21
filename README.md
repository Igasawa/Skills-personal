# PersonalSkills

個人用スキルの保管場所。

## UI言語方針

- ダッシュボードのエンドユーザー向けUI文言（見出し、ボタン、説明、トースト、エラー表示）は、原則として日本語に統一する。
- 英語を許容するのは、コード識別子・APIキー・ログ解析用の固定判定文字列など、機械処理上必要な箇所のみ。
- UI文言を追加・変更する際は、日本語表示になっていることを確認してから反映する。
- UIロケールの既定値は `ja`。必要時のみ環境変数 `DASHBOARD_UI_LOCALE` で切り替える（例: `ja`, `en`）。

```powershell
$env:DASHBOARD_UI_LOCALE = "ja"
```

## 文字コード方針（文字化け防止）

- テキストファイルは `UTF-8（BOMなし）` を標準とする。
- 改行は原則 `LF`、`*.ps1` / `*.bat` / `*.cmd` は `CRLF` とする。
- エディタ設定は `/.editorconfig`、Git属性は `/.gitattributes` を正とする。
- UTF-8/BOM違反はテストで検知し、修正後にマージする。

## マージ防止ガード（replacement character 混入対策）

- ローカル: Git hook で文字コード/文字化けテストを必須化する。
- CI: GitHub Actions `Encoding Guard` で同じテストをPR時に実行する。
- ブランチ保護で `Encoding Guard / utf8-and-mojibake-check` を Required に設定すると、失敗時はマージ不可にできる。

```powershell
Set-Location "<Skillpersonal_clone_root>"
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_kil.ps1
```

## ドキュメント運用

- 現行で利用する手順・仕様は `docs/` 直下を参照してください。
- 廃止済み/完了済みの計画書・一時メモは `docs/archive/legacy/` にアーカイブします。
- アーカイブ対象と理由は `docs/archive/README.md` に記録します。

## 収録スキル

- `skills/dashboard-ja-localization/`  
  ダッシュボードUIを日本語化し、`toFriendlyMessage` 翻訳と UTF-8 検証をセットで実施。
- `skills/mfcloud-expense-receipt-reconcile/`  
  Amazon領収書PDFの一括取得 → MFクラウド経費の未添付明細と突き合わせ。

## セットアップ（初回のみ）

PowerShell で実行：

```powershell
# クローン直後の初期セットアップ（AX_HOME, config雛形, 依存インストール）
powershell -NoProfile -ExecutionPolicy Bypass -File .\skills\mfcloud-expense-receipt-reconcile\scripts\bootstrap_from_clone.ps1 `
  -PersistAxHome `
  -InstallDependencies `
  -InstallPlaywrightChromium

# ランタイムディレクトリ作成（~/.ax）
$env:AX_HOME = "$env:USERPROFILE\\.ax"
New-Item -ItemType Directory -Force -Path "$env:AX_HOME\\sessions" | Out-Null

# Playwrightブラウザ導入（大きいDLが入る）
npx playwright install chromium

# 手動ログイン→セッション保存
npx playwright open -b chromium "https://www.amazon.co.jp/gp/your-account/order-history" --save-storage "$env:AX_HOME\\sessions\\amazon.storage.json"
npx playwright open -b chromium "<貴社のMFクラウド経費URL>" --save-storage "$env:AX_HOME\\sessions\\mfcloud-expense.storage.json"
```
- AX_HOME safety guard: bootstrap blocks repository-subdirectory / UNC AX_HOME to avoid cross-user mixing.
- Override only when intentional: `AX_ALLOW_UNSAFE_AX_HOME=1` or `-AllowUnsafeAxHome`.


## 実行例

```powershell
Set-Location "<Skillpersonal_clone_root>\\skills\\mfcloud-expense-receipt-reconcile"
python scripts/run.py --mfcloud-expense-list-url "<経費明細一覧URL>" --notes "出張多め・特定PJ集中"
```

## 設定方針（tenant）

`AX_HOME/configs/mfcloud-expense-receipt-reconcile.json` は `config.tenant` に会社/部署設定をまとめる。
`config.receipt_name` / `config.urls.*` は互換のため読み込まれるが、新規設定は `tenant` を推奨。
`YOUR_COMPANY_NAME` / `YOUR_COMPANY_NAME_FALLBACK` はプレースホルダーなので、運用前に自社値へ置き換える。
プレースホルダーのまま通常実行（Amazon/Rakuten取得）すると、実行時ガードでエラー停止する。

共有設定（`AX_HOME/configs/org-profile.json`）を置いた場合、優先順位は次の通り:
`CLI > スキル個別config > org-profile > skill.yaml defaults`

### 旧設定キーの移行方針（非推奨）

- 非推奨開始日: 2026-02-20
- 廃止目標日: 2026-06-30
- 対象: `config.receipt_name` / `config.receipt_name_fallback` / `config.urls.*` / `config.rakuten.orders_url` / `config.tenant_name` / `config.tenant_key`
- 移行先: `config.tenant.receipt.*` / `config.tenant.urls.*` / `config.tenant.name` / `config.tenant.key`
- 旧キーが実際に採用された実行では、CLI実行時に非推奨警告を表示する

```json
{
  "config": {
    "tenant": {
      "key": "default",
      "name": "YOUR_COMPANY_NAME",
      "receipt": {
        "name": "YOUR_COMPANY_NAME",
        "name_fallback": "YOUR_COMPANY_NAME_FALLBACK"
      },
      "urls": {
        "amazon_orders": "https://www.amazon.co.jp/gp/your-account/order-history",
        "rakuten_orders": "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order",
        "mfcloud_accounts": "https://expense.moneyforward.com/accounts",
        "mfcloud_expense_list": null
      }
    }
  }
}
```

## テスト（開発者向け）

```powershell
Set-Location "<Skillpersonal_clone_root>\\skills\\mfcloud-expense-receipt-reconcile"
python -m pip install -r requirements-dev.txt
python -m pytest -q
npm run check:encoding
```

## 安全コミット運用（文字化け再発防止）

本リポジトリでは、文字化け防止を含む commit/push の再現手順を固定するため、以下を利用してください。

```powershell
# 変更をステージ後
.\scripts\safe_commit_push.ps1 -Message "feat: 変更内容の要約"
```

### 実行内容

- ステージ済み変更があることを確認（未ステージ時は停止）
- `scripts/check_text_encoding.py --scope staged` を実行
- `scripts/check_text_encoding.py --scope tracked` を `scripts/` と dashboard テンプレート/静的資産に対して実行
- commit 後 `git fetch` し、push 先が自分のローカルより進んでいる場合は停止
- `git push`

### 補助オプション

- `-NoPush` : commit のみ
- `-DryRun` : チェックまで実施し、commit/push を行わない
- `-AllowNoStage` : ステージング前でも、ワークツリー差分を対象に文字化けチェックまで実行
- `-CheckOnly` : ワークツリー差分を対象に文字化けチェックのみ実行（commit/push をしない）
- `-SkipScopeCheck` : 追加スコープの再帰チェックを省略
- `-Remote <name>` : push先を明示（既定 `origin`）

### 注意

- `-DryRun` はコミット/プッシュを行いません。`-AllowNoStage` はチェック対象をワークツリー差分に広げるのみで、未ステージでは commit は実行されません（コミットするには `git add` が必要です）。
- 文字化け防止のため、`-CheckOnly` や `-DryRun` で内容を確認した後に、`git add` → commit を行う運用を推奨します。
- この運用は pre-commit/pre-push の両方で文字エンコーディングチェックを行うため、文字化けの再発を抑制します。
- PowerShell でファイルを書き出すときは、`Set-Content/Out-File -Encoding utf8` を使わず、`System.Text.UTF8Encoding($false)`（または `utf8NoBOM`）を使用してください。

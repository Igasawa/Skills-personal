# PersonalSkills

個人用スキルの保管場所。

## UI言語方針

- ダッシュボードのエンドユーザー向けUI文言（見出し、ボタン、説明、トースト、エラー表示）は、原則として日本語に統一する。
- 英語を許容するのは、コード識別子・APIキー・ログ解析用の固定判定文字列など、機械処理上必要な箇所のみ。
- UI文言を追加・変更する際は、日本語表示になっていることを確認してから反映する。

## 文字コード方針（文字化け防止）

- テキストファイルは `UTF-8（BOMなし）` を標準とする。
- 改行は原則 `LF`、`*.ps1` / `*.bat` / `*.cmd` は `CRLF` とする。
- エディタ設定は `/.editorconfig`、Git属性は `/.gitattributes` を正とする。
- UTF-8/BOM違反はテストで検知し、修正後にマージする。

## 収録スキル

- `skills/mfcloud-expense-receipt-reconcile/`  
  Amazon領収書PDFの一括取得 → MFクラウド経費の未添付明細と突き合わせ。

## セットアップ（初回のみ）

PowerShell で実行：

```powershell
# ランタイムディレクトリ作成（~/.ax）
$env:AX_HOME = "$env:USERPROFILE\\.ax"
New-Item -ItemType Directory -Force -Path "$env:AX_HOME\\sessions" | Out-Null

# Playwrightブラウザ導入（大きいDLが入る）
npx playwright install chromium

# 手動ログイン→セッション保存
npx playwright open -b chromium "https://www.amazon.co.jp/gp/your-account/order-history" --save-storage "$env:AX_HOME\\sessions\\amazon.storage.json"
npx playwright open -b chromium "<貴社のMFクラウド経費URL>" --save-storage "$env:AX_HOME\\sessions\\mfcloud-expense.storage.json"
```

## 実行例

```powershell
Set-Location c:\Users\TatsuoIgasawa\.vscode\Skillpersonal\skills\mfcloud-expense-receipt-reconcile
python scripts/run.py --mfcloud-expense-list-url "<経費明細一覧URL>" --notes "出張多め・特定PJ集中"
```

## 設定方針（tenant）

`AX_HOME/configs/mfcloud-expense-receipt-reconcile.json` は `config.tenant` に会社/部署設定をまとめる。
`config.receipt_name` / `config.urls.*` は互換のため読み込まれるが、新規設定は `tenant` を推奨。

```json
{
  "config": {
    "tenant": {
      "key": "default",
      "name": "株式会社ＨＩＧＨ－ＳＴＡＮＤＡＲＤ＆ＣＯ．",
      "receipt": {
        "name": "株式会社ＨＩＧＨ－ＳＴＡＮＤＡＲＤ＆ＣＯ．",
        "name_fallback": "株式会社HIGH-STANDARD&CO."
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
Set-Location c:\Users\TatsuoIgasawa\.vscode\Skillpersonal\skills\mfcloud-expense-receipt-reconcile
python -m pip install -r requirements-dev.txt
python -m pytest -q
npm run check:encoding
```


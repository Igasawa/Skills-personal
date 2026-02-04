# PersonalSkills

個人用スキルの保管場所。

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
Set-Location c:\Users\Tatsuo-2023\Projects\PersonalSkills\skills\mfcloud-expense-receipt-reconcile
python scripts/run.py --mfcloud-expense-list-url "<経費明細一覧URL>" --notes "出張多め・特定PJ集中"
```


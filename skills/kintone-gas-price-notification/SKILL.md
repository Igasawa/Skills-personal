---
name: kintone-gas-price-notification
description: 毎月のガソリン代をgogo.gsから取得し、kintoneスレッドに周知するスキル。「ガソリン代を周知」「今月のガソリン価格をkintoneに投稿」「〇月のガソリン代を通知」などのリクエストで使用。kintoneへの定期投稿テンプレートとしても活用可能。
---

# ガソリン代周知スキル

毎月のガソリン価格をgogo.gsから取得し、kintoneスレッドに投稿するワークフロー。

## クイックスタート（標準実行）

標準入口は `scripts/run.py`。JSON入力（`config`/`params`）を受け取り、JSON結果を返す。

```bash
# 例: 価格を固定して dry-run（外部サイトに依存しない）
python scripts/run.py --year 2026 --month 1 --day 10 --price 170.2 --dry-run
```

## ワークフロー

### 1. ガソリン価格の取得

`scripts/fetch_gas_price.py` を使用して千葉県のレギュラー価格を取得。

```bash
pip install requests beautifulsoup4 --break-system-packages
python scripts/fetch_gas_price.py {年} {月} {日}
```

- 日付はデフォルトで10日
- 10日が404の場合は直近日へフォールバックする（既定: 9日/8日まで）
  - `scripts/run.py` の `--fallback-days` / `params.fallback_days` で調整可能
- URL形式: `https://gogo.gs/news/report/{年}-{月}-{日}`

取得結果（価格）が想定より安い/高い場合は、実際に参照したURL（`scripts/run.py` の出力 `data.source_url`）を開いて確認すること。

### 2. 投稿前preflightチェック（本番投稿の前提）

`scripts/run.py --post` は、本番スレッド投稿の前に以下の sandbox スレッドへ疎通確認コメントを投稿する。

- Space: `https://5atx9.cybozu.com/k/#/space/81`
- Thread: `https://5atx9.cybozu.com/k/#/space/81/thread/131`
- サブドメイン: `5atx9`
- スペースID: `81`
- スレッドID: `131`

preflight 投稿に失敗した場合、本番投稿は実行しない。

```bash
# 既定では preflight 実行後に本番投稿
python scripts/run.py --year 2026 --month 1 --day 10 --post

# 緊急時/または sandbox 単体テスト時のみ preflight を明示スキップ
python scripts/run.py --year 2026 --month 1 --day 10 --post --skip-preflight
```

### 3. kintoneへの投稿

`scripts/post_to_kintone.py` を使用してスレッドにコメント投稿。

**重要**: スペース/スレッドAPIはAPIトークン認証をサポートしていない。
本スキルは「パスワード認証」または「保存済みログインセッション（storage_state）」で投稿する。

**認証情報の優先順位**:
1. 環境変数（設定されていれば自動で使用）
2. 保存済みセッション（`~/.ax/sessions/kintone.storage.json`）
3. 対話入力（`--interactive` 有効時）

```bash
# オプション: 環境変数で事前設定（自動化向け）
export KINTONE_USERNAME="ログイン名"
export KINTONE_PASSWORD="パスワード"

# 環境変数が空の場合は、保存済みセッションへ自動フォールバック
```

**投稿先設定**:
- サブドメイン: `5atx9`
- スペースID: `24`
- スレッドID: `36`

## サンドボックスでの投稿確認（推奨）

このリポジトリの運用ルールとして、各スキルは最低限のアウトプット確認として sandbox のスレッドへの書き込みができるかをチェックしてから本番の動作へ進める。

sandbox スレッド（space=81/thread=131）へ直接投稿して確認したい場合、preflight 先と投稿先が同一になり二重投稿になるため、`--skip-preflight` を付けて 1 回だけ投稿する。

```powershell
# sandbox 単体で「実投稿」確認（preflight も同じスレッドなのでスキップして1回だけ投稿）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-gas-price-notification/scripts/run.py --year 2026 --month 2 --day 10 --space-id 81 --thread-id 131 --post --skip-preflight
```

### 4. コメントフォーマット

```
[{月}月ガソリン代]
お疲れ様です。{月}月ガソリン代の連絡です。よろしくお願いいたします。
ガソリン価格 {価格}円
```

## 誤投稿の削除（取り消し）

誤って投稿した場合は、コメントID（`scripts/run.py` の出力 `comment_id`）を使って
`kintone-thread-comment-cleanup` スキルで削除する。

```powershell
# 例: 本番スレッド（space=24/thread=36）のコメントID=4790 を削除
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-thread-comment-cleanup/scripts/run.py --space-id 24 --thread-id 36 --comment-id 4790 --apply --allow-production
```

## 統合実行例

```python
from scripts.fetch_gas_price import fetch_gas_price
from scripts.post_to_kintone import post_thread_comment

# 価格取得
result = fetch_gas_price(2026, 1, 10)
price = result["price"]

# コメント作成
comment = f"""[1月ガソリン代]
お疲れ様です。1月ガソリン代の連絡です。よろしくお願いいたします。
ガソリン価格 {price}円"""

# kintoneに投稿
post_thread_comment("5atx9", 24, 36, comment)
```

## カスタマイズポイント

このスキルをテンプレートとして他のkintone投稿スキルを作成する場合:

1. **データ取得部分** (`scripts/fetch_gas_price.py`): 取得元サイトとパース処理を変更
2. **投稿先** (`SKILL.md`内の設定): サブドメイン、スペースID、スレッドIDを変更
3. **コメントフォーマット**: 投稿内容のテンプレートを変更

kintone API詳細は `references/kintone_api.md` を参照。

---
name: kintone-thread-comment-cleanup
description: kintoneスペースのスレッドコメントを検索・削除するスキル。「この投稿を消して」「スレッドのコメントを削除」「誤投稿を取り消し」などの依頼に使用。まず sandbox（space=81/thread=131）で dry-run/削除手順を確認してから本番へ。
---

# kintone スレッドコメント削除スキル

kintone のスペーススレッドに投稿されたコメントを、本文マッチまたはコメントID指定で削除する。

## 重要（安全運用）

- 既定は `--dry-run`（削除しない）。削除には `--apply` が必要。
- sandbox で動作確認してから本番へ（本番削除は `--allow-production` が必要）。
- 1件だけ確実に消す場合は `--comment-id` を推奨（`--match-text` は複数件にヒットし得る）。

## クイックスタート

```powershell
# 1) sandbox で候補確認（削除しない）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-thread-comment-cleanup/scripts/run.py --space-id 81 --thread-id 131 --match-text "[AX preflight]" --dry-run

# 2) sandbox で削除（例: comment_id 指定）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-thread-comment-cleanup/scripts/run.py --space-id 81 --thread-id 131 --comment-id 4789 --apply

# 3) 本番で削除（production許可が必須）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-thread-comment-cleanup/scripts/run.py --space-id 24 --thread-id 36 --match-text "ガソリン価格 170.2円" --apply --allow-production
```

## comment_id の入手方法

投稿スキル（例: `kintone-gas-price-notification`）の実行結果JSONに `comment_id` が含まれる。

- 本番投稿: `data.kintone.comment_id`
- preflight 投稿: `data.preflight.comment_id`

この `comment_id` を `--comment-id` に渡して削除する。

## 入出力

標準入口は `scripts/run.py`。JSON入力（`config`/`params`）またはCLI引数を受け取り、JSON結果を返す。

削除対象は以下で指定できる:
- `--comment-id`（複数指定可）
- `--match-text`（本文に含まれる文字列。複数指定可）

## 依存

このスキルは削除操作に Playwright（Python）を使用する。

未導入の場合:
```powershell
python -m pip install --user playwright
python -m playwright install chromium
```

## 生成物（スクリーンショット）

実行時に `output/playwright/` 配下へ `before/after` のスクリーンショットを保存する（gitignore 済み）。

---
name: playwright
description: このリポジトリから Playwright CLI を使って実ブラウザ自動化を実行する。ページ遷移、UIクリック/入力、スナップショット/スクリーンショット取得、ダッシュボードUIフローのデバッグ（`/skill run playwright ...`）が必要なときに使う。
---

# Playwright（リポジトリラッパー）

`scripts/run.py` を Playwright CLI の薄いラッパーとして使う。

## クイックスタート

```powershell
# 1) 環境チェック
python skills/playwright/scripts/run.py --self-check

# 2) 実ブラウザでダッシュボードを開く
python skills/playwright/scripts/run.py open http://127.0.0.1:8765 --headed

# 3) スナップショット取得
python skills/playwright/scripts/run.py snapshot
```

## チャットでの利用

```text
/skill run playwright --self-check
/skill run playwright open http://127.0.0.1:8765/errors?tab=ai-skills --headed
/skill run playwright snapshot
```

## 注意点

- `npx` が PATH に必要。
- `PLAYWRIGHT_CLI_SESSION` が設定されている場合、`--session` 未指定時にラッパーが自動注入する。
- ラッパー独自オプション: `--self-check`, `--timeout-seconds`, `--session`, `--cwd`。

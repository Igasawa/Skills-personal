---
name: kintone-inventory-export
description: kintone にログイン済みセッション（またはID/パスワード）で接続し、アプリ一覧と（アプリに紐づく）スペース情報を収集して JSON で保存・出力する。「kintoneのスペース/アプリ構成を棚卸し」「どんなアプリがあるか調べて」「投稿先追加のために現状把握したい」等の依頼で使用。
---

# kintone アプリ/スペース棚卸し（export）

## できること / 制限

- アプリ一覧: REST API `GET /k/v1/apps.json` で取得（最大100件/回なのでページングして全件取得）
- スペース一覧: 「アプリが属する spaceId」から推定して `GET /k/v1/space.json?id=...` を取得
  - 注意: アプリが1つも紐づかないスペースは、この方法では検出できない可能性がある
  - private space は権限がないと取得に失敗する（失敗は結果JSONに記録して継続）

## 認証（秘密情報をリポジトリに置かない）

優先順位:
1. `KINTONE_USERNAME` / `KINTONE_PASSWORD`（`AX_HOME/secrets/kintone.env` など）
2. Playwright の storage_state（既定: `AX_HOME/sessions/kintone.storage.json`）

storage_state の作成例（手動ログイン）:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 playwright login --name kintone --url "https://5atx9.cybozu.com/k/"
```

## 実行例

```powershell
# secrets を読み込んで実行（推奨）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-inventory-export/scripts/run.py --subdomain 5atx9
```

出力:
- 標準出力: `status/data/error` のJSON
- 既定で `AX_HOME/reports/kintone_inventory/` に JSON を保存（ファイルパスは出力JSONにも入る）

## 使用頻度が低いアプリ/スペースを除外したい場合

「最近N日でレコード更新があったアプリだけ」を対象にできる（スペースは対象アプリに紐づくものだけ推定して残る）。

```powershell
# 例: 直近180日で更新のあるアプリに絞る
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service kintone -- `
  python skills/kintone-inventory-export/scripts/run.py --subdomain 5atx9 --active-within-days 180
```

注意:
- 判定は各アプリの「最新レコードの Updated_datetime」を1件だけ取得して行う。
- 権限不足などで判定できないアプリは結果に `unknown_activity` として記録される（必要なら `--exclude-unknown-activity` で除外）。

## 運用メモ（リポジトリに残す情報）

リポジトリにコミットするのは原則「IDベースの参照（space_id/thread_id/app_id等）」に寄せる。
アプリ名/スペース名など、内部情報を含む棚卸し結果は `AX_HOME` 側に保存する運用を推奨。

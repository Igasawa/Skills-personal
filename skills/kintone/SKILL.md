---
name: kintone
description: "Cybozu kintone 自動化のためのガイダンス。アプリ/レコード設計、REST API 連携、安定運用ワークフローを扱う。"
category: crm, low-code platform, api
dependencies:
  - kintone アプリ管理権限
  - kintone APIトークンまたはユーザー認証
  - HTTPS + JSON 対応クライアント
updated: 2026-02-16
---

# kintone 運用ガイド

## このスキルの用途

kintone のデータ運用を自動化する場合にこのスキルを使う:

- アプリスキーマとフィールド定義の管理
- レコードの安全な登録/更新
- レコード検索とエクスポート
- 外部システムとの連携
- リトライ/可観測性を備えた運用ダッシュボード・同期ジョブ実装

## 主要概念

- **App**: フィールド、レコード、ビュー、フォーム、権限を持つ単位。
- **Record**: フィールドコードとレコードIDをキーにした構造化JSONオブジェクト。
- **Field code**: 連携で最重要のキー。コード不一致が書き込みエラーの最大要因。
- **REST API request scope**: トークン権限は必要最小限かつ対象アプリ/操作に限定する。

## セットアップチェックリスト

1. テナントURL、アプリID、対象フィールドコードを確認する。
2. 最小権限でAPIトークンを作成する。
3. 認証情報は環境変数またはシークレットストアに保存する（インライン記載は禁止）。
4. 次の単一の正本を定義する:
   - app id
   - field mapping
   - sync cursor / last processed timestamp
5. 書き込み前にドライラン相当の読み取り検証を行う。

## 推奨API運用パターン

- タイムアウトとリトライ方針を統一する。
- request ID / response status / error payload を必ず記録する。
- 書き込み操作では:
  - 実行前にペイロードを検証する
  - 盲目的な上書きを避ける
  - 可能な限り冪等にする
- 読み取りはページングし、進捗をチェックポイント化する。

## 例（Python）

```python
import requests

BASE = "https://example.cybozu.com"
APP_ID = "123"
TOKEN = "kintone_api_token_here"

headers = {
    "X-Cybozu-API-Token": TOKEN,
    "Content-Type": "application/json",
}

resp = requests.get(
    f"{BASE}/k/v1/records.json",
    headers=headers,
    params={"app": APP_ID, "query": "created_time > \"2026-02-01T00:00:00Z\"", "limit": 100},
    timeout=30,
)
resp.raise_for_status()
payload = resp.json()
```

## トラブルシュート

| 症状 | 想定原因 | 対処 |
|---|---|---|
| 401 unauthorized | トークン無効/期限切れ | トークンを再発行し、権限範囲を確認 |
| 403 forbidden | 権限不一致 | アプリ権限とトークン制限を再確認 |
| 400 bad request | スキーマ不一致 | フィールドコードと値の形式を確認 |
| 429 rate limit | 同時呼び出し過多 | backoff + jitter を追加し並列度を下げる |
| 500-level API error | 一時的なサービス障害 | 回数上限付きリトライを実施 |

## 運用時の検証

- 書き込み実行前に、既知レコード1件とフィルタ付きクエリ1件を読み取り確認する。
- 必須フィールドが宛先アプリに存在することを確認する。
- 応答件数が想定 `limit`/`offset` と整合するか確認する。
- 監査ログには次を残す:
  - run start/end time
  - app id
  - affected record count
  - request errors and retry count

## 参照

- `references/official_sources.md` に kintone 公式ドキュメントとAPI参照をまとめている。
- kintone データに触れる連携スクリプトを作るときは本スキルを使う。

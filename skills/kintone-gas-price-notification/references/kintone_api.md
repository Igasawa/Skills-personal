# kintone設定リファレンス

## 認証設定

**重要**: スペース/スレッドAPIはAPIトークン認証をサポートしていない。パスワード認証が必須。

### 認証情報の取得優先順位

スクリプトは以下の順序で認証情報を取得:

1. **関数の引数** - 直接指定された場合
2. **環境変数** - `KINTONE_USERNAME`, `KINTONE_PASSWORD`
3. **保存済みセッション** - `AX_HOME/sessions/kintone.storage.json`（環境変数が空の場合）
4. **対話入力** - 上記がない場合、ユーザーに入力を求める

### 環境変数設定（自動化向け）

```bash
export KINTONE_USERNAME="ログイン名"
export KINTONE_PASSWORD="パスワード"
```

### 対話入力

環境変数が未設定の場合、実行時にプロンプトが表示される:
```
kintoneログイン名: （入力）
kintoneパスワード: （入力、非表示）
```

### セッションフォールバック

Playwright で保存した storage_state（例: `C:\\Users\\<user>\\.ax\\sessions\\kintone.storage.json`）がある場合、
`.env` が空でもセッションCookie + CSRFトークンで投稿できる。

### リクエストヘッダー

パスワード認証では「ログイン名:パスワード」をBase64エンコードして送信:

```
X-Cybozu-Authorization: {Base64エンコードした "ログイン名:パスワード"}
Content-Type: application/json
```

Python例:
```python
import base64
auth_string = f"{username}:{password}"
auth_base64 = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
headers = {"X-Cybozu-Authorization": auth_base64}
```

### APIトークン認証（アプリAPI用のみ）

レコード操作などアプリ関連のAPIではAPIトークンが使用可能:
```
X-Cybozu-API-Token: {APIトークン}
```

## エンドポイント

### スレッドコメント投稿

```
POST https://{subdomain}.cybozu.com/k/v1/space/thread/comment.json
```

リクエストボディ:
```json
{
  "space": スペースID(数値),
  "thread": スレッドID(数値),
  "comment": {
    "text": "コメント本文"
  }
}
```

成功時レスポンス:
```json
{
  "id": "コメントID"
}
```

## URLからIDを取得する方法

kintoneのURL形式:
```
https://{subdomain}.cybozu.com/k/#/space/{space_id}/thread/{thread_id}
```

例: `https://5atx9.cybozu.com/k/#/space/24/thread/36`
- subdomain: 5atx9
- space_id: 24
- thread_id: 36

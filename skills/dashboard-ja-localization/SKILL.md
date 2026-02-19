---
name: dashboard-ja-localization
description: ダッシュボードUIの日本語化と文字化け防止を行うスキル。テンプレート/フロントJSの文言を追加・変更するとき、英語UI文言の日本語統一、`DASHBOARD_UI_LOCALE` の反映、`toFriendlyMessage` の翻訳追加、UTF-8(no BOM) 検証まで実施したい場合に使う。
---

# Dashboard 日本語化・文字化け防止

このスキルは、UI文言の言語統一と文字コード事故の再発防止を最小変更で実施する。

## 実施手順

1. UIロケール設定を確認する  
`DASHBOARD_UI_LOCALE` を既定 `ja` として扱い、テンプレートの `lang` に反映する。

2. UI文言を日本語に統一する  
対象:
- `dashboard/templates/*.html` の見出し、説明文、ボタン
- `dashboard/static/js/*.js` の表示用メッセージ（toast、状態表示、エラー表示）

3. API英語エラーを日本語化する  
`dashboard/static/js/common.js` の `toFriendlyMessage` に翻訳マッピングを追加する。

4. 文字化け防止チェックを実行する  
変更ファイルに対して:

```powershell
python scripts/check_text_encoding.py --path <file1> --path <file2>
```

5. 回帰テストを実行する  
対象ページに応じた `pytest` を実行し、少なくとも次を確認する。
- `lang="ja"`（または設定したロケール）
- 主要UI文言が日本語で表示されること

## 実装ルール

- 英語の固定メッセージを直接UIに出さない。必要なら `toFriendlyMessage` を経由する。
- 機械判定に必要な英語文字列（API識別子、ステータスキー等）は維持し、表示層のみ翻訳する。
- 保存エンコーディングは UTF-8（BOMなし）を使う。

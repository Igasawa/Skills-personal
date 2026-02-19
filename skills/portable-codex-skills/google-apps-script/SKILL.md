---
name: google-apps-script
description: Google Apps Script 開発の包括ガイド。組み込みサービス（SpreadsheetApp, DocumentApp, GmailApp, DriveApp, CalendarApp, FormApp, SlidesApp）、トリガー、認可、エラーハンドリング、性能最適化を扱う。Google Sheets 自動化、Google Docs 生成、Gmail 管理、Drive 操作、Calendar 自動化、トリガー実装、カスタム関数、アドオン作成、OAuth スコープ管理、UrlFetchApp でのAPI呼び出し、PropertiesService 永続化、CacheService 一時保存に使用する。バッチ処理、障害復旧、JavaScript ES6+ 実行環境を含む。
---

# Google Apps Script

## 概要

Google Workspace サービスを自動化するクラウド型 JavaScript プラットフォーム。サーバーサイド V8 ランタイムで、Sheets/Docs/Gmail/Drive/Calendar などへ OAuth 連携する。

## このスキルを使う場面

次のケースで利用する:

- Google Sheets 操作の自動化（読み取り、書き込み、書式）
- Google Docs のプログラム生成/編集
- Gmail メッセージ管理とメール送信
- Google Drive のファイル/フォルダ操作
- Google Calendar イベント自動化
- トリガー実装（時間ベース/イベントベース）
- Sheets カスタム関数の作成
- Google Workspace アドオンの作成
- OAuth スコープ/認可対応
- UrlFetchApp による外部API呼び出し
- PropertiesService による永続データ管理
- CacheService によるキャッシュ戦略
- バッチ処理による性能最適化
- Apps Script コードや認可問題のデバッグ

## 主要サービス

1. **SpreadsheetApp** - Google Sheets 自動化（読み書き、書式、データ検証）
2. **DocumentApp** - Google Docs 作成/編集
3. **GmailApp & MailApp** - メール操作（送信、検索、ラベル管理）
4. **DriveApp** - ファイル/フォルダ管理、共有、権限
5. **CalendarApp** - カレンダーイベント、定期予定、リマインダー
6. **Triggers & ScriptApp** - 時間ベース/イベント駆動自動化

## クイックスタート

```javascript
function generateWeeklyReport() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('Data');
  const data = sheet.getRange('A2:D').getValues();

  const report = data.filter(row => row[0]);
  const summarySheet = ss.getSheetByName('Summary') || ss.insertSheet('Summary');
  summarySheet.clear();
  summarySheet.appendRow(['Name', 'Value', 'Status']);
  report.forEach(row => summarySheet.appendRow([row[0], row[1], row[2]]));

  MailApp.sendEmail({
    to: Session.getEffectiveUser().getEmail(),
    subject: 'Weekly Report Generated',
    body: `Report generated with ${report.length} records.`
  });
}
```

## ベストプラクティス

- **Batch operations** - ループ内のセル単位処理を避け、範囲をまとめて読み書きする
- **Cache data** - 高頻度データは CacheService（TTL 25分）を使う
- **Error handling** - try/catch で囲み、監査向けにエラーをシートへ記録する
- **Respect limits** - 実行上限6分を前提に、大規模処理はトリガー分割する
- **Minimise scopes** - `appscript.json` では必要最小限の OAuth 権限のみ要求する
- **Persistent storage** - 設定と状態は PropertiesService で保持する
- **Validate inputs** - プロパティ参照前にオブジェクト存在を検証する

各項目の詳細例は [references/best-practices.md](references/best-practices.md) を参照。

## 検証とテスト

デプロイ前チェックには `scripts/` の検証スクリプトを使う:

- **scripts/validators.py** - スプレッドシート操作、範囲指定、データ構造を検証

`Logger.log()` でデバッグし、View > Logs（Cmd/Ctrl + Enter）で出力確認する。Apps Script エディタのブレークポイントでステップ実行する。

## 他スキルとの連携

- **google-ads-scripts** - Google Ads データを Sheets に出力してレポート化
- **gtm-datalayer** - Apps Script 起点イベントを GTM 連携で追跡
- **ga4-bigquery** - Apps Script から BigQuery を問い合わせ、結果を Sheets へ書き込み

## トラブルシュート

| 問題 | 対応 |
|-------|----------|
| Execution timeout | 処理を小さなバッチへ分割するか、複数トリガーを使う |
| Authorisation error | マニフェストの OAuth スコープを確認する |
| Quota exceeded | API 呼び出し頻度を下げ、キャッシュを使う |
| Null reference error | プロパティ参照前にオブジェクト存在を確認する |

## 参照

詳細は参照ファイルに分離されており、必要時に読み込む:

- [references/apps-script-api-reference.md](references/apps-script-api-reference.md) - 組み込みサービス、トリガー、認可、性能最適化を含む API リファレンス
- [references/examples.md](references/examples.md) - 本番向けコード例（スプレッドシートレポート、Gmail自動返信、文書生成、トリガー設定）
- [references/best-practices.md](references/best-practices.md) - バッチ処理、キャッシュ、エラーハンドリング、スコープ、永続化の実践例
- [references/patterns.md](references/patterns.md) - 再利用パターン（データ検証、リトライロジック、フォーム回答処理）

## ダッシュボード/Webhook 連携（Expense Reconcile）

GAS ワークフローから月次インポート状態をワークフローダッシュボードカードへ報告する場合、次のパターンを使う。

- Script Properties にダッシュボードのベースURLを保存: `AX_EXPENSE_DASHBOARD_BASE_URL`
- 任意トークン: `AX_PROVIDER_IMPORT_WEBHOOK_TOKEN`（`x-provider-import-token` として送信）
- POST エンドポイント形式: `POST /api/provider-import/{ym}/result`（`ym = YYYY-MM`）
- ペイロードはバックエンド項目（`found_files`, `found_pdfs`, `imported`, `imported_missing_amount`, `skipped_duplicates`, `failed`, `provider_counts`, `manual_action_required` など）へ合わせる
- 月次トリガーは毎月5日を使用: `everyMonths(1).onMonthDay(5).atHour(4)`
- 実装コードは `references/examples.md` を参照。

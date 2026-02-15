# 公式マニュアル整合ノート（連携スキル向け）

最終更新: 2026-02-15

## 1. 本スキルの対象範囲
- 対象: Amazon領収書、楽天領収書、MFクラウド経費（Step0/Step5）連携
- 目的: 画面仕様と差分が出る領収書取得ケースを、ノー・レシートとして安定化

## 2. MFクラウド経費（確認済み）
- 参照公式リンク:
  - 領収証/明細作成系ガイド: `https://biz.moneyforward.com/support/expense/guide/ap/ap31.html`
  - 入力フォーム・個人設定: `https://biz.moneyforward.com/support/expense/guide/personal/pa34.html`
  - OCR自動入力FAQ: `https://biz.moneyforward.com/support/expense/faq/ap-faq/r10.html`
  - Step2/ステップ系: `https://biz.moneyforward.com/support/expense/guide/first-step-guide/fs02.html`
- 運用要点:
  - Step0: 連携更新後に取得中の再取得状態を確認するまで完走を目標
  - Step5: `outgo_input` 側で下書き作成へ接続する導線が既定
  - 失敗時のバリデーション情報（`validation_failed`）は補完ロジック改修の入力情報として保持

## 3. 楽天（確認済み）
- 仕様上ノー・レシートが起きやすい条件:
  - 支払方法が代引き/代金引換（配送業者領収書へ切替）
  - 決済がデジタル関連（デジタル版・電子版）と判断される注文
- 楽天Books（`books.rakuten.co.jp`）は既存ロジックで、`receiptInput`/`receiptPrint`の遷移を扱うため既に個別分岐あり
- 追加運用観点:
  - 「支払確定」前・遷移失敗時は一律エラーにせず、`no_receipt` 系に寄せる
  - 同一注文で `payment_method` ベースの先行スキップを優先し、タイムアウトやボタン未検知を減らす

## 4. Amazon（確認ポイント）
- 既知情報:
  - 一部の支払方法では、注文履歴上の表示はあるが、通常の領収書として扱えないケースがある
  - 同一購入で税務証憑が複数種別（購入明細/請求系）に分かれるケースあり
- 実装反映方針:
  - Amazon側は本セクションで追加確認中。まずは既知例外（代引き/代金引換系）を除外候補として扱えるようロジック側を拡張
  - 取得実績ログと `error_reason` を `payment_method` と突合して、除外条件を定量化

## 5. 直近対応として反映済み
- `skills/mfcloud-expense-receipt-reconcile/scripts/rakuten_download.mjs`
  - `isRakutenNoReceiptPaymentMethod()` を追加
  - 支払方法が対象外のとき、`findReceiptAction` 前に `status=no_receipt` に短絡
  - `error_reason=no_receipt_payment_method` と `error_detail` に `payment_method` を保存
- テスト追加:
- `skills/mfcloud-expense-receipt-reconcile/tests/test_rakuten_download_logic.py`
  - `test_is_rakuten_no_receipt_payment_method`
- `skills/mfcloud-expense-receipt-reconcile/scripts/amazon_download.mjs`
  - `isAmazonNoReceiptPaymentMethod()` 追加（代金引換/COD 系を除外）
  - `extractAmazonPaymentMethodFromText()` 追加（注文行テキストから支払方法を抽出）
  - `status=no_receipt` かつ `error_reason=no_receipt_payment_method` を短絡
  - `payment_method` を明細レコードに保持（`row.payment_method`）
  - `status=no_receipt` 時に `include=false` を明示
- `skills/mfcloud-expense-receipt-reconcile/tests/test_amazon_download_logic.py`
  - `test_extract_amazon_payment_method_from_text`
  - `test_is_amazon_no_receipt_payment_method`
- 追加要注意:
  - Amazon公式の領収書取得要件（特定支払方法での不発行）が動的に変化するため、運用監視時に `payment_method` を蓄積して除外閾値を調整

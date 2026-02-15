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
  - 領収書詳細画面を開いた時点でも支払方法を再判定し、`no_receipt` に短絡（カード一覧のみだと取得できないケース対応）
- `skills/mfcloud-expense-receipt-reconcile/tests/test_amazon_download_logic.py`
  - `test_extract_amazon_payment_method_from_text`
  - `test_is_amazon_no_receipt_payment_method`
- 追加要注意:
  - Amazon公式の領収書取得要件（特定支払方法での不発行）が動的に変化するため、運用監視時に `payment_method` を蓄積して除外閾値を調整

## 6. 運用ナレッジ（実運用向け）
- 目的:
  - `error_reason` を固定キーとして扱い、再実行・除外対象の運用判断を標準化する
- 運用原則:
  - `status=no_receipt` は原則除外フロー
  - `status=error` は再試行または手動確認が必要

### 6.1 エラー理由別運用ルール
- `no_receipt_payment_method`
  - 対象: Amazon/楽天の COD/代引きなどの判定
  - 処理: `include=false`、`error_reason` 変更なしで再実行しない
  - 記録: `payment_method` を必ず保持して月次集計
- `link_not_resolved`
  - 対象: リンク解決失敗
  - 処理: 1回だけ再実行し、同一注文で連続失敗時は保留
- `menu_not_found`
  - 対象: 受け渡し画面の構造差分
  - 処理: UI差分確認（スクリーンショット比較・ロジック差分）を優先
- `document_validation_failed:...`
  - 対象: 領収書ページ本文の検証失敗
  - 処理: 画面構成・文言変更の有無を確認、必要なら判定条件更新
- `auth_required`
  - 対象: 認証タイムアウト/期限切れ
  - 処理: ログイン状態復旧後に再実行

### 6.2 判定優先順位（実行時）
1. gift card 判定
2. payment_method 除外判定（`no_receipt_payment_method`）
3. メニュー/リンク解決
4. 領収書ページの取得・保存
5. 領収書本文の妥当性検証

### 6.3 監視メトリクス（週次）
- 期間ごとの `source` / `status` / `error_reason` 件数
- `no_receipt` と `error` の比率推移
- `no_receipt_payment_method` の `payment_method` 上位（10件）
- `status=no_receipt` のうち `include=false` 維持率（除外の誤判定を観測）

### 6.4 再現レビュー記録（最小）
- `order_id`, `source`, `status`, `error_reason`, `payment_method`, `detail_url`, `receipt_url`, `log_path`
- 同一 `order_id` の再試行履歴を簡易ノート化し、原因を「除外」か「要改善」に分類

## 7. 運用ナレッジの蓄積基準（実務で再現性を担保）
- 公式マニュアル変更時は、影響範囲の小さな差分でも「設計ノート」に反映し、実装差分がなくても運用手順を更新する。
- 3本柱（Amazon / 楽天 / MF）で「日次実行で見えない例外」と「人手前提例外」を事前分類し、担当が即時判断できるようにする。
- 同一障害が 7 日連続で発生する場合は、当該フローを一時停止して原因切り分けし、再発抑止のルール更新まで戻さない。

### 7.1 公式マニュアルとの差分監査
- 毎月1回、各サービスの運用ページの最終更新日をスクショログ化して保存し、更新有無を確認。
- 変更点が UI ラベル・文言・必須項目・導線に及ぶ場合は、同日中に以下を順守。
  - スクリプト判定文言のキー更新対象を明文化
  - 既存テストケースの影響範囲確認
  - ユーザー操作手順の画面遷移図を更新
- official_manual_alignment_notes.md の「リンク」「状態コード」「例外コメント」を同時に更新。

### 7.2 例外復旧の優先順位
- P0: 認証失敗、ログイン制御、ダウンロード停止が連鎖的に起きるケース（即時停止・即日連絡）
- P1: 個別明細の取りこぼし、
o_receipt_payment_method の増加（当日中の手動補完）
- P2: 命名差分や軽微な文言差分（次回リリース前に対応）
- 判定フローは「1)原資データ確認 2)再実行可否 3)手動代替 4)監査記録」の順。

### 7.3 運用時に共有すべき最低情報
- 実行結果サマリ: 実行開始/終了、対象件数、成功/失敗数、再試行数
- 失敗一覧: order_id, error_reason, source, status, payment_method, log_path
- 代替処理: 人手対応の根拠と実施者、対応日時、次回再実行結果
- 監査証跡: すべての主要操作は日次の実施ログへ追記（差分を追跡可能な状態に）

### 7.4 運用ハンドオフの形式
- 月次で「平常導線」「注意導線」「障害導線」の3種類をテンプレート化。
  - 平常導線: エラーなし、再試行なし
  - 注意導線: 件数増加のみ、時間内復旧
  - 障害導線: P0/P1 発生、実運用待機あり
- 引継ぎ担当者は「その日対応した例外」を短く 5 行以内でまとめ、次担当に引き継ぐ。
- 問題のある注文情報は、MF の手動補完画面へ戻るルートと再試行タイミングを明確にしておく。

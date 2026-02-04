# 月次処理スレッド

対象月：{{YEAR}}年{{MONTH}}月
対象期間：{{RANGE_START}} ～ {{RANGE_END}}
対象ステータス：下書き / 未申請

## 今月の前提・特記事項
{{NOTES}}

## レシート提供状況
- 保存場所：{{RECEIPTS_PATH}}
- 形式：PDF
- 命名：YYYY-MM-DD_amazon_<orderId>_<totalYen>.pdf

## 今月の進め方
- 基本方針：1明細=1レシート、金額/日付が一致しない場合は自動紐付けしない
- 優先順位：完全一致 → 近似一致 → 要確認

## 作業開始指示
- Phase 1 (Scan) から開始

## 参考
- レポート出力：{{REPORTS_PATH}}

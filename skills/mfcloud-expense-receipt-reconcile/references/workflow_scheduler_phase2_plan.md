# Phase 2 実装計画: スケジュール実行増設

最終更新: 2026-02-20  
前提: 機能フラグなし、MVPスケルトンから段階導入する。

## 1. ゴール
- 先頭手順 `trigger_kind=scheduled` のテンプレートを、指定日時で安全に起動できる。
- 既存の `manual_start` / `external_event` 運用を壊さず共存させる。
- 失敗時に原因追跡できる最低限の監査情報を残す。

## 2. 段階導入（アジャイル）

### Phase 2.1（最小価値）
- スコープ:
  - テンプレート保存時の scheduler 同期（既存）を契約化。
  - `run_date` / `run_time` の入力と保存を UI/API で往復可能にする。
  - `enabled=false` でも設定を保持し、再有効化時に再利用できるようにする。
- 完了条件:
  - `/api/scheduler/state?template_id=...` で設定を取得・保存できる。
  - `/expense-workflow-copy` から対象テンプレートに紐づく設定を編集できる。

### Phase 2.2（安全起動）
- スコープ:
  - `once` のみ先行対応（単発実行）。
  - 予約時刻到達で workflow run を1回起動する。
  - 同一 `template_id + run_date + run_time` の重複起動防止を実装。
- 完了条件:
  - 到達時刻で1回だけ起動し、二重実行しない。
  - 実行結果を `reports/audit_log.jsonl` に記録できる。

### Phase 2.3（運用拡張）
- スコープ:
  - `daily/weekly/monthly` を段階的に追加。
  - catch-up policy（`run_on_startup`/`skip`）を実際の再起動ケースで反映。
  - 失敗リトライ方針を最小実装（例: 1回再試行）する。
- 完了条件:
  - 再起動・障害時の挙動が仕様通りで、手順が運用文書に明記されている。

### Phase 2.3 受け入れ条件（詳細）
1. `daily`
- 前回実行日と同日中は再実行しない。
- 指定時刻到達後に1回だけ起動する。

2. `weekly`
- 設定曜日 + 設定時刻の一致時のみ起動する。
- サーバー再起動で同一週の二重起動が発生しない。

3. `monthly`
- 設定日（例: 25日）+ 設定時刻で1回起動する。
- 存在しない日付（例: 31日）の扱いを仕様固定する（末日補正 or skip）。

4. catch-up policy
- `run_on_startup`: ダウン中に取り逃した最新スロットを起動する。
- `skip`: ダウン中の取り逃しを起動せず、次スロットを待つ。

5. retry policy（最小）
- 起動失敗時は1回だけ再試行する。
- 再試行失敗時は `failed` で確定し、同一スロットの無限再試行を行わない。

6. 監査・運用
- `reports/audit_log.jsonl` に `started/skipped/deferred/failed` を必ず出力する。
- 同一スロット判定キー（idempotency）で重複起動抑止を確認できる。
- 障害時に「失敗理由」「次回予定時刻」「再試行有無」を追跡できる。

## 3. 実装タスク分解

## A. 契約とデータ
1. scheduler 状態の契約を固定（必須/任意、既定値、エラー条件）
2. `workflow_trigger_execution_contract.md` と整合する制約を明記
3. 既存テンプレート（scheduler未設定）移行時の既定挙動を定義

## B. API
1. `/api/scheduler/state` の入力検証を強化（形式・範囲・必須）
2. テンプレート保存時 `scheduler_sync.reason` の扱いを固定
3. 異常系の detail を `toFriendlyMessage` で変換可能な形に揃える

## C. UI
1. `/expense-workflow-copy` で scheduler パネルを段階的に再導入
2. 先頭手順が `scheduled` 以外の場合は編集不可の説明表示
3. 保存結果（armed/disabled理由）をカード上に表示

## D. 実行基盤
1. 予約起動チェックのポーリング/タイマー処理を整理
2. 二重実行防止キーを実装
3. 失敗時ログ（原因、次アクション）を出力

## E. テスト
1. APIユニット: 正常/異常/境界（日時、enabled、action）
2. 統合: テンプレート保存→scheduler同期→状態取得
3. E2E: UI保存→有効化→起動待ち→実行履歴確認

## 4. リスクと先回り
- リスク: scheduler と workflow run の責務分散でバグ混入
  - 対応: 起動入口を1か所に限定し、監査ログで追跡可能にする。
- リスク: タイムゾーン差異による誤起動
  - 対応: サーバー時刻基準を明示し、保存時に正規化する。
- リスク: UIで設定できても実行されない状態の混乱
  - 対応: `scheduler_sync.reason` を明示表示し、未起動理由を可視化する。

## 5. 受け入れ基準（Phase 2完了）
1. 先頭手順 `scheduled` のテンプレートを時刻指定で起動できる
2. 二重実行が抑止される
3. 失敗時に原因と再実行方針がログで追跡できる
4. UI/API/ドキュメントの用語と制約が一致している

## 6. 関連運用文書
- scheduler運用手順: `references/workflow_scheduler_runbook.md`

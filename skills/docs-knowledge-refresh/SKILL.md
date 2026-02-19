---
name: docs-knowledge-refresh
description: ドキュメントの鮮度（最終確認日・期限切れ・要更新）を定期監査するスキル。Markdown群を走査し、更新期限超過を検出してレポート化する。「この資料が古くないか確認」「ナレッジの定期更新を仕組み化したい」「更新期限を超えたドキュメントを一覧化して」といった依頼で使用。
---

# ドキュメント鮮度監査スキル

## 概要

`scripts/run.py` で Markdown ドキュメントをスキャンし、更新期限超過を検出する。
既定は `--dry-run` で、`--apply --write-report` のときだけレポートを確定します。

## 監査対象ルール

このスキルは次を優先して日付を読む。

1. YAML frontmatter の `last_verified` / `last_reviewed` / `reviewed_at` / `last_checked` / `updated_at` / `Last Verified` / `最終確認日`
2. 本文中の `最終確認日: YYYY-MM-DD` / `Last Verified: YYYY-MM-DD` / `Review Date: YYYY-MM-DD`

`review_source` は日付キーではなく、監査時点のメタ情報（例: `knowledge_refresh_weekly`）です。

期限ルールは `docs/knowledge_refresh_registry.json` でファイルごとに上書きできます。

## クイックスタート

```powershell
# 1) 監査（読み取りのみ）
python skills/docs-knowledge-refresh/scripts/run.py `
  --scan docs `
  --registry docs/knowledge_refresh_registry.json `
  --fail-on-stale

# 2) 監査＋レポート出力（AX_HOME/reports/knowledge_refresh）
python skills/docs-knowledge-refresh/scripts/run.py `
  --scan docs `
  --registry docs/knowledge_refresh_registry.json `
  --bootstrap-missing-review-date `
  --bootstrap-review-source knowledge_refresh_weekly `
  --write-report `
  --apply
```

## 他リポジトリ運用ガイド

このスキルを別リポジトリで使う場合は、監査対象リポジトリを起点に実行すると失敗しにくくなります。

前提:
- 対象リポジトリに `docs/` があること
- 監査ルールファイルが `docs/knowledge_refresh_registry.json` であること（なければ既定値を使う）

おすすめ実行手順（PowerShell）:
```powershell
# 監査対象リポジトリへ移動
$repoRoot = "path\to\other-repo"
Set-Location $repoRoot

# skills 側（ローカルに共有している想定）
$runScript = "path\to\skills-core\skills\docs-knowledge-refresh\scripts\run.py"
python $runScript `
  --scan docs `
  --registry docs/knowledge_refresh_registry.json `
  --fail-on-stale `
  --dry-run
```

相対パスを安定化したい場合は `--scan` と `--registry` を絶対パスで固定します。
```powershell
python $runScript `
  --scan (Join-Path $repoRoot "docs") `
  --registry (Join-Path $repoRoot "docs/knowledge_refresh_registry.json") `
  --fail-on-stale
```

## 他リポジトリでの運用手順（定期運用）

1. まず `--dry-run --fail-on-stale` で監査だけ実施して確認
2. 問題なければ `--apply --write-report` を付与
3. レポートを他リポジトリ配下へ置きたい場合:
   `--report-dir (Join-Path $repoRoot "reports/knowledge_refresh")`
4. 追加ドキュメントは監査対象追加後に以下を実行して漏れを洗い出す
```powershell
python $runScript `
  --scan docs `
  --registry docs/knowledge_refresh_registry.json `
  --bootstrap-missing-review-date `
  --bootstrap-review-source knowledge_refresh_weekly `
  --strict-bootstrap `
  --dry-run
```

## 追加チェックリスト（他リポジトリ用）

1. 対象確認
   - `python ...\run.py --scan docs --registry docs/knowledge_refresh_registry.json --dry-run --fail-on-stale`
2. 追加漏れ確認
   - `python ...\run.py --scan docs --registry docs/knowledge_refresh_registry.json --bootstrap-missing-review-date --bootstrap-review-source knowledge_refresh_weekly --dry-run`
   - ここで `bootstrap_items` が空なら、漏れなし
3. レポート出力（必要時）
   - `python ...\run.py --scan docs --registry docs/knowledge_refresh_registry.json --apply --write-report`
4. 週次実行
   - `--fail-on-stale` を付与し、失敗時はジョブを再実行前に `--dry-run` で原因を特定
5. 追加ドキュメント受け入れ時
   - 追加直後に手順2を必ず実施
   - 追加が多数ある場合は手順3へ進む前に issue だけを一覧化

## 実行パスの取り違え対策（推奨）

`--scan`/`--registry` は実行場所で解決先が変わるため、次のどちらかに揃えると事故りにくくなります。

1. リポジトリ直下から実行（最も簡単）
```powershell
$repoRoot = "path\to\PersonalSkills"
Set-Location $repoRoot
python skills/docs-knowledge-refresh/scripts/run.py --scan docs --registry docs/knowledge_refresh_registry.json --fail-on-stale --apply --write-report
```

2. スキル配下から実行（モジュール実行）
```powershell
Set-Location (Join-Path $repoRoot "skills/docs-knowledge-refresh")
python -m scripts.run --scan docs --registry docs/knowledge_refresh_registry.json --fail-on-stale --apply --write-report
```

- `--registry` は実行場所でパスが変わりやすいため、明示的に `docs/...` のルールは維持しつつ、`skills/docs-knowledge-refresh/scripts/run_support_io.py` 側で補完検索を入れています。

## JSON I/O（標準入口）

## PowerShell実行関数（推奨）

```powershell
# 1) skills 側スクリプトをロードして関数定義
. .\skills\docs-knowledge-refresh\scripts\knowledge_refresh.ps1

# 監査対象リポジトリを起点に実行（推奨）
Set-Location path\to\repo-root
knowledge_refresh --fail-on-stale --dry-run

# 別リポジトリを明示して実行したい場合
knowledge_refresh --repo-root path\to\other-repo --scan docs --registry docs/knowledge_refresh_registry.json --fail-on-stale
```

`scripts/run.py` は `config/params` JSON を受け取り、`status/data/error` を返す。

入力例:
```json
{
  "config": {
    "dry_run": true,
    "targets": { "paths": ["docs"], "extensions": [".md"] },
    "policy": { "default_max_age_days": 30, "warn_within_days": 7 },
    "registry": { "path": "docs/knowledge_refresh_registry.json" }
  },
  "params": {
    "fail_on_stale": true,
    "bootstrap_missing_review_date": true,
    "strict_bootstrap": true
  }
}
```

主な出力:
- `data.summary.stale`: 期限切れ件数
- `data.stale_items[]`: 期限切れの詳細
- `data.warning_items[]`: 期限接近
- `data.bootstrap_items[]`: 自動補完されたファイル
- `data.bootstrap_items[].review_source`: 補完時に入れた `review_source`（例: `knowledge_refresh_weekly`）
- `data.bootstrap_items[].review_date_key`: 日付を読み取ったキー名（既存 metadata の場合）
- `data.report.path`: `--apply --write-report` 時のレポートパス

## Windows Task Scheduler 例

```powershell
schtasks /Create /F /SC WEEKLY /D MON /TN "AX-Knowledge-Refresh" /TR "powershell -NoProfile -ExecutionPolicy Bypass -Command `"cd <REPO_ROOT>; python skills/docs-knowledge-refresh/scripts/run.py --scan docs --registry docs/knowledge_refresh_registry.json --fail-on-stale --write-report --apply`""
```

## 運用のコツ

1. 外部仕様に依存する資料は `最終確認日` と出典 URL を必ず記載する
2. 期限が短い資料（価格/API/UI 変更が多いもの）は `registry` で `max_age_days` を短くする
3. CI/定期ジョブでは `--fail-on-stale` を付け、期限切れを見逃さない
4. 追加ドキュメントの取りこぼし対策として、`--bootstrap-missing-review-date` を入れつつ、漏れ監査を確実化する

## 追加ドキュメントの漏れ対策

新規 `docs/*.md` を追加する場合は、先に metadata を入れておくと監査失敗を防げます。

```powershell
python skills/docs-knowledge-refresh/scripts/run.py `
  --scan docs `
  --registry docs/knowledge_refresh_registry.json `
  --bootstrap-missing-review-date `
  --bootstrap-review-source knowledge_refresh_weekly `
  --dry-run
```

- `--dry-run` で不足分を検出だけ確認できます。
- `--apply` を付けると `last_reviewed` と `review_source` の frontmatter を不足ファイルへ埋めます。
- `--strict-bootstrap` を有効にすると、補完されたファイルは `data.bootstrap_items` とレポート「Bootstrap Updates」へ出ると同時に `stale` 扱いになります。
- 追加手順として、`--scan docs --registry ... --bootstrap-missing-review-date --dry-run` を追加ドキュメント反映直後に必ず1回通し、漏れのないことを確認してから本番ジョブへ入れると事故を防げます。

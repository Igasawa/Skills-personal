# KIL 学習で再発防止する「最小条件」一覧

このリポジトリでは、`post-commit` でのコミット知識抽出を前提に、次の条件を毎回優先して守る。  
人間レビューの判断を速くするため、**この一覧を最優先で読む**。

## 1) 実行環境の前提（必須）

- OSが Windows なら、スクリプトは **PowerShell 前提**で考える  
  - `&&` / `||` / bash 風条件分岐は避ける  
  - 複数コマンドは `;` 区切りまたは PowerShell の構文で記述する
- 文字エンコードは原則 `UTF-8` / `UTF-8-SIG`（PowerShell入出力との整合優先）
- 機密情報はリポジトリ外 (`AX_HOME` 配下の env) に配置

## 2) KIL フローの固定ルール

- `post-commit` が未設置・非管理状態で進めない（`scripts/bootstrap_kil.ps1` で管理状態を確認）
- `analyze_commit.py` は **失敗しても commit を止めない**（後段で `AGENT_BRAIN_ERROR.log` を必ず残す）
- 解析は `AGENT_BRAIN_INDEX.jsonl` と `AGENT_BRAIN.md` に同時反映する
- 既存コミットの重複追記を避ける（コミットハッシュ単位で1件化）

## 3) レビューで必ず見る項目（再発防止）

- PowerShell 依存性ミス（`&&` などの混入）
- シークレットの露出/混入（`AIza...`, `sk_live...`, `Bearer ...` など）
- 新規ルール未反映（`AGENT_BRAIN.md` / `AGENT_BRAIN_INDEX.jsonl` への反映漏れ）
- `review_deadline` が設定されている項目の期限超過
- `high risk` または `confidence` が低いエントリの人間レビュー

## 4) 学習順調度を読む目安

- `lag_commits=0` かつ最新コミットと `analyzed_commit` が一致 → 基本順調
- `lag_days` が継続的に増える → 学習が遅延
- `Markdown由来` が増える → `index` 未生成を疑う
- 期限超過件数や `human review` 必要件の増加 → 優先レビュー対象

## 5) 追加の推奨（将来）

- 重要ルールを `AGENTS` の最上位ルールとして固定化し、AIに毎回最優先で読ませる
- `AGENT_BRAIN_REVIEW.jsonl` で `needs_human_review` を監査し、頻発項目を dashboard 表示優先にする

# KIL 2.1 運用計画書  

## 1. 目的

- 開発者のコミットから「技術的意図」「制約」「教訓」を継続的に抽出し、エージェントが常に最新文脈で提案できるようにする。  
- 仕様変更の意図を失わず、再発防止知識を時系列で蓄積する。  
- 将来の検索系AI活用（ChromaDB等）に拡張しやすい形式で長期記憶基盤を育てる。

---

## 2. 基本方針（設計原則）

1. **フックは開発体験を壊さない**  
   post-commitは必ず成功（exit code 0）で終了し、取得・解析失敗時はエラーログに残して次回再実行する。  

2. **コスト最適化を前提にする**  
   差分は要約してモデルに送る。`diff`が巨大な場合は「重要差分のみ」「ハイライト抽出」を行う。  

3. **品質の高い構造化知識を優先**  
   Markdownは人間向け、JSONLは機械向けの**二層構造**で保存する。  

4. **機密に対しては最小暴露**  
   APIへ送る前にシークレット文字列・キー情報・メール/トークン疑い文字列をサニタイズする。  

5. **再実行可能性**  
   同一コミット再処理時に重複エントリを作らない（commit hash を主キー化）。  

---

## 3. 全体アーキテクチャ（最小構成）

- **Layer A: Trigger**
  - Git hook（`post-commit`）で非同期ジョブとして処理を起動。
- **Layer B: Capture**
  - `git show` を使って最新コミット情報（メッセージ/差分/変更ファイル）を収集。
- **Layer C: Analyze**
  - 差分をサニタイズ・圧縮し、Gemini APIへ投げる。
- **Layer D: Memory**
  - `docs/AGENT_BRAIN.md`（Markdown）へ追記  
  - `docs/AGENT_BRAIN_INDEX.jsonl`（機械可読）へ同時追記  
- **Layer E: Retrieval（将来）**
  - v2以降でChromaDB等へJSONLをインデックス化し、関連知識を高速検索。

---

## 4. ファイル構成（提案）

```
docs/
  AGENT_BRAIN.md
  AGENT_BRAIN_INDEX.jsonl
  AGENT_BRAIN_ERROR.log
  KIL_PLAN.md

scripts/
  analyze_commit.py
  kil/
    prompt.py
    sanitize.py
    writer.py
    git_capture.py
    model_client.py

.git/hooks/
  post-commit
  post-commit.ps1
```

---

## 5. Hook設計（OS非依存）

### 5.1 Windows/PowerShell

`post-commit`は直接シェル分岐せず、`post-commit.ps1`を起動するラッパーを呼ぶ。  

- PowerShell実行中に `python` コマンドが存在しない場合は `py` を試す。
- `start-process`/非同期実行を用い、Gitのexit codeには影響しない。

### 5.2 Linux/macOS

- 標準 `#!/usr/bin/env python` を起動する方式でもよいが、Windows互換のため最終的にPythonラッパーを共通化する。  

### 5.3 失敗時ポリシー

- `analyze_commit.py` が失敗しても `post-commit` は成功終了。  
- 失敗内容は `docs/AGENT_BRAIN_ERROR.log` へ1行JSONで追記（commit hash, error type, timestamp, command, retry_count）。  

---

## 6. `analyze_commit.py` 設計

### 6.1 入力

- `HEAD` のcommit hash  
- 取得対象:
  - Commit message
  - author, date, parents
  - 変更ファイル一覧
  - patch（上限付き）

### 6.2 正規化処理

1. バイナリ/画像等は差分本文を除外し、メタ情報のみ扱う。  
2. `node_modules` / `dist` / `.venv` / `build` / 大容量vendorを除外。  
3. シークレット疑い文字列をサニタイズ:
   - `AKIA...`, `sk_live_...`, `AIza...`, `Bearer ...`, 長文Base64疑いなど  
4. diff長が上限を超える場合は「圧縮モード」に切り替え（変更ファイル数上位/意味のあるhunkに絞る）。  

### 6.3 LLM実行

- 送信ペイロードは以下の構造:
  - `commit_meta`
  - `context_summary`
  - `patch_excerpt`
- モデルには**JSONのみ返却**を厳命（スキーマ違反時は再試行）。  
- 応答が不正な場合は `fallback` 文字列で最低限の記録を生成。  

### 6.4 出力

- `docs/AGENT_BRAIN_INDEX.jsonl` へ1レコード追記。  
- 同内容を整形して `docs/AGENT_BRAIN.md` へ追記（重複チェック後）。  
- 追加に失敗した場合は `.bak` へ退避して再試行できる形で保存。  

---

## 7. 出力フォーマット（標準）

### 7.1 `AGENT_BRAIN.md`（人間向け）

```md
## [2026-02-17T10:15:00+09:00] Commit: <commit-hash>
- **概要**: ...
- **獲得した知識**: ...
- **守るべきルール**: ...
- **未解決の文脈**: ...
- **技術的負債**: ...
- **影響スコープ**: ...
- **信頼度**: 0.87
- **重要度**: high/medium/low
- **再評価予定日**: YYYY-MM-DD
```

### 7.2 `AGENT_BRAIN_INDEX.jsonl`（機械可読）

```json
{"commit":"<hash>","timestamp":"2026-02-17T10:15:00+09:00","summary":"...","intent":"...","new_rules":["..."],"anti_patterns":["..."],"debt":["..."],"scope":["backend","auth"],"confidence":0.87,"risk":"medium"}
```

---

## 8. LLMプロンプト（v1）

あなたは開発履歴の知識抽出エージェント。  
以下の入力から、コミットの意図と再利用すべき知識を抽出し、必ず有効なJSONで返す。  

**出力スキーマ（必須キー）**  

```json
{
  "summary": "string",
  "intent": "string",
  "new_rules": ["string", ...],
  "anti_patterns": ["string", ...],
  "debt": ["string", ...],
  "scope": ["string", ...],
  "confidence": 0.0,
  "risk": "low" | "medium" | "high",
  "review_deadline": "YYYY-MM-DD | null"
}
```

- `summary`: 変更の要約。  
- `intent`: 変更背景・目的・想定効果。  
- `new_rules`: 今後守るべきルール/禁止事項。  
- `anti_patterns`: 再発防止に効く懸念点。  
- `debt`: 未解決の残件。  
- `risk`: 影響の大きさ。  
- `review_deadline`: 期限付きの追跡が必要な項目は日付で記述、不要なら `null`。  

---

## 9. 運用ルール

1. 各タスク開始前に `AGENT_BRAIN.md` と `AGENT_BRAIN_INDEX.jsonl` の最新20件を読む。  
2. `risk=high` は必読対象として優先。  
3. `review_deadline` 到来時は再評価項目としてタスクログに明示。  
4. `AGENT_BRAIN_ERROR.log` が2件以上連続したら保守担当が設定をレビュー。  
5. 6か月ごとに知識圧縮（古いコミットの要点再集約）を実施。  

---

## 10. 監査指標（KPI）

- Hook成功率（コミット完了時）: 99.5%以上  
- 解析成功率（1コミットあたり）: 90%以上  
- 1回あたりLLM呼び出し時間（p95）: 6秒以内  
- `AGENT_BRAIN.md`の必須キー欠損率: 0%  
- 失敗時再試行成功率: 80%以上  

---

## 11. 拡張計画

- **v1（今回）**: Markdown + JSONL のみ。  
- **v2（1〜2週）**: ChromaDBへの取り込みジョブ追加。  
  - JSONLをembedding化し、コミット検索APIを追加。  
- **v3（1か月）**: retrieval優先順位を「リスク」「スコープ」「最新性」で再ランキングし、提案時の先読みに活用。  

---

## 12. 受け入れ条件（実装完了判定）

1. 10連続コミットでもpost-commitが失敗せず実行される。  
2. Gemini障害中もコミットは完了し、`AGENT_BRAIN_ERROR.log` へ記録される。  
3. 追加されたエントリが `AGENT_BRAIN.md` と `AGENT_BRAIN_INDEX.jsonl` の双方で同時整合される。  
4. 連携環境（Windows / macOS）でフックが起動し、最低1件の分析を保存できる。  
5. APIペイロードにシークレット疑い文字列が含まれない。  


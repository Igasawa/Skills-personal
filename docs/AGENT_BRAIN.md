## [2026-02-18] Commit: 792a848adfbc0f5e9b27eabb9a7486bbefa90e7f
- **Summary**: Configurable Gemini model and API key via environment variables in commit analysis script.
- **Acquired knowledge**: Use the environment variable 'KIL_GEMINI_MODEL' to override the default LLM model in KIL scripts., Support 'KIL_GEMINI_API_KEY' as a valid environment variable for Gemini authentication., Default the Gemini model to 'gemini-flash-latest' for commit analysis tasks.
- **Rules to follow**: Hardcoding specific LLM model versions (e.g., 'gemini-1.5-flash') in operational scripts, preventing easy upgrades or testing.
- **Outstanding context**: -
- **Scope**: scripts/analyze_commit.py, KIL configuration
- **Confidence**: 1.0
- **Severity**: low
- **Review deadline**: -
- **Source**: llm
## [2026-02-17] Commit: dfbd198814375dc68484f54d4777dc7c93d0c080
- **要約**: pre-commit実行時にpost-commitフックの設置状態を強制チェックするガード機能の導入
- **獲得した知識**: pre-commitフックにおいて、post-commitフックが存在し、かつ 'KIL_MANAGED_HOOK: post-commit' という識別子が含まれているかを検証しなければならない。, フックの検証に失敗した場合は、コミットを中断し 'scripts/bootstrap_kil.ps1' の実行をユーザーに促すこと。, Gitの core.hooksPath 設定を考慮し、絶対パスおよびリポジトリルートからの相対パスの両方でフックディレクトリを特定するロジックを維持すること。
- **守るべきルール**: KIL管理外のpost-commitフックを手動で設置し、自動化プロセスをバイパスすること。, PowerShellスクリプトで外部コマンドの出力をキャプチャする際、ErrorActionPreferenceを適切に制御せずに実行結果を判定すること。
- **未解決の文脈**: Husky経由のBashスクリプトでGit設定をパースしているが、Windows/Linux間のパス区切り文字の差異に関する厳密なテストが不足している可能性がある。, bootstrap_kil.ps1 におけるエラー出力の配列化処理が、特定のPowerShellバージョンに依存する挙動を含んでいる可能性がある。
- **対象範囲**: .husky/_/pre-commit, scripts/bootstrap_kil.ps1, Git Hooks configuration
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-17] Commit: b28a03656cf5d562b8f9172c69a3680bca942951
- **要約**: KILレビュー専用ダッシュボードの導入と、リスクフィルタリング・ヘルスチェック機能の実装
- **獲得した知識**: KILの運用健全性を「コミット遅延数」「解析経過日数」「Markdown比率」の3指標で評価・監視する。, レビュー専用のデータソースとして `docs/AGENT_BRAIN_REVIEW.jsonl` を、軽量な運用指針として `docs/KIL_MINI_RULES.md` を維持・活用する。, リスク分布に基づいたフィルタリング機能を活用し、高リスクな変更を優先的にレビュー対象とする。
- **守るべきルール**: 解析の遅延（Lag）が発生している状態で、古い知識に基づいた自動判断を無批判に受け入れること。, PowerShell環境において、Husky等のツールを経由してBash依存のスクリプトや構文をフックに混入させること。
- **未解決の文脈**: Husky経由のBashスクリプトとPowerShell環境（bootstrap_kil.ps1）の完全な互換性確保と自動検知ロジックの洗練。, AGENT_BRAIN_INDEX.jsonl と AGENT_BRAIN_REVIEW.jsonl の間のデータ整合性維持メカニズム。
- **対象範囲**: KIL運用管理, ダッシュボード, リスク管理, Git Hook
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-17] Commit: 7d40b87e3b5ea31995e8fafbb46fa6200b157370
- **要約**: post-commit hookの実行ログをGit管理対象外に設定
- **獲得した知識**: Git hookの実行によって生成される一時的なログファイルは、原則として .gitignore に追加し、リポジトリにコミットしない。
- **守るべきルール**: 自動生成される実行ログ（.logファイル）をGitの追跡対象に含めること。
- **未解決の文脈**: ログファイルが docs/ 配下に生成されているが、プロジェクトの標準的なログ出力先（logs/等）に集約すべきか検討の余地がある。
- **対象範囲**: .gitignore, Git Hooks, KIL Runtime
- **確度**: 1.0
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-17] Commit: b44c45fce3487cd1decf5c306a17c90e6c4a304a
- **要約**: chore: sync KIL knowledge records after dashboard update
- **獲得した知識**: コミット差分の影響範囲を限定してレビューし、不要な範囲の仮説を避ける。
- **守るべきルール**: -
- **未解決の文脈**: 現時点で確度が高い未解決課題は確認できませんでした。
- **対象範囲**: docs
- **確度**: 0.35
- **重要度**: medium
- **レビュー期限**: -
- **ソース**: fallback

## [2026-02-17] Commit: 930fb5a4c6ddea460262f93c8c0f704122f74868
- **要約**: Geminiからのレスポンス解析におけるJSON抽出ロジックの堅牢化
- **獲得した知識**: LLMのレスポンス解析には、Markdownコードブロックの抽出と、中括弧のネスト深さを追跡するロジックを組み合わせて使用する。, 解析失敗時のエラーメッセージには、原因特定を容易にするためレスポンスのプレビュー（最大1200文字程度）を含める。, 実行時のエラーログ（docs/AGENT_BRAIN_ERROR.log）はGit管理対象外とする。
- **守るべきルール**: LLMが純粋なJSONのみを返すと盲信し、単純な正規表現のみでパースを試みること。, 解析エラー時にレスポンス内容を破棄し、デバッグ情報を残さないこと。
- **未解決の文脈**: 中括弧のカウントによるJSON抽出ロジックにおいて、極めて複雑なエスケープ文字を含む文字列リテラルに対する完全な堅牢性の検証。, maxOutputTokensの倍増（1536→3072）に伴う、APIコストおよびレスポンス遅延への影響評価。
- **対象範囲**: scripts/analyze_commit.py, .gitignore, KIL Runtime
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-17] Commit: 131847d75c9c39cb24532e31a0c46272075dbcc1
- **要約**: LLMレスポンス（特にGemini）のJSONパース処理における堅牢性の向上とエラー情報の詳細化
- **獲得した知識**: LLMの出力パースには直接 json.loads を使用せず、マークダウン等のノイズを除去可能な抽出ロジック（_parse_json_from_model_text等）を介在させる。, パース失敗時のエラーメッセージには、原因調査を容易にするため、定数（LLM_RESPONSE_TEXT_PREVIEW）で制限したレスポンスのプレビューを含める。
- **守るべきルール**: LLMの出力を単純な strip() だけで json.loads に渡すこと（Gemini等のペイロード形式の変化に対応できないため）。, パース失敗時に、受信した生データの内容を一切出力しないこと。
- **未解決の文脈**: _parse_json_from_model_text の内部実装（正規表現等）がカバーしきれない特殊なフォーマットが存在する可能性。
- **対象範囲**: scripts/analyze_commit.py, LLMレスポンス解析ロジック
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-17] Commit: 9f3ff0ee1c6e9c037bdfc65e21d44c7c51615949
- **要約**: Geminiからのレスポンス解析におけるJSON抽出ロジックの堅牢化
- **獲得した知識**: LLMのレスポンス解析には、Markdownコードブロックの抽出と、中括弧のネスト深さを追跡するロジックを組み合わせて使用する。, 解析失敗時のエラーメッセージには、原因特定を容易にするためレスポンスのプレビュー（最大1200文字程度）を含める。, 実行時のエラーログ（docs/AGENT_BRAIN_ERROR.log）はGit管理対象外とする。
- **守るべきルール**: LLMが純粋なJSONのみを返すと盲信し、単純な正規表現のみでパースを試みること。, 解析エラー時にレスポンス内容を破棄し、デバッグ情報を残さないこと。
- **未解決の文脈**: 中括弧のカウントによるJSON抽出ロジックにおいて、極めて複雑なエスケープ文字を含む文字列リテラルに対する完全な堅牢性の検証。, maxOutputTokensの倍増（1536→3072）に伴う、APIコストおよびレスポンス遅延への影響評価。
- **対象範囲**: scripts/analyze_commit.py, .gitignore, KIL Runtime
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-17] Commit: 1062c93c8388dbb1e9d8d8d0e81a70540d7fe038
- **要約**: LLMレスポンス解析（JSONパース）の堅牢化に関する運用知識の記録
- **獲得した知識**: LLMの出力パースには直接 json.loads を使用せず、Markdownコードブロックの抽出と中括弧のネスト深さ追跡を組み合わせた専用ロジック（_parse_json_from_model_text等）を介在させる。, パース失敗時のエラーメッセージには、原因特定を容易にするため、定数で制限されたレスポンスのプレビュー（最大1200文字程度）を含める。, 実行時のエラーログ（docs/AGENT_BRAIN_ERROR.log）はGit管理対象外（.gitignore）とする。
- **守るべきルール**: LLMが純粋なJSONのみを返すと盲信し、単純な strip() や正規表現のみでパースを試みること。, 解析エラー時に受信した生データを破棄し、デバッグ情報をログに残さないこと。
- **未解決の文脈**: 中括弧のカウントによるJSON抽出ロジックにおいて、極めて複雑なエスケープ文字を含む文字列リテラルに対する完全な堅牢性の検証。, maxOutputTokensの倍増（1536→3072）に伴う、APIコストおよびレスポンス遅延への影響評価。
- **対象範囲**: scripts/analyze_commit.py, docs/AGENT_BRAIN.md, LLMレスポンス解析ロジック
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-17] Commit: 50c5569352794e9f0a19ac45c1c9ea5ceb627cc2
- **要約**: Gemini APIにおける構造化JSON出力の要求と失敗時のフォールバック機構の導入
- **獲得した知識**: Gemini APIへのリクエスト時、まずは generationConfig に responseMimeType: application/json を設定して構造化出力を試みる。, 構造化出力のリクエストが失敗（RuntimeError等）した場合は、従来のプレーンなリクエスト設定で再試行するフォールバック処理を実装する。
- **守るべきルール**: APIの構造化出力機能に過度に依存し、エラー時の代替手段を用意しないこと。, リクエスト失敗時に原因を切り分けず、一律に処理を中断すること。
- **未解決の文脈**: フォールバックが発生した際のログ出力が不十分であり、運用中にどちらのモードが適用されたか追跡が困難。, RuntimeError のキャッチ範囲が広く、リトライすべき一時的エラーと設定エラーの区別がなされていない。
- **対象範囲**: scripts/analyze_commit.py, Gemini API integration
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-17] Commit: b5a34d9551a6f6b4699e27e0d3659f6b1722e21d
- **要約**: Gemini APIにおける構造化JSON出力の要求と失敗時のフォールバック機構の導入
- **獲得した知識**: Gemini APIへのリクエスト時、まずは generationConfig に responseMimeType: application/json を設定して構造化出力を試みる。, 構造化出力のリクエストが失敗（RuntimeError等）した場合は、従来のプレーンなリクエスト設定で再試行するフォールバック処理を実装する。
- **守るべきルール**: APIの構造化出力機能に過度に依存し、エラー時の代替手段を用意しないこと。, リクエスト失敗時に原因を切り分けず、一律に処理を中断すること。
- **未解決の文脈**: フォールバックが発生した際のログ出力が不十分であり、運用中にどちらのモードが適用されたか追跡が困難。, RuntimeError のキャッチ範囲が広く、リトライすべき一時的エラーと設定エラーの区別がなされていない。
- **対象範囲**: scripts/analyze_commit.py, Gemini API integration
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-17] Commit: d49716a556d6da98126f63b67fc6ecd7ee5552f0
- **要約**: KILドキュメント（AGENT_BRAIN）のパス解決ロジックの動的化と診断情報の可視化
- **獲得した知識**: KILドキュメントの探索は、スキルルートからカレントディレクトリまで5段階の優先順位（skill_root/docs, skills/docs, repo_root/docs, repo_parent/docs, cwd/docs）で行う。, AGENT_BRAIN_INDEX.jsonl または AGENT_BRAIN.md が存在するディレクトリを優先的に選択する。, APIレスポンスに診断情報（diagnostics）を含め、フロントエンドで探索状況（存在有無、選択理由）を表示可能にする。
- **守るべきルール**: 特定の相対パス（例: ../../docs）のみを固定で参照し、環境差異（開発環境 vs デプロイ環境）を考慮しない実装を避ける。
- **未解決の文脈**: 探索候補パスが api.py 内にハードコードされており、リポジトリ構成の根本的な変更時にはこのリストの更新が必要。, requested_source パラメータにおいて 'fallback' が指定された場合に 'all' へ内部変換されるなど、一部のパラメータ解釈が暗黙的である。
- **対象範囲**: KIL (Knowledge Integration Loop) レビュー機能, ドキュメントパス解決ロジック（api.py）, レビュー画面UI（kil-review.js）
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-17] Commit: 67290714ea53a8cdb6d4c81bb3b810c639f39726
- **要約**: KILレビューメタデータの同期とダッシュボードAPI接続の堅牢化（フォールバック実装）
- **獲得した知識**: フロントエンドからのAPI呼び出しには、現在のOriginに加え、localhost/127.0.0.1および特定のフォールバックポート（8765, 8000）を候補として順次試行するロジックを実装する。, API接続失敗時のエラーメッセージには、試行したURLと具体的なエラー原因（HTTPステータスや例外メッセージ）を含め、デバッグを容易にする。, KILドキュメント（AGENT_BRAIN.md）の更新時は、INDEX.jsonlおよびREVIEW.jsonlのメタデータも同期させる。
- **守るべきルール**: APIエンドポイントを単一の相対パスや特定のホスト・ポートに固定し、環境差異による接続失敗を許容すること。, APIリクエスト失敗時に、どのエンドポイントでどのようなエラーが発生したかの詳細を破棄すること。
- **未解決の文脈**: フォールバック対象のポート番号（8765, 8000）がJavaScript内にハードコードされており、インフラ構成の変更時に手動更新が必要。, 複数のエンドポイントを順次試行するため、ネットワークタイムアウトの設定がない場合、最終的なエラー表示までに時間がかかる可能性がある。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/kil-review.js, docs/AGENT_BRAIN.md, KIL Dashboard API integration
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-18] Commit: 67c769581d4fbaee5f7869609da632dfb931a9c2
- **要約**: KIL計画書およびスケジューラスクリプトのUTF-8正規化と、KIL自律学習ループの運用ルールの明文化。
- **獲得した知識**: post-commitフックによりscripts/analyze_commit.pyを自動実行し、最新の知識をAGENT_BRAINに反映する。, タスク開始前にAGENT_BRAIN.mdおよびAGENT_BRAIN_INDEX.jsonlの最新5件以上を確認し、制約や未解決事項を引き継ぐ。, GEMINI_API_KEY等の機密情報はリポジトリ外の環境変数ファイル（~/.ax/secrets/kintone.env等）で管理する。, AGENT_BRAINの更新が止まっていないか、エントリ数の推移を定期的に確認する。
- **守るべきルール**: APIキーやモデル名などの機密情報をリポジトリ内のファイルに直接記述する。, AGENT_BRAINの反映失敗を理由にコミットをブロックする（エラーログを記録し、次回タスク開始時に復旧させる）。, 過去のAGENT_BRAINの履歴を確認せずに新規タスクの判断を行う。
- **未解決の文脈**: 反映処理失敗時の復旧対応が運用ルール（手動/次回開始時）に依存しており、自動リトライ等の仕組みは未定義。, UTF-8正規化が他の既存スクリプトにも必要かどうかの全量調査。
- **対象範囲**: docs/KIL_PLAN.md, scripts/analyze_commit.py, AGENT_BRAIN 運用フロー, 環境変数・秘匿情報管理
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-18] Commit: 5b32cadfe24a1b629baa69ab27360f4d1a74d728
- **要約**: ワークフローテンプレートのUX改善およびアーカイブ済みワークフロー管理画面の分離
- **獲得した知識**: ワークフローのステップ情報やノート情報は、APIレスポンス返却前に `_normalize_workflow_template_steps` 等の正規化関数を必ず通すこと。, アーカイブ済みワークフローの管理ロジックは `workflow-archive-pages.js` に集約し、メインのダッシュボードロジックから分離すること。, サイドバーのリンク情報は HTML の `data-sidebar-links` 属性を介して JSON 形式でフロントエンドに渡す設計を維持する。
- **守るべきルール**: アクティブなワークフローとアーカイブ済みワークフローの表示・操作ロジックを同一の JS ファイルやテンプレートに混在させること。, API レスポンスにおいて、正規化されていない生の DB 行データをそのままフロントエンドに返却すること。
- **未解決の文脈**: 正規化ロジック（_normalize_workflow_template_steps 等）が複数の API エンドポイントで重複定義されている可能性があるため、共通ユーティリティへの集約が必要か確認が必要。, フロントエンドのトースト通知や共通処理が `common.js` に依存しているが、ページ分割に伴い依存関係の整理が必要になる可能性がある。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/routes, skills/mfcloud-expense-receipt-reconcile/dashboard/static/js, skills/mfcloud-expense-receipt-reconcile/dashboard/templates
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-18] Commit: 004e2c56e3df3e5fc6f6695a952d3eb78abeda3b
- **要約**: ワークフロー作成画面の簡素化と年月処理の自動補完ロジックの導入
- **獲得した知識**: 年月の入力値は `resolveFormYearMonth` を通じて取得し、未入力や不正値（2000年未満、1-12月以外）の場合は現在の年月をデフォルトとして適用する。, UI上の「小見出し」という表記は「補足説明」に統一する。, ワークフロー作成時の確認ダイアログには、ユーザーが直接変更できない内部的な詳細情報（ソースURL件数など）を含めず、簡潔な内容にする。
- **守るべきルール**: フロントエンドのイベントハンドラ内で個別に年月の必須チェックバリデーションを実装すること（リゾルバによる自動補完に任せる）。, ワークフロー作成のメインフローにおいて、頻繁に変更しない高度な設定（複数URLの追加等）を露出させ、UIを複雑化させること。
- **未解決の文脈**: サーバーサイド（Python）でのデフォルト値設定と、フロントエンド（JS）での `resolveFormYearMonth` によるデフォルト値決定ロジックが二重管理になっている可能性がある。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/index.js, skills/mfcloud-expense-receipt-reconcile/dashboard/templates/expense_workflow_copy.html
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-18] Commit: b311521df2b7e94d78eef2d04cfaf3126991038e
- **要約**: 管理センター（Error Center）へのWFアーカイブ管理およびKIL Review機能の統合と、ワークフロー設定制約の導入
- **獲得した知識**: ワークフローテンプレートには 'preflight' と 'mf_reconcile' のステップを必須とする。, ワークフローのステップタイマーはデフォルト5分、最大10,080分（1週間）の範囲で設定する。, WFアーカイブおよびKIL Reviewへのアクセスは、独立したパスではなく '/errors?tab=workflow-archive' および '/errors?tab=kil-review' を使用する。, ワークフローの各ステップには、定義された標準タイトル（WORKFLOW_TEMPLATE_REQUIRED_STEP_TITLES）を適用する。
- **守るべきルール**: 管理センター外に独立した管理用ページを新設すること。, 1週間（10,080分）を超えるワークフロータイマーの設定。, 必須ステップ（preflight, mf_reconcile）を欠いたワークフローテンプレートの定義。
- **未解決の文脈**: 旧パス（/workflow-pages/archived, /kil-review）からのリダイレクト処理が残存しているため、フロントエンドのリンクを直接タブ指定形式に完全移行した後に削除を検討する必要がある。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/routes/pages.py, skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/, ワークフローテンプレート定義
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-18] Commit: b8ec49d7c8b5cd579defec61d942f88f7e6ce90f
- **要約**: ワークスペースの定義を「エージェントの作業場」から「人間による自動化準備・管理ハブ」へ変更し、運用管理用のメタデータ項目を追加しました。
- **獲得した知識**: ワークスペース（Automation Hub）は、エージェントが直接操作する場所ではなく、人間が自動化運用を準備・管理する画面として定義する。, 各自動化リンクには「担当者」「推奨エージェント」「最終見直し日」のメタデータを付与し、運用の透明性と鮮度を維持する。, エージェントへの指示出しは、URL・目的・プロンプトをパッケージ化した「実行指示セット」をコピーして利用する運用を推奨する。
- **守るべきルール**: エージェントが直接この管理画面を操作することを前提とした設計やプロンプトの作成。, 担当者や見直し日を更新せず、プロンプトやリンクの有効性を放置すること。
- **未解決の文脈**: 推奨エージェントの選択肢（Codex, ChatGPT, Claude, Gemini等）がHTMLにハードコードされており、新しいモデルへの対応にコード修正が必要。, 削除された「ステータスページ」へのリンクの代替確認手段が定義されていない。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/templates/workspace.html, skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_pages.py
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-18] Commit: d7581456e185355a7eee7d77d3e91aa5224c7721
- **要約**: ダッシュボードにおけるワークフロー管理機能の改善（タイマー設定の追加、正規化処理の徹底、アーカイブ管理の分離）
- **獲得した知識**: ワークフローのステップ情報（タイトル、アクション、タイマー等）は、API返却前に必ず _normalize_workflow_template_steps 等の正規化関数を通すこと。, サイドバーのリンク情報は HTML の data-sidebar-links 属性を介した JSON 形式での受け渡しを維持する。, ワークフローのステップタイマー設定（timer_minutes）を適切に処理・保存し、テストコードで検証すること。
- **守るべきルール**: アクティブなワークフローとアーカイブ済みワークフローの表示・操作ロジックを同一の JS ファイルやテンプレートに混在させること。, API レスポンスにおいて、正規化されていない生の DB 行データをそのままフロントエンドに返却すること。
- **未解決の文脈**: 正規化ロジック（_normalize_workflow_template_steps 等）が複数の API エンドポイントで重複定義されている可能性があるため、共通ユーティリティへの集約が必要。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/routes/, skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/, skills/mfcloud-expense-receipt-reconcile/dashboard/templates/
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-18] Commit: c40c2d71d91e251828b539124a1d6d9d249085cf
- **要約**: ダッシュボードにおけるワークフロー管理機能の改善（タイマー設定の追加、正規化処理の徹底、アーカイブ管理の分離）
- **獲得した知識**: ワークフローのステップ情報（タイトル、アクション、タイマー等）は、API返却前に必ず _normalize_workflow_template_steps 等の正規化関数を通すこと。, サイドバーのリンク情報は HTML の data-sidebar-links 属性を介した JSON 形式での受け渡しを維持する。, ワークフローのステップタイマー設定（timer_minutes）を適切に処理・保存し、テストコードで検証すること。
- **守るべきルール**: アクティブなワークフローとアーカイブ済みワークフローの表示・操作ロジックを同一の JS ファイルやテンプレートに混在させること。, API レスポンスにおいて、正規化されていない生の DB 行データをそのままフロントエンドに返却すること。
- **未解決の文脈**: 正規化ロジック（_normalize_workflow_template_steps 等）が複数の API エンドポイントで重複定義されている可能性があるため、共通ユーティリティへの集約が必要。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/routes/, skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/, skills/mfcloud-expense-receipt-reconcile/dashboard/templates/
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: b10b43fc01d02b897d795b7ef12cbdc73ae4aae2
- **要約**: ドキュメントの鮮度確認（freshness check）をKIL依存のターゲットから、環境変数で指定されたディレクトリ配下のファイルベースのチェックに移行しました。
- **獲得した知識**: ドキュメント監視対象のルートディレクトリは環境変数 `AX_DOC_FRESHNESS_ROOTS` で定義する。, ドキュメント鮮度確認API（/api/errors/document-freshness）は `limit` クエリパラメータによる取得件数の制限をサポートしなければならない。, フロントエンドの表示ロジックは、サマリー情報（total, displayed, hidden）に基づいて、表示制限がかかっている状態をユーザーに通知する設計にする。
- **守るべきルール**: 監視対象のドキュメントパスをソースコード内にハードコードすること。, 大量のドキュメントが存在する環境で、リミットを設けずに全件のメタデータを一度に取得・表示しようとすること。
- **未解決の文脈**: 既存のKILターゲットベースのロジックが他のコンポーネントに残存していないかの確認が必要。, 正規表現によるファイル抽出ロジックが複雑なディレクトリ構造において意図通り動作するかの検証。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/routes/api_runs.py, skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/errors.js, skills/mfcloud-expense-receipt-reconcile/dashboard/templates/errors.html
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: a0bc595144db6e8c63722fd44e058fcc28291a82
- **要約**: ワークフローテンプレートMVP実装に向けたダッシュボード機能の更新と、ワークスペースリンク昇格前のチェックポイント。
- **獲得した知識**: ワークフローのステップ情報は、API返却前に必ず正規化関数（_normalize_workflow_template_steps等）を介在させること。, サイドバーのリンク情報は、HTMLのdata-sidebar-links属性を用いたJSON形式での受け渡しを維持すること。, ワークフローのコピー・編集画面において、template_idとtemplate_modeの初期値設定を厳密に管理し、テストで検証すること。
- **守るべきルール**: APIレスポンスにおいて、正規化されていない生のDBデータを直接フロントエンドに返却すること。, アクティブなワークフローとアーカイブ済みワークフローの操作ロジックを、分離せずに同一のJS/テンプレートに混在させること。
- **未解決の文脈**: 正規化ロジックが複数のAPIエンドポイントに分散しており、共通化の余地がある。, ワークスペースリンクの昇格（promotion）に伴う大規模な構造変更が予定されており、既存のリンク生成ロジックへの影響が懸念される。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/, docs/workflow_template_mvp_*
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: 2026-03-05
- **ソース**: llm

## [2026-02-19] Commit: 8ebddc703ab6d6fb3dda42f018b72135ab101d32
- **要約**: ウィザード形式の年月バリデーション修正およびプリフライト情報の統合
- **獲得した知識**: ウィザード操作を前提とするスキルでは、起動時に core_scheduler.stop_worker() を呼び出し、タイマーによる自動実行を明示的に無効化する。, 年月(YM)のバリデーションはウィザードの入力フローに適合させ、不整合な状態での進行を防止する。
- **守るべきルール**: ユーザーがウィザードで対話的な操作を行っている最中に、バックグラウンドで非同期の自動処理を並行して稼働させる（データの競合や予期せぬ上書きのリスクがあるため）。
- **未解決の文脈**: タイマー実行を再開するための条件や、手動実行と自動実行の切り替えに関する運用ポリシーの定義。, プリフライト情報をターゲットカードに統合したことによる、UIの複雑化や情報の視認性への影響評価。
- **対象範囲**: mfcloud-expense-receipt-reconcile スキルのダッシュボードおよびスケジューラ制御, ウィザード形式の入力バリデーションロジック
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: fc271b473adb1e79f076c0496ae69d8febadb964
- **要約**: テンプレートレベルでの月の値のバリデーション（クランプ処理）の導入
- **獲得した知識**: Jinja2テンプレート内で月（month）を扱う際は、`| int` でキャストした上で1〜12の範囲内に収まるようクランプ処理を行う。, HTMLの `input type="number"` の `min`/`max` 属性だけでなく、初期値（value属性）自体もテンプレート側で安全な値に制限する。
- **守るべきルール**: バックエンドのバリデーションを過信し、テンプレート側で生の変数をそのまま `value` 属性に流し込むこと。, hidden属性のinput要素に対して、範囲外の値をそのまま保持させること。
- **未解決の文脈**: 複数のテンプレート（index.html, expense_workflow_copy.html）で同様のクランプ処理が重複している。共通のJinja2マクロまたはカスタムフィルタとして共通化を検討すべき。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/templates/
- **確度**: 1.0
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: 39967571dfb302c470b3d9499169a7cbccb6d830
- **要約**: 経費精算ワークフロー画面からのスケジューラUI（タイマー自動実行設定）の削除
- **獲得した知識**: mfcloud-expense-receipt-reconcileのダッシュボード（index.html）にはスケジューラUI（scheduler-panel、scheduler-toggle等）を配置しない。, 当該ページのHTMLで /static/js/scheduler.js をロードしない。, ダッシュボードのテストコードでは、スケジューラ関連のIDや属性が存在しないことを検証する。
- **守るべきルール**: 明確な再導入の指示がない限り、削除されたスケジューラ関連のHTML要素やJavaScript参照を復元すること。
- **未解決の文脈**: サーバーサイドにスケジューラ実行用のAPIやロジックが残存している可能性があるが、今回の差分からは不明。, プロジェクト全体で scheduler.js が不要になったのか、このスキル固有の変更なのかの確認が必要。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/templates/index.html, skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_pages.py
- **確度**: 1.0
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: 8290c89ebc62c52f0f118b7ef5a231b7a99f178f
- **要約**: ワークスペースの追加リンク機能における文言の日本語統一、およびピン留めリンク機能の導入と状態管理の更新。
- **獲得した知識**: ピン留めリンクの最大数は6件（MAX_PINNED_LINKS）に制限する。, リンクの追加・削除・全削除などの状態変更時には、必ず `clearLinkUndoNotice` を呼び出して取り消し通知の状態をリセットする。, リンク一覧の描画には `renderLinkLists` を使用し、通常リンクとピン留めリンクの双方を同期して更新する。
- **守るべきルール**: リンク更新処理において `clearLinkUndoNotice` の呼び出しを漏らすこと（UI上の通知不整合の原因となる）。, ピン留めリンクの上限（6件）を定数 `MAX_PINNED_LINKS` 以外でハードコードすること。
- **未解決の文脈**: コミットメッセージが「文言の日本語統一」となっているが、実際にはピン留め機能のロジック変更や定数追加が含まれており、変更内容とメッセージに乖離がある。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/workspace.js
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: bfb99aaafcfcc544986f2161571b474c6c82d272
- **要約**: AGENT_BRAINの更新と、ワークスペースダッシュボードAPIにおける固定リンク(pinned_links)対応およびワークフロー正規化ルールの適用。
- **獲得した知識**: APIレスポンス返却前に、ワークフローのステップ情報は必ず正規化関数（_normalize_workflow_template_steps等）を介在させること。, サイドバーのリンク情報は、HTMLのdata-sidebar-links属性を用いたJSON形式での受け渡しを維持すること。, ワークフローのコピー・編集画面において、template_idとtemplate_modeの初期値設定を厳密に管理し、テストで検証すること。, ワークスペースの状態管理において、pinned_links（固定リンク）をサポートし、リビジョン競合時のマージ対象に含めること。
- **守るべきルール**: 正規化されていない生のDBデータを直接フロントエンドに返却すること。, アクティブなワークフローとアーカイブ済みワークフローの操作ロジックを、分離せずに同一のJS/テンプレートに混在させること。
- **未解決の文脈**: 正規化ロジックが複数のAPIエンドポイントに分散しており、共通化の余地がある。, ワークスペースリンクの昇格（promotion）に伴う大規模な構造変更が予定されている。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/, docs/AGENT_BRAIN.md
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: 67ca33ef39d708a341cc1e0d715627d401d730ed
- **要約**: PowerShellにおけるファイル書き出し時のエンコーディングをUTF-8 (BOMなし) に統一する方針の策定と自動チェックの導入
- **獲得した知識**: PowerShellでファイルを書き出す際は Set-Content/Add-Content/Out-File -Encoding utf8 を使用しない。, 代わりに [System.Text.UTF8Encoding]($false) を使用した .NET の [System.IO.File]::WriteAllText() 等、または utf8NoBOM を明示的に使用する。, .ps1 ファイルに対するエンコーディングチェック（scripts/check_text_encoding.py）をパスさせること。
- **守るべきルール**: PowerShellスクリプト内での -Encoding utf8 オプションの使用（BOMが付与される可能性があるため）。, UTF-8 BOM付きでのファイル保存。
- **未解決の文脈**: 正規表現による静的チェック（DISALLOWED_POWERSHELL_ENCODING_PATTERN）であるため、動的なコマンド生成や特殊なエイリアス使用による回避を完全には捕捉できない可能性がある。
- **対象範囲**: リポジトリ内の全PowerShellスクリプト（.ps1）, エンコーディング管理方針（README.md）, CI/プリコミット時のエンコーディングバリデーション
- **確度**: 1.0
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: 399252e1fd3bd3823e4f2ff2e43f984dc45ac806
- **要約**: ダッシュボードのJavaScriptファイルにおける文字化けの修正
- **獲得した知識**: 日本語等のマルチバイト文字を含むソースファイルは、必ず UTF-8 (BOMなし) エンコーディングで保存する。, UIテキストの修正を含むコミットを行う際は、ブラウザ上での表示確認を必須とする。
- **守るべきルール**: エディタの自動判別ミスによる文字化け（Mojibake）を含んだ状態でのコードコミット。, BOM（Byte Order Mark）付きのUTF-8での保存（一部のツールや環境で予期せぬ動作を引き起こす可能性があるため）。
- **未解決の文脈**: UIコピー（文言）がJavaScriptファイル内に直接ハードコードされており、エンコーディング問題の影響を受けやすい。i18n（国際化）対応による文言の外部管理化が望ましい。, パッチ内で修正されていない他のラベル（preflight, amazon_decide_print等）にも文字化けが残存している可能性がある。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/index.js
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: f5d813f2e33545e316d932fe5a993efa4642739b
- **要約**: ダッシュボードのフロントエンドJavaScriptを機能別にモジュール化
- **獲得した知識**: ダッシュボードのフロントエンド機能を追加・修正する際は、役割に応じたファイル（index.api.js, index.render.js等）にロジックを分散させること。, HTMLテンプレートでスクリプトを読み込む際は、依存関係を考慮した特定の順序（constants -> state -> api -> render -> events -> index）を厳守すること。
- **守るべきルール**: index.js に全てのロジックを直接記述し、肥大化させること。, モジュール間の依存関係を無視して、HTML内でのスクリプト読み込み順序を変更すること。
- **未解決の文脈**: ES Modules (import/export) を使用せず、グローバルスコープでの関数・変数共有に依存しているため、名前衝突のリスクがある。, ビルドツール（Webpack/Vite等）が導入されていないため、ファイル分割によるHTTPリクエスト数の増加が発生している。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/, skills/mfcloud-expense-receipt-reconcile/dashboard/templates/
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: cc64d00af2464be6309201131a5f0da517ebcd74
- **要約**: APIおよびサービス層の巨大なモジュールを機能単位で分割し、互換性を維持するためのリファクタリングの実施。
- **獲得した知識**: APIエンドポイントやサービスロジックが肥大化した場合は、機能カテゴリ（folder, print, run, workflow等）ごとにファイルを分割して管理する。, フロントエンド（JavaScript）とバックエンドのインターフェース（グローバル変数やイベント名）の整合性を確認するためのコントラクトテストを導入・維持する。, モジュール分割時は、既存のAPIパスやシンボル定義が維持されているかを検証するテストコードをセットで作成する。
- **守るべきルール**: 1つのファイルに数千行規模のロジック（API定義やビジネスロジック）を詰め込み、単一責任原則に反する状態を放置すること。, フロントエンドが依存するJS側のグローバルシンボル（window.DashboardIndexEvents等）の定義有無を確認せずにリファクタリングを完了すること。
- **未解決の文脈**: 分割された各モジュール間での循環参照が発生しないよう、共通ヘルパー（api_helpers.py等）への依存関係を継続的に監視する必要がある。, 既存のテストコードが分割後の全エンドポイントを網羅できているかの再確認。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/routes/, skills/mfcloud-expense-receipt-reconcile/dashboard/services/, skills/mfcloud-expense-receipt-reconcile/tests/
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: 2026-03-19
- **ソース**: llm

## [2026-02-19] Commit: 3fc643af990dbdb1639f5d3e96e21ebe2257da42
- **要約**: APIエンドポイント登録における循環参照の解消と依存性注入の導入
- **獲得した知識**: サブモジュールが親モジュールや兄弟モジュールの関数を必要とする場合、直接インポートせず、登録用関数の引数として Callable（コールバック）を渡す依存性注入（DI）パターンを採用する。, DI用の引数には型ヒント（Callable[[...], ...], Any等）を明示し、インターフェースを定義する。
- **守るべきルール**: 同一パッケージ内のルート定義モジュール間で相互に import を行い、実行時エラーや初期化の複雑化を招くこと。, 循環参照を避けるために、関数内でローカルインポートを多用すること（DIの方が追跡可能性が高い）。
- **未解決の文脈**: 他の register_api_* 関数群においても同様の密結合が存在する可能性があり、必要に応じてDIパターンへの統一を検討すべきである。, api.py 内で定義されたプロキシ関数（_provider_source_status_for_ym_proxy）が増加した場合、管理用のファクトリや設定クラスへの集約が必要になる可能性がある。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/routes/
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: 9a6dddc35403fd90833a9c68b2d3b4595cc7bd29
- **要約**: APIルーターにおけるプロバイダーソース状態解決関数のインジェクションを検証するコントラクトテストの追加。
- **獲得した知識**: APIルーターの構築ロジック（create_api_router等）を変更する場合、依存するエンドポイント登録関数への引数注入が正しく行われているかを確認するテストを含めること。, 注入されるコールバック関数が、内部の実装関数（_provider_source_status_for_ym等）を正しく呼び出しているかを検証すること。
- **守るべきルール**: エンドポイント登録関数のシグネチャ変更時に、呼び出し元（ルーター構築部）のテストを更新せず、実行時のインジェクションエラーを見逃すこと。
- **未解決の文脈**: テスト内で多数のモック（_fake_endpoints）を手動定義しており、APIエンドポイントのカテゴリが増えるたびにテストコードのボイラープレートが増加する可能性がある。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/tests/test_dashboard_contract.py, APIルーティング定義
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm


## [2026-02-19] Dashboard skill pages: common shell + skill modules
- **Summary**: For dashboard expansion, define a shared-shell, skill-pages split so new skills can be added without creating monolithic files.
- **Acquired knowledge**: The dashboard should keep common layout, sidebar, and shared components in common paths, while each skill owns a separate page module under `dashboard/skill_pages` and skill-scoped services. Existing sidebar links should be driven by a shared registry so discovery stays consistent.
- **Rules to follow**: Keep the dashboard structure explicit by adding new skill features under `dashboard/` in two layers: 1) shared UI/contract modules (components, API helpers, base layout, common JS/CSS) and 2) skill-specific modules in `dashboard/skill_pages/<skill_name>.py` + `dashboard/services/<skill_name>/...`.
- **Rules to follow**: Register skill pages through a single `register_skill_pages(app)` path and keep route wiring in one place (`dashboard/routes/pages.py`) to avoid circular imports.
- **Rules to follow**: Ensure sidebar links are centrally defined/ rendered from dashboard config, not hardcoded per isolated page, so `index` and skill pages stay aligned.
- **Rules to follow**: When adding a new skill, update contract tests and page tests together with route/service changes.
- **Outstanding context**: Current implementations should be reviewed to verify all existing skill pages are converted to this split if they are still mixed in a single route file.
- **Scope**: skills/mfcloud-expense-receipt-reconcile/dashboard/*, tests around dashboard routes/services
- **Confidence**: 0.93
- **Severity**: medium
- **Review deadline**: -
- **Source**: human
## [2026-02-19] Commit: 97e8d23894e3dcb4957841827b1709c3b2d38df2
- **要約**: PPTXブラッシュアップ機能の追加と、スキル専用ページの共通アーキテクチャの導入
- **獲得した知識**: スキル固有のページロジックは `dashboard/skill_pages/` 配下にカプセル化して実装すること。, サイドバーのリンク情報は、HTMLの `data-sidebar-links` 属性を用いたJSON形式での受け渡しを維持し、フロントエンドで動的に生成すること。, 新しいスキルページを追加する際は、`pages.py` でのルーティング定義と、サイドバーへのリンク定義（href, tab, section）をセットで行うこと。
- **守るべきルール**: スキル固有の複雑なビジネスロジックを `routes/pages.py` に直接記述し、肥大化させること。, サイドバーのリンク情報をHTMLテンプレート内にハードコードして個別に定義すること。
- **未解決の文脈**: skill_pages アーキテクチャにおける各スキルクラスの共通インターフェース（Baseクラス等）の厳密な定義。, pptx_polish_portable.py のポータブル性の検証と、他スキルへの再利用性の向上。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: 07ec4341720e3f80bdb2d7da8168d95f445f21eb
- **要約**: PPTX整形ジョブのステータスメッセージにおける文字化けの解消とファイルエンコーディングの修正
- **獲得した知識**: ジョブの進捗メッセージなどのシステム内部から出力されるメッセージには、エンコーディングトラブルを避けるため原則として英語を使用するか、UTF-8（BOMなし）を厳守する。, Pythonソースファイルの保存形式はBOMなしUTF-8とし、ファイル先頭に不要な制御文字を含めない。
- **守るべきルール**: 非ASCII文字を含むメッセージを、実行環境のエンコーディングが不明確な状態でハードコードすること。, BOM付きUTF-8でPythonソースコードを保存すること。
- **未解決の文脈**: 他のエンドポイントやモジュールにおいても同様の文字化けが発生していないかの横断的な確認。, ハードコードされたメッセージの国際化（i18n）対応。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/routes/api_print_endpoints.py, ジョブステータス通知メッセージ管理
- **確度**: 1.0
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: 9b21f4ab255702b02f30f4dd22c820824cd80421
- **要約**: AGENT_BRAINドキュメントを最新のスキル追加およびアーキテクチャ変更（PPTX整形機能、スキル専用ページ構成、エンコーディング規則）に同期しました。
- **獲得した知識**: スキル固有のページロジックは `dashboard/skill_pages/` 配下にカプセル化して実装すること。, サイドバーのリンク情報は、HTMLの `data-sidebar-links` 属性を用いたJSON形式での受け渡しを維持し、フロントエンドで動的に生成すること。, Pythonソースファイルの保存形式はBOMなしUTF-8を厳守し、システム内部メッセージには原則として英語またはUTF-8（BOMなし）を使用すること。
- **守るべきルール**: スキル固有の複雑なビジネスロジックを `routes/pages.py` に直接記述し、ファイルを肥大化させること。, サイドバーのリンク情報をHTMLテンプレート内にハードコードして個別に定義すること。, 非ASCII文字を含むメッセージを、実行環境のエンコーディングが不明確な状態でハードコードすること。
- **未解決の文脈**: skill_pages アーキテクチャにおける各スキルクラスの共通インターフェース（Baseクラス等）の厳密な定義。, ハードコードされたメッセージの国際化（i18n）対応。, pptx_polish_portable.py のポータブル性の検証と、他スキルへの再利用性の向上。
- **対象範囲**: docs/, skills/mfcloud-expense-receipt-reconcile/dashboard/
- **確度**: 1.0
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: 2d7e074ff634e4c8eded61630e675dbabf45ca1c
- **要約**: ワークスペースのピン留めグループ管理機能の刷新と、削除確認UIの日本語化対応
- **獲得した知識**: ワークスペースのピン留め管理には 'pinned-groups' という命名・ID体系を使用する, 削除確認ダイアログ等のUIメッセージは日本語で実装する, 開発時の一時ファイル（tmp_*, workspace_*.js, ws.diff, *.bak等）はリポジトリに含めない
- **守るべきルール**: ワークスペースのグループ管理に旧称の 'pinned-links' を使用すること, 作業用のスクラッチファイルやバックアップファイルをコミットに含めること
- **未解決の文脈**: スケジューラー関連コンポーネントの整理（一部テストで削除された要素の整合性確認と、不要になったJS/CSSのクリーンアップ）
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/, .gitignore, docs/AGENT_BRAIN.md
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: 03cf36666128fffafb45af98d3cd17f55ce9f4e9
- **要約**: Skillディレクトリ構造の標準化とベースライン定義、およびスクリプト型Skillへのテスト導入
- **獲得した知識**: 各Skillディレクトリには 'SKILL.md' と 'skill.yaml' を必須とする。, Skillの構成要素として 'scripts' および 'tests' ディレクトリを標準的なオプションとして定義する。, Skillの準拠状況は 'docs/skill-structure-baseline.json' で管理し、'scripts/check_skill_structure.py' で検証する。
- **守るべきルール**: メタデータファイル（SKILL.md, skill.yaml）が欠落した状態でのSkillの新規作成。, 共通のパース処理（日付、金額、CSV等）をテストコードなしで実装すること。
- **未解決の文脈**: 全Skillが標準構造に完全準拠しているわけではなく、'docs/structure-refactor-roadmap.md' に基づく段階的なリファクタリングが必要。, 構造チェックスクリプトのCIパイプラインへの完全な統合。
- **対象範囲**: skills/ 配下の全ディレクトリ, docs/ 構造管理ドキュメント, scripts/ 構造チェックツール
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: 2026-03-19
- **ソース**: llm

## [2026-02-19] Commit: 8414c4c46fbf1c5dbfb36d3d00f9268b3781c1d0
- **要約**: Skillディレクトリ構造の厳格なチェックを行うCIワークフローの導入
- **獲得した知識**: Skillのディレクトリ構造は `scripts/check_skill_structure.py --strict` による検証をパスしなければならない。, ファイル保存時にBOM（Byte Order Mark）を含めないように徹底する。
- **守るべきルール**: CIの構造チェックをバイパスするようなディレクトリ構成の変更。, エディタ設定による意図しないBOM（Byte Order Mark）の付与。
- **未解決の文脈**: scripts/check_skill_structure.py が定義する具体的なバリデーションルール（必須ファイル等）のドキュメント化。
- **対象範囲**: .github/workflows/skill-structure-check.yml, skills/ 配下のディレクトリ構造およびファイル形式
- **確度**: 0.9
- **重要度**: medium
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: 14c4eda98ca2b30ff57d3fe2069d62b91ba5b6db
- **要約**: ダッシュボードの500エラー修正（変数名衝突の解消とテンプレートの文字化け修正）
- **獲得した知識**: ユーティリティ関数名（例: safe_incident_id）と同一の変数名をローカルスコープで使用しない。resolved_incident_id 等の明確に区別できる変数名を採用すること。, HTMLテンプレートのデフォルト値やメタデータに文字化けした文字列（mojibake）を含めない。必要に応じて英語表記または適切なエンコーディングの日本語を使用する。
- **守るべきルール**: 関数名を変数名で上書き（シャドウイング）し、同一スコープ内での再利用を不可能にする実装。, 開発環境のエンコーディング不備に起因する不正な文字列のコミット。
- **未解決の文脈**: 外部スクリプト（error_status.py, error_plan_generate.py等）をサブプロセスとして呼び出しており、引数構造の変更に対して脆弱な構造になっている。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/routes/api_runs.py, skills/mfcloud-expense-receipt-reconcile/dashboard/templates/index.html
- **確度**: 1.0
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: f3c5c9ab8e465855ee44ad609f0b5014707383fb
- **要約**: mf_reconcileステップの削除とダッシュボードの文字化け修正
- **獲得した知識**: Pythonソースコード内の日本語文字列は、文字化けを防ぐため適切なエンコーディング（UTF-8）で保存・管理し、コミット前に表示を確認すること。, ワークフローの必須ステップ定義（WORKFLOW_TEMPLATE_REQUIRED_STEP_ACTIONS等）を更新した際は、関連するテストコードの期待値も同期させること。
- **守るべきルール**: 不適切なエンコーディングによるマルチバイト文字（文字化け）の混入。, 削除済みのワークフローアクションを必須定義やテンプレート内に残存させること。
- **未解決の文脈**: mf_reconcileステップの削除に伴う、外部ドキュメントやユーザーマニュアルの更新要否の確認。, テストコード内でのUI要素（scheduler-panel等）の存在確認ロジックの整理。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard, skills/mfcloud-expense-receipt-reconcile/tests
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: ee9cacc6409dba4aac0f4feef97f1bf197b4bf72
- **要約**: 非ASCII文字を含むファイルパスをGitコマンドから正確に取得するための修正
- **獲得した知識**: Gitコマンドでファイルパス一覧を取得する際は -z オプションを使用し、ヌル文字で分割する。, subprocessでGit出力を扱う際は text=False でバイト列として取得し、明示的にデコードする。
- **守るべきルール**: Gitのパス出力を標準の改行区切りや text=True でパースすること（非ASCII文字がクォートやエスケープされるリスクがあるため）。
- **未解決の文脈**: プロジェクト内の他のスクリプトにおけるGitパス取得処理の横断的な確認。
- **対象範囲**: scripts/check_text_encoding.py, Git操作を含むPythonスクリプト
- **確度**: 1.0
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm

## [2026-02-19] Commit: dbcef8066ae8a3210e0367a254344602d1b8c09a
- **要約**: ワークフロータスクカードのUI改善（コンパクト/詳細表示の切り替え機能追加とラベルの標準化）
- **獲得した知識**: トグルボタンのラベルには標準的なハイフン「-」を使用し、全角文字や特殊なマイナス記号を避ける。, MVPフェーズにおける機能制限（自動実行の未実装など）は、UI上の注釈（data-template-step-mvp-note）でユーザーに明示する。
- **守るべきルール**: UIのラベルや定数に、視覚的に区別がつきにくい特殊文字（全角マイナス「−」など）を混在させること。
- **未解決の文脈**: タイマー機能の自動実行ロジックは未実装であり、現在はUI上の設定保存のみにとどまっている。, 注釈テキストが英語に変更されたが、プロジェクト全体の多言語対応方針との整合性確認が必要。
- **対象範囲**: skills/mfcloud-expense-receipt-reconcile/dashboard/static/js/, skills/mfcloud-expense-receipt-reconcile/dashboard/templates/components/expense_workflow_card.html
- **確度**: 0.9
- **重要度**: low
- **レビュー期限**: -
- **ソース**: llm


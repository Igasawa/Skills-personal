---
name: pptx
description: "プレゼン資料（.pptx）の作成・編集・解析スキル。新規作成、既存編集、レイアウト調整、コメント/ノート確認、テンプレート準拠作成に使う。"
---

# PPTX 作成・編集・解析スキル

## 概要

`.pptx` は ZIP 形式の OOXML（XML + メディア）で構成される。  
目的に応じて次の2系統を使い分ける。

- 文章・軽微確認: `markitdown` でテキスト抽出
- 構造編集・厳密調整: OOXML を展開して XML を直接編集

## 内容の読み取りと解析

### テキスト抽出
発表資料の文言だけ確認したい場合:

```bash
python -m markitdown path-to-file.pptx
```

### 生XMLアクセスが必要なケース
次の要件がある場合は OOXML 展開が必要:
- コメント
- スピーカーノート
- レイアウト/マスター
- アニメーション
- 詳細な書式・テーマ調整

展開コマンド:
```bash
python ooxml/scripts/unpack.py <office_file> <output_dir>
```

補足:
- `unpack.py` の想定位置は `skills/pptx/ooxml/scripts/unpack.py`（プロジェクトルート基準）
- 見つからない場合は `find . -name "unpack.py"` で探索する

### 重要ファイル
- `ppt/presentation.xml`: プレゼン全体メタ情報とスライド参照
- `ppt/slides/slide{N}.xml`: 各スライド本体
- `ppt/notesSlides/notesSlide{N}.xml`: スピーカーノート
- `ppt/comments/modernComment_*.xml`: コメント
- `ppt/slideLayouts/`: レイアウト定義
- `ppt/slideMasters/`: マスター定義
- `ppt/theme/`: テーマ（色・フォント）
- `ppt/media/`: 画像などメディア

### タイポグラフィ/配色の抽出
既存デザインを踏襲する場合は最初に確認する:
1. `ppt/theme/theme1.xml` の `<a:clrScheme>` と `<a:fontScheme>`
2. 代表スライド（例: `ppt/slides/slide1.xml`）の `<a:rPr>` と色指定
3. XML全体から `<a:solidFill>`, `<a:srgbClr>` などを検索

## テンプレートなしで新規作成

新規作成は `html2pptx` ワークフローを使う。

### デザイン原則

作成前に必ず次を明示する:
1. テーマ（業種、トーン、対象読者）
2. ブランド要件（会社名や既存色が指定されていれば反映）
3. 採用する配色と理由

必須要件:
- コードを書く前にデザイン方針を文章で示す
- フォントは Web safe のみ（Arial, Helvetica, Times New Roman, Georgia, Courier New, Verdana, Tahoma, Trebuchet MS, Impact）
- サイズ・太さ・色で視覚階層を作る
- 高コントラストで可読性を確保する
- スライド間で余白・配置・表現を統一する

### 配色選定ガイド
- 既定色に固定せず、題材に合う色を選ぶ
- テーマ、業界、温度感、ブランドを同時に見る
- 基本は 3〜5色（主色 + 補助色 + アクセント）
- 背景と文字のコントラストを優先する

例（必要に応じて調整）:
- クラシックブルー: `#1C2833`, `#2E4053`, `#AAB7B8`, `#F4F6F6`
- ティール&コーラル: `#5EA8A7`, `#277884`, `#FE4447`, `#FFFFFF`
- ブラック&ゴールド: `#BF9A4A`, `#000000`, `#F4F6F6`
- セージ&テラコッタ: `#87A96B`, `#E07A5F`, `#F4F1DE`, `#2C2C2C`

### レイアウト指針
- 図表を含む場合は「ヘッダー + 2カラム（40/60 など）」を優先する
- もしくは図表を全面に使う全画面レイアウトを選ぶ
- テキストの下に図表を縦積みする構成は避ける

### 実装ワークフロー
1. `html2pptx.md` を**全量**読む（範囲指定での部分読み禁止）
2. スライドごとに HTML を作る（例: 16:9 なら `720pt x 405pt`）
   - テキストは `<p>`, `<h1>`-`<h6>`, `<ul>`, `<ol>` を使う
   - 図表差し込み位置は `class="placeholder"` で明示する
   - グラデーションやアイコンは先に PNG ラスタライズして参照する
3. `scripts/html2pptx.js` で変換し `pptx.writeFile()` で保存する
4. サムネイルで目視検証し、崩れを修正して再生成する

サムネイル生成例:
```bash
python scripts/thumbnail.py output.pptx workspace/thumbnails --cols 4
```

目視チェック項目:
- 文字切れ（ヘッダー帯、図形、スライド端）
- 文字重なり
- 余白不足・境界接触
- コントラスト不足

## 既存PPTXの編集

既存スライド編集は OOXML 直接編集を基本とする。

### 編集ワークフロー
1. `ooxml.md` を**全量**読む（範囲指定での部分読み禁止）
2. `python ooxml/scripts/unpack.py <office_file> <output_dir>` で展開
3. 主に `ppt/slides/slide{N}.xml` と関連ファイルを編集
4. 各編集直後に必ず検証:
   ```bash
   python ooxml/scripts/validate.py <dir> --original <file>
   ```
5. 問題がなければ再パック:
   ```bash
   python ooxml/scripts/pack.py <input_directory> <office_file>
   ```

## テンプレートありで新規作成

既存テンプレート準拠で作る場合は、テンプレ在庫化を先に行う。

### ワークフロー
1. テンプレ情報を抽出する
   - テキスト抽出: `python -m markitdown template.pptx > template-content.md`
   - `template-content.md` を全量読む
   - サムネイル生成: `python scripts/thumbnail.py template.pptx`
2. テンプレ在庫（`template-inventory.md`）を作成する
   - 全スライドを 0-index で列挙
   - レイアウト用途と特徴を記録
3. 在庫に基づき構成案を作る
   - 1枚目は導入/表紙向けレイアウト
   - 本文は内容に合う安全なテキスト中心レイアウト
   - 列数は内容数と一致させる（2項目なら2カラム）
4. 必要スライドを複製・並べ替えし、プレースホルダを置換
5. サムネイル再確認し、崩れを修正

`template-inventory.md` の最小例:
```markdown
# Template Inventory Analysis
**Total Slides: [count]**
**IMPORTANT: Slides are 0-indexed (first slide = 0, last slide = count-1)**

## [Category Name]
- Slide 0: [Layout code if available] - Description/purpose
- Slide 1: [Layout code] - Description/purpose
```

## サムネイルグリッド作成

基本:
```bash
python scripts/thumbnail.py input.pptx
```

出力先と列数指定:
```bash
python scripts/thumbnail.py input.pptx workspace/thumbnails --cols 4 --name my-grid
```

用途:
- レイアウト比較
- 目視レビュー
- テンプレ在庫化

## スライドを画像化

用途:
- デザイン比較
- 差分レビュー
- 外部共有用の静的書き出し

一般的な流れ:
1. PPTX を PDF へ変換
2. PDF を PNG/JPG へ分割
3. ページ順で命名整理

## コードスタイル

- 変更範囲を最小にする
- 目的外の XML 再整形を避ける
- 1編集ごとに検証し、壊れた状態を持ち越さない
- パスとスライド番号をログへ残す

## 依存関係

主要:
- Python
- `markitdown`
- `pptxgenjs`（html2pptx利用時）
- LibreOffice / Poppler（必要に応じて）

OOXML操作:
- `ooxml/scripts/unpack.py`
- `ooxml/scripts/validate.py`
- `ooxml/scripts/pack.py`

## 失敗しやすいポイント

- テンプレ解析なしで複製を始める
- 列レイアウトと実データ件数が不一致
- 図表配置で縦積みを選び可読性が落ちる
- 検証を後回しにしてエラー箇所が追跡不能になる
- サムネイル確認を省略して文字切れを見落とす

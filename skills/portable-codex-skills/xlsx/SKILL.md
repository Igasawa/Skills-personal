---
name: xlsx
description: "数式・書式・分析・可視化を含むスプレッドシート作業（.xlsx/.xlsm/.csv/.tsv）の包括スキル。新規作成、既存編集、分析、数式再計算、財務モデル品質管理に使う。"
---

# XLSX 作成・編集・分析スキル

## 出力要件

### 全Excelファイル共通
- 数式エラーをゼロにする（`#REF!`, `#DIV/0!`, `#VALUE!`, `#N/A`, `#NAME?`）。
- 既存テンプレート編集時は、既存の書式・命名・配置規約を最優先する。
- 既存規約がある場合は、本ファイルの一般規約より既存規約を優先する。

### 財務モデル向け規約
- ユーザー指定や既存テンプレートがない場合は、次の色規約を使う。
  - 青文字（`RGB 0,0,255`）: 入力値
  - 黒文字（`RGB 0,0,0`）: 数式・計算
  - 緑文字（`RGB 0,128,0`）: 同一ブック内リンク
  - 赤文字（`RGB 255,0,0`）: 外部ファイルリンク
  - 黄背景（`RGB 255,255,0`）: 重要前提・要更新セル
- 数値書式:
  - 年は文字列（例: `"2026"`）
  - 通貨は `"$#,##0"` 形式、ヘッダーに単位を明記（例: `Revenue ($mm)`）
  - ゼロは `-` 表示（パーセント含む）
  - パーセントは既定で `0.0%`
  - 倍率は `0.0x`
  - 負数は `-123` ではなく `(123)`

### 数式構築ルール
- 成長率・マージン・倍率などの前提は前提セルに分離する。
- 式内ハードコードを避け、セル参照を使う。
  - 例: `=B5*(1+$B$6)`（`=B5*1.05` ではなく）
- 範囲のずれ、参照切れ、循環参照、期間間の式不整合を必ず確認する。
- 境界値（ゼロ、負数、欠損）で式を検証する。

### ハードコード値の記録
- ハードコード値には出典をコメントまたは表の近傍に記載する。
- 記載形式:
  - `Source: [System/Document], [Date], [Specific Reference], [URL if applicable]`

## 概要

ユーザーは `.xlsx` ファイルの作成・編集・分析を依頼する。用途に応じて `openpyxl` と `pandas` を使い分ける。

- `openpyxl`: 数式・書式保持を伴う編集
- `pandas`: 集計・分析・CSV/TSV操作

## 重要要件

- LibreOffice を使った再計算を前提にしてよい。
- 数式を使った場合、`recalc.py` による再計算とエラーチェックは必須。

## 読み取りと分析

### pandas 基本例
```python
import pandas as pd

# 読み取り
df = pd.read_excel("file.xlsx")                   # 先頭シート
all_sheets = pd.read_excel("file.xlsx", sheet_name=None)  # 全シート(dict)

# 確認
df.head()
df.info()
df.describe()

# 書き出し
df.to_excel("output.xlsx", index=False)
```

## 最重要: 計算値をハードコードしない

Excel の動的再計算を維持するため、Python で計算して固定値を書き込まず、Excel 数式を書く。

### NG（ハードコード）
```python
total = df["Sales"].sum()
sheet["B10"] = total
```

### OK（Excel数式）
```python
sheet["B10"] = "=SUM(B2:B9)"
sheet["C5"] = "=(C4-C2)/C2"
sheet["D20"] = "=AVERAGE(D2:D19)"
```

## 標準ワークフロー

1. ツール選定（`pandas` / `openpyxl`）
2. 新規作成または既存ブック読み込み
3. データ・数式・書式を編集
4. 保存
5. 数式再計算（数式を使った場合は必須）
6. エラー修正と再計算を繰り返し、エラーゼロで完了

再計算コマンド:
```bash
python recalc.py output.xlsx
```

## 新規作成例（openpyxl）
```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook()
sheet = wb.active

sheet["A1"] = "Hello"
sheet["B1"] = "World"
sheet.append(["Row", "of", "data"])
sheet["B2"] = "=SUM(A1:A10)"

sheet["A1"].font = Font(bold=True, color="FF0000")
sheet["A1"].fill = PatternFill("solid", start_color="FFFF00")
sheet["A1"].alignment = Alignment(horizontal="center")
sheet.column_dimensions["A"].width = 20

wb.save("output.xlsx")
```

## 既存編集例（openpyxl）
```python
from openpyxl import load_workbook

wb = load_workbook("existing.xlsx")
sheet = wb.active

for sheet_name in wb.sheetnames:
    s = wb[sheet_name]
    print(f"Sheet: {sheet_name}")

sheet["A1"] = "New Value"
sheet.insert_rows(2)
sheet.delete_cols(3)

new_sheet = wb.create_sheet("NewSheet")
new_sheet["A1"] = "Data"

wb.save("modified.xlsx")
```

## 数式再計算と検証

openpyxl は数式を文字列として保持し、計算結果は更新しない。`recalc.py` で再計算する。

```bash
python recalc.py <excel_file> [timeout_seconds]
```

例:
```bash
python recalc.py output.xlsx 30
```

`recalc.py` のポイント:
- 初回実行時に LibreOffice 側設定を自動セットアップ
- 全シートの数式を再計算
- 全セルを走査して Excel エラーを検出
- JSON でエラー件数・位置を返却

## 数式検証チェックリスト

- 参照先が存在するか
- 範囲の開始/終了が意図どおりか
- 横展開・縦展開で式が崩れていないか
- ゼロ除算や型不一致が起きないか
- 期間列で式パターンが一貫しているか

## データ分析パターン（pandas）

### 複数シート読み取り
```python
import pandas as pd

sheets = pd.read_excel("input.xlsx", sheet_name=None)
for name, df in sheets.items():
    print(name, df.shape)
```

### ピボット
```python
pivot = df.pivot_table(
    index="Region",
    columns="Product",
    values="Sales",
    aggfunc="sum",
    fill_value=0
)
```

### groupby 集計
```python
agg = df.groupby("Category", as_index=False)["Amount"].sum()

agg2 = df.groupby("Category", as_index=False).agg({
    "Amount": ["sum", "mean"],
    "Count": "sum"
})
```

### フィルタ・派生列
```python
filtered = df[df["Amount"] > 0]
filtered = filtered[(filtered["Region"] == "APAC") & (filtered["Status"] == "Open")]
filtered["Margin"] = filtered["Revenue"] - filtered["Cost"]
filtered = filtered.sort_values(["Region", "Amount"], ascending=[True, False])
```

### クリーニング
```python
df = df.drop_duplicates()
df = df.fillna({"Amount": 0, "Category": "UNKNOWN"})
df["Name"] = df["Name"].astype(str).str.strip()
df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
df.to_excel("cleaned.xlsx", index=False)
```

### 結合
```python
# 縦結合
stacked = pd.concat([df1, df2, df3], ignore_index=True)

# キー結合
merged = pd.merge(left_df, right_df, on="CustomerID", how="left")
```

## 可視化

`pandas` で分析し、最終納品が Excel の場合は必要に応じて `openpyxl.chart` でネイティブグラフ化する。

## 条件付き書式（openpyxl）
```python
from openpyxl.styles import PatternFill, Font

green_fill = PatternFill("solid", fgColor="C6EFCE")
red_fill = PatternFill("solid", fgColor="FFC7CE")

for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, min_col=2, max_col=2):
    cell = row[0]
    if cell.value is None:
        continue
    if cell.value >= 0:
        cell.fill = green_fill
    else:
        cell.fill = red_fill

for cell in sheet[1]:
    cell.font = Font(bold=True)
```

## パフォーマンスのコツ

- 必要列だけ読む（`usecols`）。
- 大規模データはチャンク分割で処理する。
- `dtype` 指定で推論コストを削減する。
- `openpyxl` では `read_only=True` / `write_only=True` を必要に応じて使う。

## ユーティリティ: 列幅自動調整
```python
from openpyxl.utils import get_column_letter

for col in sheet.columns:
    max_len = 0
    col_idx = col[0].column
    for cell in col:
        value = "" if cell.value is None else str(cell.value)
        max_len = max(max_len, len(value))
    sheet.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 80)
```

## `spreadsheet` スキルとの役割分担

- `xlsx`: 財務モデル、厳格な品質管理、数式中心、監査性重視
- `spreadsheet`: 軽量なデータ加工、探索分析、CSV/TSV中心

判断ルール:
1. 財務モデル・厳格規約があるなら `xlsx`
2. 軽量分析なら `spreadsheet`
3. 迷ったら、精度/追跡可能性が必要な場合は `xlsx`

競合時:
- まず `spreadsheet` で探索し、最終仕上げを `xlsx` で行う運用は可。

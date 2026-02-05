#!/usr/bin/env python3

from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path


def render_monthly_thread(
    *,
    template_path: Path,
    year: int,
    month: int,
    receipts_path: str | Path,
    reports_path: Path,
    notes: str,
) -> str:
    start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = date(year, month, last_day)
    replacements = {
        "{{YEAR}}": f"{year:04d}",
        "{{MONTH}}": f"{month:02d}",
        "{{RANGE_START}}": start.isoformat(),
        "{{RANGE_END}}": end.isoformat(),
        "{{NOTES}}": notes if notes else "なし",
        "{{RECEIPTS_PATH}}": str(receipts_path),
        "{{REPORTS_PATH}}": str(reports_path),
    }
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    else:
        template = (
            "# 月次処理スレッド\n\n"
            f"対象月：{year}年{month}月\n"
            f"対象期間：{start.isoformat()} ～ {end.isoformat()}\n"
            "対象ステータス：下書き / 未申請\n\n"
            "## 今月の前提・特記事項\n"
            "なし\n\n"
            "## レシート提供状況\n"
            f"- 保存場所：{receipts_path}\n"
            "- 形式：PDF\n\n"
            "## 今月の進め方\n"
            "- 基本方針：1明細=1レシート、金額/日付が一致しない場合は自動紐付けしない\n"
            "- 優先順位：完全一致 → 近似一致 → 要確認\n\n"
            "## 作業開始指示\n"
            "- Phase 1 (Scan) から開始\n"
        )
    for k, v in replacements.items():
        template = template.replace(k, v)
    return template

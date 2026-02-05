#!/usr/bin/env python3

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from common import safe_non_negative_int as _safe_non_negative_int  # noqa: E402


def derive_needs_review_from_rows(rows: list[Any]) -> tuple[int, dict[str, int]]:
    reason_counts: dict[str, int] = {}
    expense_keys: set[str] = set()
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        row_type = str(row.get("row_type") or "").strip()
        is_review_row = row_type == "needs_review"
        if not is_review_row:
            is_review_row = row.get("order_id") is None and row.get("rank") is None
        if not is_review_row:
            continue
        reason = str(row.get("review_reason") or "").strip() or "no_candidate_in_window"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        expense_id = str(row.get("mf_expense_id") or "").strip()
        expense_keys.add(expense_id if expense_id else f"row:{idx}")
    return len(expense_keys), reason_counts


def build_quality_gate(
    *,
    report: dict[str, Any] | None,
    report_json_path: Path,
    report_csv_path: Path,
    year: int,
    month: int,
) -> dict[str, Any]:
    ts = datetime.now().isoformat(timespec="seconds")
    if not isinstance(report, dict):
        return {
            "version": 1,
            "generated_at": ts,
            "year": year,
            "month": month,
            "status": "fail",
            "ready_for_submission": False,
            "summary": {"needs_review_count": 0, "error_like_count": 1},
            "needs_review": {
                "missing_use_date": 0,
                "missing_amount": 0,
                "no_candidate_in_window": 0,
                "unknown": 0,
            },
            "rules": {"allow_needs_review_count": 0, "blocking_reasons": ["missing_use_date", "missing_amount", "unknown"]},
            "issues": ["reconcile_report_missing_or_invalid"],
            "sources": {
                "missing_evidence_candidates_json": str(report_json_path),
                "missing_evidence_candidates_csv": str(report_csv_path),
            },
        }

    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    rows = report.get("rows") if isinstance(report.get("rows"), list) else []
    derived_count, derived_reasons = derive_needs_review_from_rows(rows)

    needs_review_count = _safe_non_negative_int(counts.get("needs_review_count"), default=derived_count)
    missing_use_date = _safe_non_negative_int(
        counts.get("needs_review_missing_use_date"),
        default=derived_reasons.get("missing_use_date", 0),
    )
    missing_amount = _safe_non_negative_int(
        counts.get("needs_review_missing_amount"),
        default=derived_reasons.get("missing_amount", 0),
    )
    no_candidate = _safe_non_negative_int(
        counts.get("needs_review_no_candidate_in_window"),
        default=derived_reasons.get("no_candidate_in_window", 0),
    )
    derived_unknown = sum(v for k, v in derived_reasons.items() if k not in {"missing_use_date", "missing_amount", "no_candidate_in_window"})
    known_total = missing_use_date + missing_amount + no_candidate
    unknown = max(derived_unknown, max(0, needs_review_count - known_total))
    needs_review_count = max(needs_review_count, known_total + unknown)

    error_like_count = missing_use_date + missing_amount + unknown
    if error_like_count > 0:
        status = "fail"
    elif needs_review_count > 0:
        status = "warn"
    else:
        status = "pass"

    return {
        "version": 1,
        "generated_at": ts,
        "year": year,
        "month": month,
        "status": status,
        "ready_for_submission": status == "pass",
        "summary": {
            "needs_review_count": needs_review_count,
            "error_like_count": error_like_count,
            "mf_missing_evidence": _safe_non_negative_int(counts.get("mf_missing_evidence")),
            "matched_expenses": _safe_non_negative_int(counts.get("matched_expenses")),
        },
        "needs_review": {
            "missing_use_date": missing_use_date,
            "missing_amount": missing_amount,
            "no_candidate_in_window": no_candidate,
            "unknown": unknown,
        },
        "rules": {"allow_needs_review_count": 0, "blocking_reasons": ["missing_use_date", "missing_amount", "unknown"]},
        "sources": {
            "missing_evidence_candidates_json": str(report_json_path),
            "missing_evidence_candidates_csv": str(report_csv_path),
        },
    }

#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from common import (  # noqa: E402
    load_order_exclusions as _load_exclusions,
    read_jsonl as _read_jsonl,
    write_json as _write_json,
)


def _is_excluded(obj: dict[str, Any], exclusions: set[tuple[str, str]], default_source: str) -> bool:
    if not exclusions:
        return False
    order_id = str(obj.get("order_id") or "").strip()
    if not order_id:
        return False
    source = str(obj.get("source") or default_source).strip()
    return (source, order_id) in exclusions


def _dedupe_orders(orders: list["Order"]) -> list["Order"]:
    seen: set[tuple[str, str, str]] = set()
    out: list["Order"] = []
    for o in orders:
        key = (o.source, o.order_id, o.pdf_path or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    return out


def _to_int_yen(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("円", "")
        m = re.search(r"-?\d+", s)
        return int(m.group(0)) if m else None
    return None


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.strip().replace("/", "-")
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$", value.strip())
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        try:
            return datetime.fromisoformat(s).date()
        except Exception:
            return None
    return None


def _in_year_month(d: date | None, year: int, month: int) -> bool:
    return bool(d and d.year == year and d.month == month)


@dataclass(frozen=True)
class Order:
    order_id: str
    order_date: date | None
    total_yen: int | None
    pdf_path: str | None
    receipt_url: str | None
    source: str

    @staticmethod
    def from_obj(obj: dict[str, Any], *, default_source: str) -> "Order | None":
        if obj.get("include") is False:
            return None
        order_id = str(obj.get("order_id") or "").strip()
        if not order_id:
            return None
        return Order(
            order_id=order_id,
            order_date=_to_date(obj.get("order_date") or obj.get("date")),
            total_yen=_to_int_yen(obj.get("total_yen") or obj.get("total")),
            pdf_path=(str(obj.get("pdf_path")).strip() if obj.get("pdf_path") else None),
            receipt_url=(str(obj.get("receipt_url")).strip() if obj.get("receipt_url") else None),
            source=str(obj.get("source") or default_source),
        )


@dataclass(frozen=True)
class MfExpense:
    expense_id: str
    use_date: date | None
    amount_yen: int | None
    vendor: str
    memo: str
    has_evidence: bool
    detail_url: str | None

    @staticmethod
    def from_obj(obj: dict[str, Any]) -> "MfExpense | None":
        expense_id = str(obj.get("expense_id") or obj.get("id") or "").strip()
        if not expense_id:
            return None
        vendor = str(obj.get("vendor") or obj.get("payee") or "").strip()
        memo = str(obj.get("memo") or obj.get("summary") or obj.get("description") or "").strip()
        return MfExpense(
            expense_id=expense_id,
            use_date=_to_date(obj.get("use_date") or obj.get("date")),
            amount_yen=_to_int_yen(obj.get("amount_yen") or obj.get("amount")),
            vendor=vendor,
            memo=memo,
            has_evidence=bool(obj.get("has_evidence", False)),
            detail_url=(str(obj.get("detail_url")).strip() if obj.get("detail_url") else None),
        )


def _days_diff(a: date | None, b: date | None) -> int | None:
    if not a or not b:
        return None
    return abs((a - b).days)


def _looks_like_amazon(text: str) -> bool:
    t = text.lower()
    return ("amazon" in t) or ("アマゾン" in text) or ("ｱﾏｿﾞﾝ" in text)


def _looks_like_rakuten(text: str) -> bool:
    t = text.lower()
    return ("rakuten" in t) or ("楽天" in text)


def reconcile(
    *,
    orders: list[Order],
    mf_expenses: list[MfExpense],
    year: int,
    month: int,
    date_window_days: int,
    max_candidates_per_mf: int,
) -> dict[str, Any]:
    orders_in_month = [o for o in orders if _in_year_month(o.order_date, year, month)]
    mf_in_month = [e for e in mf_expenses if _in_year_month(e.use_date, year, month)]
    mf_unknown_date = [e for e in mf_expenses if e.use_date is None]

    # Keep one record per expense id and prioritize records that are already in target month.
    mf_scope_by_id: dict[str, MfExpense] = {}
    for expense in [*mf_in_month, *mf_unknown_date]:
        if expense.expense_id in mf_scope_by_id:
            continue
        mf_scope_by_id[expense.expense_id] = expense
    mf_scope = list(mf_scope_by_id.values())
    mf_missing = [e for e in mf_scope if not e.has_evidence]

    amazon_all = [o for o in orders if o.source == "amazon"]
    rakuten_all = [o for o in orders if o.source == "rakuten"]
    amazon_in_month = [o for o in amazon_all if _in_year_month(o.order_date, year, month)]
    rakuten_in_month = [o for o in rakuten_all if _in_year_month(o.order_date, year, month)]

    needs_review_missing_use_date = 0
    needs_review_missing_amount = 0
    needs_review_no_candidate = 0
    needs_review_expense_ids: set[str] = set()
    matched_expense_ids: set[str] = set()

    rows: list[dict[str, Any]] = []
    for expense in mf_missing:
        base = {
            "mf_expense_id": expense.expense_id,
            "mf_use_date": expense.use_date.isoformat() if expense.use_date else None,
            "mf_amount_yen": expense.amount_yen,
            "mf_vendor": expense.vendor,
            "mf_memo": expense.memo,
            "mf_detail_url": expense.detail_url,
        }

        if expense.use_date is None:
            needs_review_missing_use_date += 1
            needs_review_expense_ids.add(expense.expense_id)
            rows.append(
                {
                    **base,
                    "row_type": "needs_review",
                    "review_reason": "missing_use_date",
                    "rank": None,
                    "order_id": None,
                    "order_date": None,
                    "total_yen": None,
                    "order_source": None,
                    "pdf_path": None,
                    "diff_days": None,
                    "score": None,
                }
            )
            continue

        if expense.amount_yen is None:
            needs_review_missing_amount += 1
            needs_review_expense_ids.add(expense.expense_id)
            rows.append(
                {
                    **base,
                    "row_type": "needs_review",
                    "review_reason": "missing_amount",
                    "rank": None,
                    "order_id": None,
                    "order_date": None,
                    "total_yen": None,
                    "order_source": None,
                    "pdf_path": None,
                    "diff_days": None,
                    "score": None,
                }
            )
            continue

        candidates: list[dict[str, Any]] = []
        for order in orders_in_month:
            if order.total_yen is None:
                continue
            if order.total_yen != expense.amount_yen:
                continue
            diff = _days_diff(expense.use_date, order.order_date)
            if diff is None or diff > date_window_days:
                continue

            score = 100
            score += max(0, 20 - 2 * diff)
            vendor_text = f"{expense.vendor} {expense.memo}"
            if order.source == "amazon" and _looks_like_amazon(vendor_text):
                score += 10
            if order.source == "rakuten" and _looks_like_rakuten(vendor_text):
                score += 10

            candidates.append(
                {
                    "order_id": order.order_id,
                    "order_date": order.order_date.isoformat() if order.order_date else None,
                    "total_yen": order.total_yen,
                    "pdf_path": order.pdf_path,
                    "receipt_url": order.receipt_url,
                    "order_source": order.source,
                    "diff_days": diff,
                    "score": score,
                }
            )

        candidates.sort(key=lambda x: (-int(x["score"]), int(x["diff_days"]), str(x.get("order_id") or "")))
        candidates = candidates[: max(0, int(max_candidates_per_mf))]

        if not candidates:
            needs_review_no_candidate += 1
            needs_review_expense_ids.add(expense.expense_id)
            rows.append(
                {
                    **base,
                    "row_type": "needs_review",
                    "review_reason": "no_candidate_in_window",
                    "rank": None,
                    "order_id": None,
                    "order_date": None,
                    "total_yen": None,
                    "order_source": None,
                    "pdf_path": None,
                    "diff_days": None,
                    "score": None,
                }
            )
            continue

        matched_expense_ids.add(expense.expense_id)
        for rank, cand in enumerate(candidates, start=1):
            rows.append(
                {
                    **base,
                    "row_type": "candidate",
                    "review_reason": None,
                    "rank": rank,
                    "order_id": cand["order_id"],
                    "order_date": cand["order_date"],
                    "total_yen": cand["total_yen"],
                    "order_source": cand["order_source"],
                    "pdf_path": cand["pdf_path"],
                    "diff_days": cand["diff_days"],
                    "score": cand["score"],
                }
            )

    needs_review_count = len(needs_review_expense_ids)
    matched_expenses = len(matched_expense_ids)

    return {
        "year": year,
        "month": month,
        "counts": {
            "amazon_orders_total": len(amazon_all),
            "amazon_orders_in_month": len(amazon_in_month),
            "rakuten_orders_total": len(rakuten_all),
            "rakuten_orders_in_month": len(rakuten_in_month),
            "orders_total": len(orders),
            "orders_in_month": len(orders_in_month),
            "mf_expenses_total": len(mf_expenses),
            "mf_expenses_in_month": len(mf_in_month),
            "mf_expenses_unknown_date": len(mf_unknown_date),
            "mf_scope_expenses": len(mf_scope),
            "mf_missing_evidence": len(mf_missing),
            "matched_expenses": matched_expenses,
            "needs_review_count": needs_review_count,
            "needs_review_missing_use_date": needs_review_missing_use_date,
            "needs_review_missing_amount": needs_review_missing_amount,
            "needs_review_no_candidate_in_window": needs_review_no_candidate,
            "report_rows": len(rows),
        },
        "rows": rows,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "mf_expense_id",
        "mf_use_date",
        "mf_amount_yen",
        "mf_vendor",
        "mf_memo",
        "mf_detail_url",
        "row_type",
        "review_reason",
        "rank",
        "order_id",
        "order_source",
        "order_date",
        "total_yen",
        "pdf_path",
        "diff_days",
        "score",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reconcile MF expenses with Amazon/Rakuten receipt PDFs")
    ap.add_argument("--amazon-orders-jsonl")
    ap.add_argument("--rakuten-orders-jsonl")
    ap.add_argument("--exclude-orders-json", help="path to exclude orders json")
    ap.add_argument("--mf-expenses-jsonl", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--date-window-days", type=int, default=7)
    ap.add_argument("--max-candidates-per-mf", type=int, default=5)
    args = ap.parse_args(argv)

    if not args.amazon_orders_jsonl and not args.rakuten_orders_jsonl:
        raise ValueError("Either --amazon-orders-jsonl or --rakuten-orders-jsonl is required.")

    amazon_raw = _read_jsonl(Path(args.amazon_orders_jsonl), required=True, strict=True) if args.amazon_orders_jsonl else []
    rakuten_raw = _read_jsonl(Path(args.rakuten_orders_jsonl), required=True, strict=True) if args.rakuten_orders_jsonl else []
    exclusions = _load_exclusions(args.exclude_orders_json)
    if exclusions:
        amazon_raw = [x for x in amazon_raw if not _is_excluded(x, exclusions, "amazon")]
        rakuten_raw = [x for x in rakuten_raw if not _is_excluded(x, exclusions, "rakuten")]
    mf_raw = _read_jsonl(Path(args.mf_expenses_jsonl), required=True, strict=True)
    orders = [o for o in (Order.from_obj(x, default_source="amazon") for x in amazon_raw) if o]
    orders += [o for o in (Order.from_obj(x, default_source="rakuten") for x in rakuten_raw) if o]
    orders = _dedupe_orders(orders)
    mf_expenses = [e for e in (MfExpense.from_obj(x) for x in mf_raw) if e]

    data = reconcile(
        orders=orders,
        mf_expenses=mf_expenses,
        year=int(args.year),
        month=int(args.month),
        date_window_days=int(args.date_window_days),
        max_candidates_per_mf=int(args.max_candidates_per_mf),
    )

    _write_json(Path(args.out_json), data)
    _write_csv(Path(args.out_csv), data["rows"])

    print(
        json.dumps(
            {"status": "success", "data": {"counts": data["counts"], "out_json": str(Path(args.out_json)), "out_csv": str(Path(args.out_csv))}},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

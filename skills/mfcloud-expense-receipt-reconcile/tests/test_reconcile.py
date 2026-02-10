from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from reconcile import MfExpense, Order, main as reconcile_main, reconcile


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_reconcile_prioritizes_highest_score_candidate() -> None:
    orders = [
        Order(
            order_id="AMZ-001",
            order_date=date(2026, 1, 11),
            total_yen=1000,
            pdf_path="amazon/pdfs/AMZ-001.pdf",
            receipt_url=None,
            source="amazon",
        ),
        Order(
            order_id="RAK-001",
            order_date=date(2026, 1, 10),
            total_yen=1000,
            pdf_path="rakuten/pdfs/RAK-001.pdf",
            receipt_url=None,
            source="rakuten",
        ),
    ]
    mf_expenses = [
        MfExpense(
            expense_id="MF-001",
            use_date=date(2026, 1, 10),
            amount_yen=1000,
            vendor="Amazon Japan",
            memo="備品",
            has_evidence=False,
            detail_url=None,
        )
    ]

    report = reconcile(
        orders=orders,
        mf_expenses=mf_expenses,
        year=2026,
        month=1,
        date_window_days=7,
        max_candidates_per_mf=5,
    )

    rows = [row for row in report["rows"] if row["mf_expense_id"] == "MF-001"]
    assert [row["order_id"] for row in rows] == ["AMZ-001", "RAK-001"]
    assert rows[0]["rank"] == 1
    assert rows[0]["score"] > rows[1]["score"]


def test_reconcile_respects_date_window_boundary() -> None:
    orders = [
        Order(
            order_id="IN-WINDOW",
            order_date=date(2026, 1, 3),
            total_yen=500,
            pdf_path="amazon/pdfs/IN-WINDOW.pdf",
            receipt_url=None,
            source="amazon",
        ),
        Order(
            order_id="OUT-WINDOW",
            order_date=date(2026, 1, 2),
            total_yen=500,
            pdf_path="amazon/pdfs/OUT-WINDOW.pdf",
            receipt_url=None,
            source="amazon",
        ),
    ]
    mf_expenses = [
        MfExpense(
            expense_id="MF-BOUNDARY",
            use_date=date(2026, 1, 10),
            amount_yen=500,
            vendor="Amazon",
            memo="文具",
            has_evidence=False,
            detail_url=None,
        )
    ]

    report = reconcile(
        orders=orders,
        mf_expenses=mf_expenses,
        year=2026,
        month=1,
        date_window_days=7,
        max_candidates_per_mf=5,
    )

    rows = [row for row in report["rows"] if row["mf_expense_id"] == "MF-BOUNDARY"]
    assert len(rows) == 1
    assert rows[0]["order_id"] == "IN-WINDOW"
    assert report["counts"]["needs_review_count"] == 0


def test_reconcile_reports_needs_review_reasons() -> None:
    mf_expenses = [
        MfExpense(
            expense_id="MF-MISSING-DATE",
            use_date=None,
            amount_yen=1000,
            vendor="Amazon",
            memo="",
            has_evidence=False,
            detail_url=None,
        ),
        MfExpense(
            expense_id="MF-MISSING-AMOUNT",
            use_date=date(2026, 1, 15),
            amount_yen=None,
            vendor="Amazon",
            memo="",
            has_evidence=False,
            detail_url=None,
        ),
        MfExpense(
            expense_id="MF-NO-CANDIDATE",
            use_date=date(2026, 1, 20),
            amount_yen=3000,
            vendor="Unknown",
            memo="",
            has_evidence=False,
            detail_url=None,
        ),
    ]

    report = reconcile(
        orders=[],
        mf_expenses=mf_expenses,
        year=2026,
        month=1,
        date_window_days=7,
        max_candidates_per_mf=5,
    )

    assert report["counts"]["needs_review_count"] == 3
    assert report["counts"]["needs_review_missing_use_date"] == 1
    assert report["counts"]["needs_review_missing_amount"] == 1
    assert report["counts"]["needs_review_no_candidate_in_window"] == 1
    reasons = {row["review_reason"] for row in report["rows"]}
    assert {"missing_use_date", "missing_amount", "no_candidate_in_window"} <= reasons


def test_reconcile_main_applies_order_exclusions(tmp_path: Path) -> None:
    amazon_orders_jsonl = tmp_path / "amazon_orders.jsonl"
    mf_expenses_jsonl = tmp_path / "mf_expenses.jsonl"
    out_json = tmp_path / "out.json"
    out_csv = tmp_path / "out.csv"
    exclusions_json = tmp_path / "exclude_orders.json"

    _write_jsonl(
        amazon_orders_jsonl,
        [
            {"order_id": "AMZ-A", "order_date": "2026-01-15", "total_yen": 1200, "pdf_path": "amazon/pdfs/AMZ-A.pdf"},
            {"order_id": "AMZ-B", "order_date": "2026-01-15", "total_yen": 1200, "pdf_path": "amazon/pdfs/AMZ-B.pdf"},
        ],
    )
    _write_jsonl(
        mf_expenses_jsonl,
        [
            {
                "expense_id": "MF-ONLY",
                "use_date": "2026-01-15",
                "amount_yen": 1200,
                "vendor": "Amazon",
                "memo": "消耗品",
                "has_evidence": False,
            }
        ],
    )
    exclusions_json.write_text(
        json.dumps({"ym": "2026-01", "exclude": [{"source": "amazon", "order_id": "AMZ-A"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    exit_code = reconcile_main(
        [
            "--amazon-orders-jsonl",
            str(amazon_orders_jsonl),
            "--exclude-orders-json",
            str(exclusions_json),
            "--mf-expenses-jsonl",
            str(mf_expenses_jsonl),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
            "--year",
            "2026",
            "--month",
            "1",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    candidate_order_ids = [row["order_id"] for row in data["rows"] if row["row_type"] == "candidate"]
    assert candidate_order_ids == ["AMZ-B"]


def test_reconcile_main_skips_rows_missing_both_date_and_amount(tmp_path: Path) -> None:
    amazon_orders_jsonl = tmp_path / "amazon_orders.jsonl"
    mf_expenses_jsonl = tmp_path / "mf_expenses.jsonl"
    out_json = tmp_path / "out.json"
    out_csv = tmp_path / "out.csv"

    _write_jsonl(
        amazon_orders_jsonl,
        [{"order_id": "AMZ-1", "order_date": "2026-01-15", "total_yen": 1200, "pdf_path": "amazon/pdfs/AMZ-1.pdf"}],
    )
    _write_jsonl(
        mf_expenses_jsonl,
        [
            # 明細ではない行（例: 申請者/タイトル/合計など）を想定
            {
                "expense_id": "MF-NOT-AN-EXPENSE",
                "use_date": None,
                "amount_yen": None,
                "vendor": "",
                "memo": "申請者 〜",
                "has_evidence": False,
            },
            # 正常な未添付明細
            {
                "expense_id": "MF-OK",
                "use_date": "2026-01-15",
                "amount_yen": 1200,
                "vendor": "Amazon",
                "memo": "消耗品",
                "has_evidence": False,
            },
        ],
    )

    exit_code = reconcile_main(
        [
            "--amazon-orders-jsonl",
            str(amazon_orders_jsonl),
            "--mf-expenses-jsonl",
            str(mf_expenses_jsonl),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
            "--year",
            "2026",
            "--month",
            "1",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["counts"]["mf_expenses_total"] == 1
    assert {row["mf_expense_id"] for row in data["rows"]} == {"MF-OK"}


def test_reconcile_main_prefers_order_total_yen_when_present(tmp_path: Path) -> None:
    amazon_orders_jsonl = tmp_path / "amazon_orders.jsonl"
    mf_expenses_jsonl = tmp_path / "mf_expenses.jsonl"
    out_json = tmp_path / "out.json"
    out_csv = tmp_path / "out.csv"

    _write_jsonl(
        amazon_orders_jsonl,
        [
            {
                "order_id": "AMZ-SPLIT-1",
                "order_date": "2026-01-15",
                "total_yen": 700,
                "order_total_yen": 1200,
                "pdf_path": "amazon/pdfs/AMZ-SPLIT-1_invoice.pdf",
                "doc_type": "tax_invoice",
            }
        ],
    )
    _write_jsonl(
        mf_expenses_jsonl,
        [
            {
                "expense_id": "MF-AMZ-SPLIT",
                "use_date": "2026-01-15",
                "amount_yen": 1200,
                "vendor": "Amazon",
                "memo": "split",
                "has_evidence": False,
            }
        ],
    )

    exit_code = reconcile_main(
        [
            "--amazon-orders-jsonl",
            str(amazon_orders_jsonl),
            "--mf-expenses-jsonl",
            str(mf_expenses_jsonl),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
            "--year",
            "2026",
            "--month",
            "1",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    candidates = [row for row in data["rows"] if row["row_type"] == "candidate"]
    assert len(candidates) == 1
    assert candidates[0]["order_id"] == "AMZ-SPLIT-1"


def test_reconcile_main_accepts_rakuten_only_input(tmp_path: Path) -> None:
    rakuten_orders_jsonl = tmp_path / "rakuten_orders.jsonl"
    mf_expenses_jsonl = tmp_path / "mf_expenses.jsonl"
    out_json = tmp_path / "out.json"
    out_csv = tmp_path / "out.csv"

    _write_jsonl(
        rakuten_orders_jsonl,
        [
            {"order_id": "RAK-A", "order_date": "2026-01-15", "total_yen": 1200, "pdf_path": "rakuten/pdfs/RAK-A.pdf"},
        ],
    )
    _write_jsonl(
        mf_expenses_jsonl,
        [
            {
                "expense_id": "MF-RAK",
                "use_date": "2026-01-15",
                "amount_yen": 1200,
                "vendor": "Rakuten",
                "memo": "消耗品",
                "has_evidence": False,
            }
        ],
    )

    exit_code = reconcile_main(
        [
            "--rakuten-orders-jsonl",
            str(rakuten_orders_jsonl),
            "--mf-expenses-jsonl",
            str(mf_expenses_jsonl),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
            "--year",
            "2026",
            "--month",
            "1",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    candidate_order_ids = [row["order_id"] for row in data["rows"] if row["row_type"] == "candidate"]
    assert candidate_order_ids == ["RAK-A"]


def test_reconcile_main_accepts_manual_only_input(tmp_path: Path) -> None:
    manual_orders_jsonl = tmp_path / "manual_orders.jsonl"
    mf_expenses_jsonl = tmp_path / "mf_expenses.jsonl"
    out_json = tmp_path / "out.json"
    out_csv = tmp_path / "out.csv"

    _write_jsonl(
        manual_orders_jsonl,
        [
            {
                "source": "manual",
                "order_id": "MANUAL-001",
                "order_date": "2026-01-15",
                "total_yen": 2400,
                "pdf_path": "manual/pdfs/2026-01-15_manual_2400_MANUAL-001.pdf",
            },
        ],
    )
    _write_jsonl(
        mf_expenses_jsonl,
        [
            {
                "expense_id": "MF-MANUAL",
                "use_date": "2026-01-15",
                "amount_yen": 2400,
                "vendor": "MANUAL ENTRY",
                "memo": "添付テスト",
                "has_evidence": False,
            }
        ],
    )

    exit_code = reconcile_main(
        [
            "--manual-orders-jsonl",
            str(manual_orders_jsonl),
            "--mf-expenses-jsonl",
            str(mf_expenses_jsonl),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
            "--year",
            "2026",
            "--month",
            "1",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["counts"]["manual_orders_total"] == 1
    assert data["counts"]["manual_orders_in_month"] == 1
    candidate_order_ids = [row["order_id"] for row in data["rows"] if row["row_type"] == "candidate"]
    assert candidate_order_ids == ["MANUAL-001"]


def test_reconcile_main_accepts_manual_provider_metadata_rows(tmp_path: Path) -> None:
    manual_orders_jsonl = tmp_path / "manual_orders.jsonl"
    mf_expenses_jsonl = tmp_path / "mf_expenses.jsonl"
    out_json = tmp_path / "out.json"
    out_csv = tmp_path / "out.csv"

    _write_jsonl(
        manual_orders_jsonl,
        [
            {
                "source": "manual",
                "provider": "chatgpt",
                "ingestion_channel": "provider_inbox",
                "order_id": "MANUAL-PROVIDER-001",
                "order_date": "2026-01-29",
                "total_yen": 2990,
                "pdf_path": "manual/pdfs/2026-01-29_chatgpt_manual_2990_MANUAL-PROVIDER-001.pdf",
            },
        ],
    )
    _write_jsonl(
        mf_expenses_jsonl,
        [
            {
                "expense_id": "MF-PROVIDER",
                "use_date": "2026-01-29",
                "amount_yen": 2990,
                "vendor": "OPENAI",
                "memo": "ChatGPT Team",
                "has_evidence": False,
            }
        ],
    )

    exit_code = reconcile_main(
        [
            "--manual-orders-jsonl",
            str(manual_orders_jsonl),
            "--mf-expenses-jsonl",
            str(mf_expenses_jsonl),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
            "--year",
            "2026",
            "--month",
            "1",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    candidate_rows = [row for row in data["rows"] if row["row_type"] == "candidate"]
    assert len(candidate_rows) == 1
    assert candidate_rows[0]["order_source"] == "manual"
    assert candidate_rows[0]["order_id"] == "MANUAL-PROVIDER-001"


def test_reconcile_main_requires_at_least_one_order_source(tmp_path: Path) -> None:
    mf_expenses_jsonl = tmp_path / "mf_expenses.jsonl"
    out_json = tmp_path / "out.json"
    out_csv = tmp_path / "out.csv"
    _write_jsonl(
        mf_expenses_jsonl,
        [
            {
                "expense_id": "MF-ONLY",
                "use_date": "2026-01-15",
                "amount_yen": 1200,
                "vendor": "Amazon",
                "memo": "消耗品",
                "has_evidence": False,
            }
        ],
    )

    with pytest.raises(
        ValueError,
        match="At least one of --amazon-orders-jsonl, --rakuten-orders-jsonl, --manual-orders-jsonl is required.",
    ):
        reconcile_main(
            [
                "--mf-expenses-jsonl",
                str(mf_expenses_jsonl),
                "--out-json",
                str(out_json),
                "--out-csv",
                str(out_csv),
                "--year",
                "2026",
                "--month",
                "1",
            ]
        )

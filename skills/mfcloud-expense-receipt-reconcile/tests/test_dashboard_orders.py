from __future__ import annotations

import json
from pathlib import Path

from dashboard.services.core_orders import _collect_orders


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _touch_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n")


def test_collect_orders_sets_pdf_name_from_absolute_path(tmp_path: Path) -> None:
    root = tmp_path / "2026-01"
    pdf_path = root / "amazon" / "pdfs" / "AMZ-001.pdf"
    _touch_pdf(pdf_path)
    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [{"order_id": "AMZ-001", "order_date": "2026-01-10", "status": "ok", "pdf_path": str(pdf_path)}],
    )

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["has_pdf"] is True
    assert orders[0]["pdf_name"] == "AMZ-001.pdf"


def test_collect_orders_supports_legacy_prefixed_pdf_path(tmp_path: Path) -> None:
    root = tmp_path / "2026-01"
    pdf_path = root / "amazon" / "pdfs" / "AMZ-LEGACY.pdf"
    _touch_pdf(pdf_path)
    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [{"order_id": "AMZ-LEGACY", "order_date": "2026-01-10", "status": "ok", "pdf_path": "amazon/pdfs/AMZ-LEGACY.pdf"}],
    )

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["has_pdf"] is True
    assert orders[0]["pdf_name"] == "AMZ-LEGACY.pdf"


def test_collect_orders_sets_no_pdf_name_when_file_missing(tmp_path: Path) -> None:
    root = tmp_path / "2026-01"
    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [{"order_id": "AMZ-NOFILE", "order_date": "2026-01-10", "status": "ok", "pdf_path": "AMZ-NOFILE.pdf"}],
    )

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["has_pdf"] is False
    assert orders[0]["pdf_name"] is None


def test_collect_orders_marks_ok_without_pdf_as_retry_needed(tmp_path: Path) -> None:
    root = tmp_path / "2026-01"
    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [{"order_id": "AMZ-RETRY", "order_date": "2026-01-10", "status": "ok", "item_name": "2026/01/10 / \u00A5500"}],
    )

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["status_label"] == "\u8981\u518d\u53d6\u5f97\uff08PDF\u306a\u3057\uff09"
    assert orders[0]["item_name"] is None


def test_collect_orders_keeps_single_item_name_for_duplicate_order_id(tmp_path: Path) -> None:
    root = tmp_path / "2026-01"
    pdf_path = root / "amazon" / "pdfs" / "AMZ-DUP.pdf"
    _touch_pdf(pdf_path)
    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [
            {
                "order_id": "AMZ-DUP",
                "order_date": "2026-01-10",
                "status": "ok",
                "item_name": "Earbuds",
                "total_yen": 3980,
                "pdf_path": str(pdf_path),
            },
            {
                "order_id": "AMZ-DUP",
                "order_date": "2026-01-10",
                "status": "no_receipt",
                "item_name": "Feedback page long text",
            },
        ],
    )

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["item_name"] == "Earbuds"
    assert " / " not in str(orders[0]["item_name"])


def test_collect_orders_does_not_adopt_no_receipt_item_when_primary_is_low_confidence(tmp_path: Path) -> None:
    root = tmp_path / "2026-01"
    pdf_path = root / "amazon" / "pdfs" / "AMZ-LOWCONF.pdf"
    _touch_pdf(pdf_path)
    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [
            {
                "order_id": "AMZ-LOWCONF",
                "order_date": "2026-01-10",
                "status": "ok",
                "item_name": "2026/01/10 / \u00A5980",
                "pdf_path": str(pdf_path),
            },
            {
                "order_id": "AMZ-LOWCONF",
                "order_date": "2026-01-10",
                "status": "no_receipt",
                "item_name": "Noisy fallback title",
            },
        ],
    )

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["item_name"] is None


def test_collect_orders_keeps_shortcut_urls_when_pdf_missing(tmp_path: Path) -> None:
    root = tmp_path / "2026-01"
    _write_jsonl(
        root / "rakuten" / "orders.jsonl",
        [
            {
                "order_id": "RAK-URL-001",
                "order_date": "2026-01-20",
                "status": "error",
                "detail_url": "https://order.my.rakuten.co.jp/purchase-history/?order_number=RAK-URL-001",
                "receipt_url": "https://order.my.rakuten.co.jp/purchase-history/?act=order_invoice",
            }
        ],
    )

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["has_pdf"] is False
    assert orders[0]["pdf_name"] is None
    assert orders[0]["detail_url"] == "https://order.my.rakuten.co.jp/purchase-history/?order_number=RAK-URL-001"
    assert orders[0]["receipt_url"] == "https://order.my.rakuten.co.jp/purchase-history/?act=order_invoice"


def test_collect_orders_defaults_to_excluded_when_total_is_dash(tmp_path: Path) -> None:
    root = tmp_path / "2026-01"
    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [
            {"order_id": "AMZ-DASH", "order_date": "2026-01-21", "status": "ok", "total_yen": "-"},
            {"order_id": "AMZ-PRICE", "order_date": "2026-01-21", "status": "ok", "total_yen": 1200},
        ],
    )

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 2

    by_id = {order["order_id"]: order for order in orders}
    assert by_id["AMZ-DASH"]["excluded"] is True
    assert by_id["AMZ-DASH"]["can_toggle"] is True
    assert by_id["AMZ-DASH"]["auto_excluded"] is False
    assert by_id["AMZ-PRICE"]["excluded"] is False

from __future__ import annotations

import json
from pathlib import Path

import pytest

import dashboard.services.core_orders as core_orders
from dashboard.services.core_orders import _collect_orders, _extract_item_name_from_text


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


def test_collect_orders_uses_pdf_fallback_item_name_when_low_confidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "2026-01"
    pdf_path = root / "amazon" / "pdfs" / "AMZ-PDF-FALLBACK.pdf"
    _touch_pdf(pdf_path)
    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [
            {
                "order_id": "AMZ-PDF-FALLBACK",
                "order_date": "2026-01-10",
                "status": "ok",
                "item_name": "2026/01/10 / \u00A51599",
                "pdf_path": str(pdf_path),
            }
        ],
    )

    monkeypatch.setattr(core_orders, "_extract_item_name_from_pdf", lambda _p: "NANAMI マグネット式ワイヤレス充電器")

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["item_name"] == "NANAMI マグネット式ワイヤレス充電器"


def test_extract_item_name_from_text_uses_delivered_section() -> None:
    text = "\n".join(
        [
            "領収書",
            "注文概要",
            "商品の小計: ¥1,599",
            "ご請求額: ¥1,599",
            "1月30日にお届け済み",
            "NANAMI マグネット式 ワイヤレス充電器",
            "販売: nanamihome",
        ]
    )
    assert _extract_item_name_from_text(text) == "NANAMI マグネット式 ワイヤレス充電器"


def test_extract_item_name_from_text_handles_rakuten_books_receipt_table() -> None:
    text = "\n".join(
        [
            "領収書（再発行） 発行日 ： 2026年02月08日",
            "利用明細",
            "注文番号 ： 213310-20260125-0555903016 注文日 ： 2026/01/25 発送日 ： 2026/01/26",
            "商品明細",
            "商品コード 商品名 数量 単価(税込) 金額(税込)",
            "9784473046963 こころが軽くなる 大人のなぞり書き 1 1,320 1,320",
            "合計金額(税込・10%) 1,320",
            "支払額 1,320",
        ]
    )
    assert _extract_item_name_from_text(text) == "こころが軽くなる 大人のなぞり書き"


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


def test_collect_orders_uses_pdf_fallback_item_name_for_rakuten_books(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "2026-01"
    pdf_path = root / "rakuten" / "pdfs" / "RAK-BOOKS.pdf"
    _touch_pdf(pdf_path)
    _write_jsonl(
        root / "rakuten" / "orders.jsonl",
        [
            {
                "order_id": "RAK-BOOKS",
                "order_date": "2026-01-25",
                "status": "ok",
                "item_name": "2026/01/25 / ¥1320",
                "pdf_path": str(pdf_path),
                "detail_url": "https://books.rakuten.co.jp/mypage/delivery/status?order_number=RAK-BOOKS",
                "receipt_url": "https://books.rakuten.co.jp/mypage/delivery/receiptPrint?order_number=RAK-BOOKS",
            }
        ],
    )

    monkeypatch.setattr(core_orders, "_extract_item_name_from_pdf", lambda _p: "こころが軽くなる 大人のなぞり書き")

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["item_name"] == "こころが軽くなる 大人のなぞり書き"


def test_collect_orders_uses_pdf_fallback_item_name_for_books_order_id_prefix_without_books_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "2026-01"
    pdf_path = root / "rakuten" / "pdfs" / "RAK-BOOKS-NO-URL.pdf"
    _touch_pdf(pdf_path)
    _write_jsonl(
        root / "rakuten" / "orders.jsonl",
        [
            {
                "order_id": "213310-20260125-0555903016",
                "order_date": "2026-01-25",
                "status": "ok",
                "item_name": None,
                "pdf_path": str(pdf_path),
                "detail_url": None,
                "receipt_url": None,
            }
        ],
    )

    monkeypatch.setattr(core_orders, "_extract_item_name_from_pdf", lambda _p: "こころが軽くなる 大人のなぞり書き")

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["item_name"] == "こころが軽くなる 大人のなぞり書き"


def test_collect_orders_does_not_use_pdf_fallback_for_non_books_rakuten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "2026-01"
    pdf_path = root / "rakuten" / "pdfs" / "RAK-REGULAR.pdf"
    _touch_pdf(pdf_path)
    _write_jsonl(
        root / "rakuten" / "orders.jsonl",
        [
            {
                "order_id": "RAK-REGULAR",
                "order_date": "2026-01-25",
                "status": "ok",
                "item_name": "2026/01/25 / ¥1320",
                "pdf_path": str(pdf_path),
                "detail_url": "https://order.my.rakuten.co.jp/purchase-history/?order_number=RAK-REGULAR",
            }
        ],
    )

    def _should_not_call(_p: Path) -> str:
        raise AssertionError("pdf fallback must not be used for non-books rakuten")

    monkeypatch.setattr(core_orders, "_extract_item_name_from_pdf", _should_not_call)

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["item_name"] is None


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


def test_collect_orders_defaults_to_excluded_when_total_is_zero(tmp_path: Path) -> None:
    root = tmp_path / "2026-01"
    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [
            {"order_id": "AMZ-ZERO", "order_date": "2026-01-21", "status": "ok", "total_yen": 0},
            {"order_id": "AMZ-PRICE", "order_date": "2026-01-21", "status": "ok", "total_yen": 1200},
        ],
    )

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 2

    by_id = {order["order_id"]: order for order in orders}
    assert by_id["AMZ-ZERO"]["excluded"] is True
    assert by_id["AMZ-ZERO"]["can_toggle"] is True
    assert by_id["AMZ-ZERO"]["auto_excluded"] is False
    assert by_id["AMZ-PRICE"]["excluded"] is False


def test_collect_orders_does_not_default_exclude_after_confirmation(tmp_path: Path) -> None:
    root = tmp_path / "2026-01"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "workflow.json").write_text(
        json.dumps({"amazon": {"confirmed_at": "2026-02-10T00:00:00"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [{"order_id": "AMZ-ZERO", "order_date": "2026-01-21", "status": "ok", "total_yen": 0}],
    )

    orders = _collect_orders(root, "2026-01", set())
    assert len(orders) == 1
    assert orders[0]["excluded"] is False

    orders = _collect_orders(root, "2026-01", {("amazon", "AMZ-ZERO")})
    assert len(orders) == 1
    assert orders[0]["excluded"] is True

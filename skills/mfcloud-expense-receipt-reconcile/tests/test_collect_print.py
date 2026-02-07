from __future__ import annotations

import json
from pathlib import Path

from collect_print import (
    _collect_orders_pdfs,
    _collect_missing_shortcut_orders,
    _resolve_orders_url,
    _resolve_receipt_env,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_collect_missing_shortcut_orders_filters_rows(tmp_path: Path) -> None:
    orders_jsonl = tmp_path / "amazon" / "orders.jsonl"
    existing_pdf = tmp_path / "amazon" / "pdfs" / "A-3.pdf"
    existing_pdf.parent.mkdir(parents=True, exist_ok=True)
    existing_pdf.write_bytes(b"%PDF-1.4\n")
    _write_jsonl(
        orders_jsonl,
        [
            {
                "order_id": "A-1",
                "order_date": "2026-01-03",
                "status": "ok",
                "detail_url": "https://example.invalid/detail/A-1",
                "pdf_path": None,
            },
            {
                "order_id": "A-2",
                "order_date": "2026-01-03",
                "status": "error",
                "receipt_url": "https://example.invalid/receipt/A-2",
                "pdf_path": "",
            },
            {
                "order_id": "A-3",
                "order_date": "2026-01-03",
                "status": "ok",
                "detail_url": "https://example.invalid/detail/A-3",
                "pdf_path": str(existing_pdf),
            },
            {
                "order_id": "A-4",
                "order_date": "2026-01-03",
                "status": "out_of_month",
                "detail_url": "https://example.invalid/detail/A-4",
                "pdf_path": None,
            },
            {
                "order_id": "A-5",
                "order_date": "2026-01-03",
                "status": "ok",
                "detail_url": "https://example.invalid/detail/A-5",
                "include": False,
            },
        ],
    )

    pending = _collect_missing_shortcut_orders(
        orders_jsonl=orders_jsonl,
        year=2026,
        month=1,
        source="amazon",
        exclusions={("amazon", "A-2")},
    )

    assert len(pending) == 1
    assert pending[0]["order_id"] == "A-1"


def test_collect_orders_pdfs_includes_documents_list_paths(tmp_path: Path) -> None:
    orders_jsonl = tmp_path / "amazon" / "orders.jsonl"
    summary_pdf = tmp_path / "amazon" / "pdfs" / "2026-01-03_amazon_A-10_summary.pdf"
    invoice_pdf = tmp_path / "amazon" / "pdfs" / "2026-01-03_amazon_A-10_invoice.pdf"
    summary_pdf.parent.mkdir(parents=True, exist_ok=True)
    summary_pdf.write_bytes(b"%PDF-1.4\n")
    invoice_pdf.write_bytes(b"%PDF-1.4\n")

    _write_jsonl(
        orders_jsonl,
        [
            {
                "order_id": "A-10",
                "order_date": "2026-01-03",
                "status": "ok",
                "pdf_path": str(summary_pdf),
                "documents": [
                    {"doc_type": "order_summary", "pdf_path": str(summary_pdf)},
                    {"doc_type": "tax_invoice", "pdf_path": str(invoice_pdf)},
                ],
            }
        ],
    )

    files = _collect_orders_pdfs(
        orders_jsonl=orders_jsonl,
        year=2026,
        month=1,
        source="amazon",
        exclusions=set(),
    )
    paths = {entry["path"] for entry in files}
    assert str(summary_pdf) in paths
    assert str(invoice_pdf) in paths


def test_resolve_orders_url_prefers_tenant_then_legacy() -> None:
    config = {
        "tenant": {"urls": {"amazon_orders": "https://tenant.example/amazon"}},
        "urls": {"amazon_orders": "https://legacy.example/amazon"},
    }
    assert _resolve_orders_url(config, "amazon") == "https://tenant.example/amazon"

    config = {"urls": {"rakuten_orders": "https://legacy.example/rakuten"}}
    assert _resolve_orders_url(config, "rakuten") == "https://legacy.example/rakuten"


def test_resolve_receipt_env_uses_tenant_receipt_values() -> None:
    env = _resolve_receipt_env(
        {
            "tenant": {"receipt": {"name": "Tenant Name", "name_fallback": "Tenant Fallback"}},
            "receipt_name": "Legacy Name",
            "receipt_name_fallback": "Legacy Fallback",
        }
    )
    assert env["RECEIPT_NAME"] == "Tenant Name"
    assert env["RECEIPT_NAME_FALLBACK"] == "Tenant Fallback"

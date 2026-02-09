from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import manual_receipt_import as manual_import


def _write_pdf(path: Path, content: bytes = b"%PDF-1.4\n%test\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_import_manual_receipts_moves_and_records_orders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output_root = tmp_path / "out"
    inbox_pdf = output_root / "manual" / "inbox" / "sample.pdf"
    _write_pdf(inbox_pdf)

    monkeypatch.setattr(
        manual_import,
        "_parse_receipt",
        lambda path: manual_import.ParsedReceipt(
            source="manual",
            order_id="MANUAL-ORDER-001",
            order_date=date(2026, 1, 29),
            total_yen=1599,
            item_name="テスト商品",
        ),
    )

    result = manual_import.import_manual_receipts_for_month(output_root, 2026, 1)

    assert result["status"] == "ok"
    assert result["found_pdfs"] == 1
    assert result["imported"] == 1
    assert result["failed"] == 0

    orders_path = Path(str(result["orders_jsonl"]))
    assert orders_path.exists()
    rows = [json.loads(line) for line in orders_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "manual"
    assert row["order_id"] == "MANUAL-ORDER-001"
    assert row["order_date"] == "2026-01-29"
    assert row["total_yen"] == 1599
    pdf_path = Path(str(row["pdf_path"]))
    assert pdf_path.exists()
    assert pdf_path.name.startswith("2026-01-29_manual_1599_")

    remaining = list((output_root / "manual" / "inbox").glob("*.pdf"))
    assert not remaining


def test_import_manual_receipts_skips_duplicate_doc_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output_root = tmp_path / "out"
    inbox_pdf = output_root / "manual" / "inbox" / "dup.pdf"
    _write_pdf(inbox_pdf, b"%PDF-1.4\n%duplicate\n")
    digest = manual_import._file_sha1(inbox_pdf)

    orders_path = output_root / "manual" / "orders.jsonl"
    orders_path.parent.mkdir(parents=True, exist_ok=True)
    orders_path.write_text(
        json.dumps(
            {
                "source": "manual",
                "order_id": "MANUAL-EXISTING",
                "order_date": "2026-01-10",
                "total_yen": 1200,
                "pdf_path": str(output_root / "manual" / "pdfs" / "existing.pdf"),
                "doc_hash": digest,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        manual_import,
        "_parse_receipt",
        lambda path: manual_import.ParsedReceipt(
            source="manual",
            order_id="MANUAL-NEW",
            order_date=date(2026, 1, 20),
            total_yen=2000,
            item_name="重複テスト",
        ),
    )

    result = manual_import.import_manual_receipts_for_month(output_root, 2026, 1)
    assert result["found_pdfs"] == 1
    assert result["imported"] == 0
    assert result["skipped_duplicates"] == 1
    assert result["failed"] == 0

    rows = [json.loads(line) for line in orders_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1

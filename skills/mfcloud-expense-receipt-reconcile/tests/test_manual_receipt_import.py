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


def test_import_manual_receipts_provider_folder_adds_provider_metadata(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    inbox_file = output_root / "manual" / "inbox" / "chatgpt" / "2026-01-28_invoice.png"
    _write_pdf(inbox_file, b"PNG")

    result = manual_import.import_manual_receipts_for_month(
        output_root,
        2026,
        1,
        provider_filter={"chatgpt"},
        ingestion_channel="provider_inbox",
    )

    assert result["status"] == "ok"
    assert result["found_files"] == 1
    assert result["imported"] == 1
    provider_counts = result.get("provider_counts") or {}
    chatgpt = provider_counts.get("chatgpt") or {}
    assert chatgpt.get("found") == 1
    assert chatgpt.get("imported") == 1

    orders_path = Path(str(result["orders_jsonl"]))
    rows = [json.loads(line) for line in orders_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "manual"
    assert row["provider"] == "chatgpt"
    assert row["doc_type"] == "provider_upload"
    assert row["ingestion_channel"] == "provider_inbox"
    assert row["source_hint"] == "manual"
    assert row["pdf_path"].endswith(".png")

    provider_report = Path(str(result.get("provider_report_json") or ""))
    assert provider_report.exists()


def test_import_provider_inbox_refreshes_duplicate_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output_root = tmp_path / "out"
    inbox_pdf = output_root / "manual" / "inbox" / "chatgpt" / "dup.pdf"
    _write_pdf(inbox_pdf, b"%PDF-1.4\n%duplicate\n")
    digest = manual_import._file_sha1(inbox_pdf)

    existing_pdf = output_root / "manual" / "pdfs" / "existing.pdf"
    _write_pdf(existing_pdf, b"%PDF-1.4\n%existing\n")

    orders_path = output_root / "manual" / "orders.jsonl"
    orders_path.parent.mkdir(parents=True, exist_ok=True)
    orders_path.write_text(
        json.dumps(
            {
                "source": "manual",
                "provider": "chatgpt",
                "source_hint": "manual",
                "ingestion_channel": "provider_inbox",
                "order_id": "MANUAL-OLD",
                "order_date": "2026-01-20",
                "total_yen": 2610013,
                "order_total_yen": 2610013,
                "pdf_path": str(existing_pdf),
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
            order_id="MANUAL-REFRESHED",
            order_date=date(2026, 1, 18),
            total_yen=None,
            item_name="ChatGPT Pro Subscription",
        ),
    )

    result = manual_import.import_manual_receipts_for_month(
        output_root,
        2026,
        1,
        provider_filter={"chatgpt"},
        ingestion_channel="provider_inbox",
    )
    assert result["found_files"] == 1
    assert result["imported"] == 1
    assert result["updated_duplicates"] == 1
    assert result["skipped_duplicates"] == 0

    rows = [json.loads(line) for line in orders_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["order_id"] == "MANUAL-REFRESHED"
    assert row["order_date"] == "2026-01-18"
    assert row["total_yen"] is None
    assert row["provider"] == "chatgpt"
    assert row.get("metadata_refreshed_at")
    assert row["pdf_path"] == str(existing_pdf)


def test_extract_total_yen_returns_none_for_foreign_currency_text() -> None:
    text = "Total $220.00 paid on January 18, 2026"
    assert manual_import._extract_total_yen(text) is None


def test_extract_total_yen_ignores_unreasonable_large_noise_numbers() -> None:
    text = "合計 19,917円 / REF 17020001010196"
    assert manual_import._extract_total_yen(text) == 19917


def test_extract_total_yen_repairs_common_ocr_comma_tail_noise() -> None:
    text = "消費税対象 19,9179"
    assert manual_import._extract_total_yen(text) == 19917


def test_extract_total_yen_prefers_repeated_total_over_single_noise_peak() -> None:
    text = "Subtotal 19,917\nTotal 19,917\nRef 91,779"
    assert manual_import._extract_total_yen(text) == 19917


def test_extract_date_from_english_text() -> None:
    text = "Date paid January 18, 2026\nDate due Feb 18, 2026"
    assert manual_import._extract_date_from_text(text) == date(2026, 1, 18)


def test_extract_date_from_numeric_unambiguous_day_first_text() -> None:
    text = "Receipt issued 16/01/2026 7:28 PM"
    assert manual_import._extract_date_from_text(text) == date(2026, 1, 16)


def test_extract_date_from_compact_ymd_text() -> None:
    text = "No 20260105-38"
    assert manual_import._extract_date_from_text(text) == date(2026, 1, 5)


def test_parse_receipt_uses_ocr_fallback_when_pdf_text_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    _write_pdf(pdf_path)

    monkeypatch.setattr(manual_import, "_read_pdf_text", lambda path: "")
    monkeypatch.setattr(manual_import, "_ocr_enabled", lambda: True)
    monkeypatch.setattr(
        manual_import,
        "_read_pdf_text_via_ocr",
        lambda path: "Date paid January 16, 2026\nTotal 25,243\nStore Azabudai Hills",
    )

    parsed = manual_import._parse_receipt(pdf_path)
    assert parsed.order_date == date(2026, 1, 16)
    assert parsed.total_yen == 25243
    assert parsed.source == "manual"

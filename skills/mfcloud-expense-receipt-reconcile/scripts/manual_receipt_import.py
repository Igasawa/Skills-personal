#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any
import unicodedata

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from common import artifact_root as _artifact_root  # noqa: E402
from common import read_jsonl as _read_jsonl  # noqa: E402

DATE_RE = re.compile(r"(20\d{2})\s*[./\-年]\s*(\d{1,2})\s*[./\-月]\s*(\d{1,2})")
EN_DATE_MONTH_FIRST_RE = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s*(20\d{2})\b")
EN_DATE_DAY_FIRST_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})\b")
NUMERIC_DATE_YMD_COMPACT_RE = re.compile(r"\b(20\d{2})(\d{2})(\d{2})\b")
NUMERIC_DATE_DMY_OR_MDY_RE = re.compile(r"\b(\d{1,2})\s*[./\-]\s*(\d{1,2})\s*[./\-]\s*(20\d{2})\b")
AMAZON_ORDER_ID_RE = re.compile(r"\b\d{3}-\d{7}-\d{7}\b")
RAKUTEN_ORDER_ID_RE = re.compile(r"\b\d{6}-\d{8}-\d{10}\b")

PROVIDER_KEYS: tuple[str, ...] = ("aquavoice", "claude", "chatgpt", "gamma")
ALLOWED_RECEIPT_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}

AMOUNT_LABELS: list[str] = [
    "ご請求額",
    "請求額",
    "注文合計",
    "合計金額",
    "支払額",
    "お支払い金額",
    "総合計",
    "合計",
    "金額",
    "amount due",
    "total",
]

ITEM_NOISE_TOKENS = (
    "領収書",
    "請求書",
    "お届け先",
    "お支払い方法",
    "注文概要",
    "注文日",
    "注文 #",
    "注文番号",
    "ご請求額",
    "注文合計",
    "商品の小計",
    "配送料",
    "手数料",
    "支払方法",
    "〒",
)

EN_MONTH_TO_NUM: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

FOREIGN_CURRENCY_RE = re.compile(
    r"\b(?:USD|EUR|GBP|AUD|CAD|CHF|CNY|HKD|SGD|NTD|KRW|INR|THB|VND|MYR|PHP)\b|(?:[$€£]\s*[0-9])",
    re.IGNORECASE,
)
YEN_MARKER_RE = re.compile(r"(?:[¥￥]|円|\bJPY\b)", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedReceipt:
    source: str
    order_id: str | None
    order_date: date | None
    total_yen: int | None
    item_name: str | None


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = normalized.replace("\u3000", " ")
    normalized = normalized.replace("\r", "\n")
    normalized = re.sub(r"\n+", "\n", normalized)
    return normalized


def _safe_token(value: str, *, fallback: str, max_len: int = 40) -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or ""))
    text = re.sub(r"_+", "_", text).strip("_.-")
    if not text:
        text = fallback
    return text[:max_len]


def _read_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency should exist in runtime
        raise RuntimeError("pypdf is required for manual receipt import.") from exc

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages[:3]:
        parts.append(page.extract_text() or "")
    return _normalize_text("\n".join(parts))


def _text_non_space_len(text: str) -> int:
    return len(re.sub(r"\s+", "", str(text or "")))


def _ocr_enabled() -> bool:
    raw = str(os.environ.get("AX_MANUAL_RECEIPT_OCR", "1") or "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _ocr_lang() -> str:
    raw = str(os.environ.get("AX_MANUAL_RECEIPT_OCR_LANG", "") or "").strip()
    return raw or "jpn+eng"


def _resolve_tesseract_cmd() -> str | None:
    override = str(os.environ.get("AX_MANUAL_RECEIPT_TESSERACT_CMD", "") or "").strip()
    if override and Path(override).exists():
        return override
    cmd = shutil.which("tesseract")
    if cmd:
        return cmd
    candidates = [
        Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
        Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _extract_pdf_image_blobs(path: Path, *, max_pages: int = 3, max_images_per_page: int = 4) -> list[bytes]:
    # pypdf image extraction requires Pillow; when unavailable, skip OCR gracefully.
    try:
        from PIL import Image  # type: ignore  # noqa: F401
    except Exception:
        return []

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return []

    try:
        reader = PdfReader(str(path))
    except Exception:
        return []

    blobs: list[bytes] = []
    for page in list(reader.pages)[: max(1, int(max_pages))]:
        page_images = getattr(page, "images", None)
        if not page_images:
            continue

        taken = 0
        try:
            image_iter = iter(page_images)
        except Exception:
            continue

        for image in image_iter:
            if taken >= max(1, int(max_images_per_page)):
                break
            data = getattr(image, "data", b"")
            try:
                blob = bytes(data or b"")
            except Exception:
                blob = b""
            if not blob:
                continue
            blobs.append(blob)
            taken += 1

    return blobs


def _ocr_text_from_image_blobs(blobs: list[bytes]) -> str:
    if not blobs:
        return ""
    if not _ocr_enabled():
        return ""

    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
    except Exception:
        return ""

    tesseract_cmd = _resolve_tesseract_cmd()
    if not tesseract_cmd:
        return ""
    try:
        pytesseract.pytesseract.tesseract_cmd = str(tesseract_cmd)
    except Exception:
        return ""

    lang = _ocr_lang()
    parts: list[str] = []
    for blob in blobs:
        try:
            with Image.open(io.BytesIO(blob)) as img:
                target = img
                if img.mode not in {"L", "RGB"}:
                    target = img.convert("RGB")
                text = pytesseract.image_to_string(target, lang=lang) or ""
        except Exception:
            continue
        cleaned = _normalize_text(text)
        if cleaned:
            parts.append(cleaned)

    return _normalize_text("\n".join(parts))


def _read_pdf_text_via_ocr(path: Path) -> str:
    blobs = _extract_pdf_image_blobs(path)
    return _ocr_text_from_image_blobs(blobs)


def _extract_date_from_text(text: str) -> date | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    date_keywords = ("注文日", "発行日", "領収日", "利用日", "日付", "date", "issued", "invoice date", "date paid")
    for line in lines[:80]:
        lower_line = line.lower()
        if not any(token in lower_line for token in date_keywords):
            continue
        m = DATE_RE.search(line)
        if not m:
            continue
        y, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, month, day)
        except ValueError:
            continue

    english_hits: list[tuple[int, date]] = []
    for m in EN_DATE_MONTH_FIRST_RE.finditer(text):
        month_token = str(m.group(1) or "").strip().lower().rstrip(".")
        month_num = EN_MONTH_TO_NUM.get(month_token)
        if not month_num:
            continue
        day = int(m.group(2))
        year = int(m.group(3))
        try:
            english_hits.append((m.start(), date(year, month_num, day)))
        except ValueError:
            continue
    for m in EN_DATE_DAY_FIRST_RE.finditer(text):
        day = int(m.group(1))
        month_token = str(m.group(2) or "").strip().lower().rstrip(".")
        month_num = EN_MONTH_TO_NUM.get(month_token)
        if not month_num:
            continue
        year = int(m.group(3))
        try:
            english_hits.append((m.start(), date(year, month_num, day)))
        except ValueError:
            continue
    if english_hits:
        english_hits.sort(key=lambda x: x[0])
        return english_hits[0][1]

    for m in NUMERIC_DATE_DMY_OR_MDY_RE.finditer(text):
        first = int(m.group(1))
        second = int(m.group(2))
        year = int(m.group(3))

        # Accept only unambiguous numeric dates to avoid swapping month/day incorrectly.
        if first > 12 and second <= 12:
            try:
                return date(year, second, first)
            except ValueError:
                continue
        if second > 12 and first <= 12:
            try:
                return date(year, first, second)
            except ValueError:
                continue

    for m in NUMERIC_DATE_YMD_COMPACT_RE.finditer(text):
        y, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, month, day)
        except ValueError:
            continue

    for m in DATE_RE.finditer(text):
        y, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, month, day)
        except ValueError:
            continue

    return None


def _extract_amount_after_label(text: str, label: str) -> int | None:
    pattern = re.compile(
        rf"{re.escape(label)}\s*[:：]?\s*(?:[¥￥$€£]|JPY|USD)?\s*([0-9][0-9,]*(?:\.[0-9]{{1,2}})?)",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "").strip()
    try:
        return int(round(float(raw)))
    except ValueError:
        return None


def _has_foreign_currency(text: str) -> bool:
    return bool(FOREIGN_CURRENCY_RE.search(text or ""))


def _has_yen_marker(text: str) -> bool:
    return bool(YEN_MARKER_RE.search(text or ""))


def _to_int_amount(raw: str) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None

    # OCR noise sometimes appends one digit (e.g. "19,9179"). If a trailing-digit
    # trim restores a valid comma-grouped integer, prefer the restored form.
    if "," in text and "." not in text:
        compact = re.sub(r"\s+", "", text)
        if not re.fullmatch(r"\d{1,3}(,\d{3})+", compact):
            restored = compact
            while restored and not re.fullmatch(r"\d{1,3}(,\d{3})+", restored):
                restored = restored[:-1]
            if re.fullmatch(r"\d{1,3}(,\d{3})+", restored):
                text = restored
            else:
                text = compact
        else:
            text = compact

    value = text.replace(",", "").strip()
    if not value:
        return None
    try:
        amount = int(round(float(value)))
    except ValueError:
        return None
    max_yen_raw = str(os.environ.get("AX_MANUAL_RECEIPT_MAX_YEN", "") or "").strip()
    try:
        max_yen = int(max_yen_raw) if max_yen_raw else 10_000_000
    except ValueError:
        max_yen = 10_000_000
    if amount <= 0 or amount > max_yen:
        return None
    return amount


def _extract_total_yen(text: str) -> int | None:
    has_foreign = _has_foreign_currency(text)
    # For foreign-currency receipts (e.g. USD invoices), do not coerce to JPY.
    # Any JPY-like token in such documents is often a tax/reference figure.
    if has_foreign:
        return None

    for label in AMOUNT_LABELS:
        hit = _extract_amount_after_label(text, label)
        if hit is not None:
            return hit

    yen_hits: list[int] = []
    for m in re.finditer(r"(?:[¥￥]|JPY)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", text, re.IGNORECASE):
        hit = _to_int_amount(m.group(1))
        if hit is not None:
            yen_hits.append(hit)
    for m in re.finditer(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:円|JPY)", text, re.IGNORECASE):
        hit = _to_int_amount(m.group(1))
        if hit is not None:
            yen_hits.append(hit)
    if yen_hits:
        return max(yen_hits)

    if has_foreign:
        return None

    loose_hits: list[int] = []
    for m in re.finditer(r"([0-9][0-9,\s]{2,}(?:\.[0-9]{1,2})?)", text):
        raw = re.sub(r"\s+", "", str(m.group(1) or ""))
        hit = _to_int_amount(raw)
        if hit is not None:
            loose_hits.append(hit)
    if loose_hits:
        freq: dict[int, int] = {}
        for value in loose_hits:
            freq[value] = int(freq.get(value, 0)) + 1
        repeated = [value for value, count in freq.items() if count >= 2]
        if repeated:
            return max(repeated)

    plain_hits: list[int] = []
    for m in re.finditer(r"\b([0-9][0-9,]{2,})\b", text):
        hit = _to_int_amount(m.group(1))
        if hit is not None:
            plain_hits.append(hit)
    return max(plain_hits) if plain_hits else None


def _extract_order_id(text: str) -> str | None:
    amazon_hit = AMAZON_ORDER_ID_RE.search(text)
    if amazon_hit:
        return amazon_hit.group(0)
    rakuten_hit = RAKUTEN_ORDER_ID_RE.search(text)
    if rakuten_hit:
        return rakuten_hit.group(0)
    generic = re.search(
        r"(?:注文(?:番号|#)?|order(?:\s*#|\s*number)?)\D{0,8}([0-9A-Za-z-]{6,40})",
        text,
        re.IGNORECASE,
    )
    if generic:
        return generic.group(1)
    return None


def _detect_source(text: str, order_id: str | None, file_name: str) -> str:
    t = text.lower()
    file_lower = str(file_name or "").lower()
    if "amazon" in t or "アマゾン" in text or AMAZON_ORDER_ID_RE.search(str(order_id or "")):
        return "amazon"
    if "rakuten" in t or "楽天" in text or RAKUTEN_ORDER_ID_RE.search(str(order_id or "")):
        return "rakuten"
    if "amazon" in file_lower:
        return "amazon"
    if "rakuten" in file_lower:
        return "rakuten"
    return "manual"


def _extract_item_name(text: str) -> str | None:
    for line in text.splitlines():
        candidate = re.sub(r"\s+", " ", line).strip()
        if not candidate:
            continue
        if len(candidate) < 3 or len(candidate) > 120:
            continue
        if any(token in candidate for token in ITEM_NOISE_TOKENS):
            continue
        if re.fullmatch(r"[0-9,./\-:()\s]+", candidate):
            continue
        return candidate
    return None


def _fallback_date_from_name(name: str) -> date | None:
    m = re.search(r"(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})", str(name or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _move_to_bucket(src: Path, bucket_root: Path, *, rel_to: Path | None = None) -> Path:
    rel_parent = Path(".")
    if rel_to is not None:
        try:
            rel_parent = src.resolve().relative_to(rel_to.resolve()).parent
        except Exception:
            rel_parent = Path(".")
    dest_dir = bucket_root / rel_parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(dest_dir / src.name)
    shutil.move(str(src), str(dest))
    return dest


def _load_existing_hashes(orders_jsonl: Path) -> set[str]:
    out: set[str] = set()
    for obj in _read_jsonl(orders_jsonl):
        if not isinstance(obj, dict):
            continue
        digest = str(obj.get("doc_hash") or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{40}", digest):
            out.add(digest)
    return out


def _append_orders(orders_jsonl: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    orders_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with orders_jsonl.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _replace_order_by_hash(
    orders_jsonl: Path,
    *,
    doc_hash: str,
    updates: dict[str, Any],
    now_iso: str,
) -> tuple[bool, dict[str, Any] | None]:
    rows = _read_jsonl(orders_jsonl, required=False, strict=False)
    if not rows:
        return False, None
    digest = str(doc_hash or "").strip().lower()
    if not digest:
        return False, None

    replaced = False
    merged_row: dict[str, Any] | None = None
    out_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not replaced and str(row.get("doc_hash") or "").strip().lower() == digest:
            merged = dict(row)
            first_imported_at = merged.get("first_imported_at") or merged.get("imported_at")
            merged.update(updates)
            merged["doc_hash"] = digest
            merged["imported_at"] = now_iso
            if first_imported_at:
                merged["first_imported_at"] = first_imported_at
            merged["metadata_refreshed_at"] = now_iso
            out_rows.append(merged)
            merged_row = merged
            replaced = True
            continue
        out_rows.append(row)

    if not replaced:
        return False, None

    orders_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with orders_jsonl.open("w", encoding="utf-8") as handle:
        for row in out_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True, merged_row


def _parse_receipt(path: Path) -> ParsedReceipt:
    text = _read_pdf_text(path)
    order_id = _extract_order_id(text)
    order_date = _extract_date_from_text(text)
    total_yen = _extract_total_yen(text)
    item_name = _extract_item_name(text)

    # OCR fallback for image-only PDFs or malformed embedded text.
    if _ocr_enabled() and (_text_non_space_len(text) < 24 or (order_date is None and total_yen is None)):
        ocr_text = _read_pdf_text_via_ocr(path)
        if _text_non_space_len(ocr_text) > 0:
            text = _normalize_text("\n".join(part for part in [text, ocr_text] if str(part or "").strip()))
            order_id = _extract_order_id(text)
            order_date = _extract_date_from_text(text)
            total_yen = _extract_total_yen(text)
            item_name = _extract_item_name(text)

    source = _detect_source(text, order_id, path.name)
    return ParsedReceipt(
        source=source,
        order_id=order_id,
        order_date=order_date,
        total_yen=total_yen,
        item_name=item_name,
    )


def _parse_receipt_file(path: Path) -> ParsedReceipt:
    if path.suffix.lower() == ".pdf":
        return _parse_receipt(path)
    order_id = _extract_order_id(path.stem)
    source = _detect_source("", order_id, path.name)
    return ParsedReceipt(
        source=source,
        order_id=order_id,
        order_date=None,
        total_yen=None,
        item_name=None,
    )


def _provider_from_relative_path(rel_path: Path) -> str:
    if not rel_path.parts:
        return "manual"
    first = str(rel_path.parts[0] or "").strip().lower()
    if first in PROVIDER_KEYS:
        return first
    return "manual"


def _normalize_provider_filter(provider_filter: set[str] | list[str] | tuple[str, ...] | None) -> set[str] | None:
    if provider_filter is None:
        return None
    normalized: set[str] = set()
    for provider in provider_filter:
        name = str(provider or "").strip().lower()
        if not name:
            continue
        if name in PROVIDER_KEYS or name == "manual":
            normalized.add(name)
    return normalized or set()


def _iter_receipt_files(inbox_dir: Path, provider_filter: set[str] | None = None) -> list[Path]:
    if not inbox_dir.exists():
        return []
    out: list[Path] = []
    for path in sorted(inbox_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_RECEIPT_SUFFIXES:
            continue
        rel = path.relative_to(inbox_dir)
        if any(part.startswith("_") for part in rel.parts):
            continue
        provider = _provider_from_relative_path(rel)
        if provider_filter is not None and provider not in provider_filter:
            continue
        out.append(path)
    return out


def _new_provider_stat() -> dict[str, int]:
    return {
        "found": 0,
        "imported": 0,
        "imported_missing_amount": 0,
        "updated_duplicates": 0,
        "skipped_duplicates": 0,
        "failed": 0,
    }


def import_manual_receipts_for_month(
    output_root: Path,
    year: int,
    month: int,
    *,
    provider_filter: set[str] | list[str] | tuple[str, ...] | None = None,
    ingestion_channel: str = "manual_inbox",
) -> dict[str, Any]:
    ym = f"{year:04d}-{month:02d}"
    output_root = output_root.resolve()
    manual_root = output_root / "manual"
    inbox_dir = manual_root / "inbox"
    pdfs_dir = manual_root / "pdfs"
    orders_jsonl = manual_root / "orders.jsonl"
    reports_dir = manual_root / "reports"
    errors_jsonl = reports_dir / "manual_import_errors.jsonl"
    report_json = reports_dir / "manual_import_last.json"
    provider_report_json = reports_dir / "provider_import_last.json"

    inbox_dir.mkdir(parents=True, exist_ok=True)
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    processed_dir = inbox_dir / "_processed" / run_stamp
    skipped_dir = inbox_dir / "_skipped" / run_stamp
    failed_dir = inbox_dir / "_failed" / run_stamp

    normalized_provider_filter = _normalize_provider_filter(provider_filter)
    receipt_files = _iter_receipt_files(inbox_dir, provider_filter=normalized_provider_filter)
    existing_hashes = _load_existing_hashes(orders_jsonl)
    now_iso = datetime.now().isoformat(timespec="seconds")

    imported_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    new_orders: list[dict[str, Any]] = []
    imported = 0
    updated_duplicates = 0
    skipped_duplicates = 0
    failed = 0
    missing_amount = 0

    provider_counts: dict[str, dict[str, int]] = {provider: _new_provider_stat() for provider in PROVIDER_KEYS}
    provider_counts["manual"] = _new_provider_stat()

    for src in receipt_files:
        rel = src.relative_to(inbox_dir)
        provider = _provider_from_relative_path(rel)
        provider_stat = provider_counts.setdefault(provider, _new_provider_stat())
        provider_stat["found"] += 1

        try:
            digest = _file_sha1(src)
        except Exception as exc:
            failed += 1
            provider_stat["failed"] += 1
            moved = _move_to_bucket(src, failed_dir, rel_to=inbox_dir)
            failed_rows.append(
                {
                    "file": src.name,
                    "relative_path": str(rel).replace("\\", "/"),
                    "provider": provider,
                    "moved_to": str(moved),
                    "reason": f"hash_error: {exc}",
                }
            )
            continue

        if digest in existing_hashes:
            if str(ingestion_channel or "").strip().lower() == "provider_inbox":
                try:
                    parsed = _parse_receipt_file(src)
                    fallback_date = _fallback_date_from_name(src.name)
                    mtime_date = date.fromtimestamp(src.stat().st_mtime)
                    order_date = parsed.order_date or fallback_date or mtime_date
                    source = parsed.source if parsed.source in {"amazon", "rakuten", "manual"} else "manual"
                    total_yen = parsed.total_yen
                    if total_yen is None:
                        missing_amount += 1
                        provider_stat["imported_missing_amount"] += 1
                    order_id = parsed.order_id or f"MANUAL-{digest[:12].upper()}"
                    provider_doc_id = parsed.order_id if provider in PROVIDER_KEYS and parsed.order_id else None
                    provider_value: str | None = provider if provider in PROVIDER_KEYS else None
                    updates: dict[str, Any] = {
                        "source": "manual",
                        "provider": provider_value,
                        "source_hint": source,
                        "ingestion_channel": str(ingestion_channel or "manual_inbox"),
                        "provider_doc_id": provider_doc_id,
                        "provider_invoice_url": None,
                        "order_id": order_id,
                        "order_date": order_date.isoformat(),
                        "total_yen": total_yen,
                        "order_total_yen": total_yen,
                        "item_name": parsed.item_name,
                        "status": "ok",
                        "doc_type": "provider_upload" if provider_value else "manual_upload",
                        "detail_url": None,
                        "receipt_url": None,
                        "include": True,
                        "import_source_name": src.name,
                        "import_source_relpath": str(rel).replace("\\", "/"),
                    }
                    replaced, merged = _replace_order_by_hash(
                        orders_jsonl,
                        doc_hash=digest,
                        updates=updates,
                        now_iso=now_iso,
                    )
                    if replaced:
                        imported += 1
                        updated_duplicates += 1
                        provider_stat["imported"] += 1
                        provider_stat["updated_duplicates"] += 1
                        moved = _move_to_bucket(src, processed_dir, rel_to=inbox_dir)
                        imported_rows.append(
                            {
                                "file": src.name,
                                "relative_path": str(rel).replace("\\", "/"),
                                "provider": provider,
                                "moved_to": str(moved),
                                "pdf_path": str((merged or {}).get("pdf_path") or ""),
                                "source": source,
                                "order_id": order_id,
                                "order_date": order_date.isoformat(),
                                "total_yen": total_yen,
                                "doc_hash": digest,
                                "updated_duplicate": True,
                            }
                        )
                        continue
                except Exception:
                    # Fall back to duplicate-skip behavior below.
                    pass

            skipped_duplicates += 1
            provider_stat["skipped_duplicates"] += 1
            moved = _move_to_bucket(src, skipped_dir, rel_to=inbox_dir)
            skipped_rows.append(
                {
                    "file": src.name,
                    "relative_path": str(rel).replace("\\", "/"),
                    "provider": provider,
                    "moved_to": str(moved),
                    "reason": "duplicate_doc_hash",
                    "doc_hash": digest,
                }
            )
            continue

        try:
            parsed = _parse_receipt_file(src)
            fallback_date = _fallback_date_from_name(src.name)
            mtime_date = date.fromtimestamp(src.stat().st_mtime)
            order_date = parsed.order_date or fallback_date or mtime_date
            source = parsed.source if parsed.source in {"amazon", "rakuten", "manual"} else "manual"
            total_yen = parsed.total_yen
            if total_yen is None:
                missing_amount += 1
                provider_stat["imported_missing_amount"] += 1

            order_id = parsed.order_id or f"MANUAL-{digest[:12].upper()}"
            amount_token = str(total_yen) if total_yen is not None else "unknown"
            order_token = _safe_token(order_id, fallback=digest[:8], max_len=32)
            suffix = src.suffix.lower() if src.suffix else ".pdf"
            if provider == "manual":
                file_name = f"{order_date.isoformat()}_{source}_{amount_token}_{order_token}{suffix}"
            else:
                file_name = f"{order_date.isoformat()}_{provider}_{source}_{amount_token}_{order_token}{suffix}"
            dest_file = _unique_path(pdfs_dir / file_name)
            shutil.copy2(src, dest_file)
            moved = _move_to_bucket(src, processed_dir, rel_to=inbox_dir)

            provider_doc_id = parsed.order_id if provider in PROVIDER_KEYS and parsed.order_id else None
            provider_value: str | None = provider if provider in PROVIDER_KEYS else None
            order_obj: dict[str, Any] = {
                "source": "manual",
                "provider": provider_value,
                "source_hint": source,
                "ingestion_channel": str(ingestion_channel or "manual_inbox"),
                "provider_doc_id": provider_doc_id,
                "provider_invoice_url": None,
                "order_id": order_id,
                "order_date": order_date.isoformat(),
                "total_yen": total_yen,
                "order_total_yen": total_yen,
                "item_name": parsed.item_name,
                "status": "ok",
                "doc_type": "provider_upload" if provider_value else "manual_upload",
                "pdf_path": str(dest_file),
                "detail_url": None,
                "receipt_url": None,
                "include": True,
                "imported_at": now_iso,
                "import_source_name": src.name,
                "import_source_relpath": str(rel).replace("\\", "/"),
                "doc_hash": digest,
            }
            new_orders.append(order_obj)
            existing_hashes.add(digest)
            imported += 1
            provider_stat["imported"] += 1
            imported_rows.append(
                {
                    "file": src.name,
                    "relative_path": str(rel).replace("\\", "/"),
                    "provider": provider,
                    "moved_to": str(moved),
                    "pdf_path": str(dest_file),
                    "source": source,
                    "order_id": order_id,
                    "order_date": order_date.isoformat(),
                    "total_yen": total_yen,
                    "doc_hash": digest,
                }
            )
        except Exception as exc:
            failed += 1
            provider_stat["failed"] += 1
            moved = _move_to_bucket(src, failed_dir, rel_to=inbox_dir)
            failed_rows.append(
                {
                    "file": src.name,
                    "relative_path": str(rel).replace("\\", "/"),
                    "provider": provider,
                    "moved_to": str(moved),
                    "reason": str(exc),
                    "doc_hash": digest,
                }
            )

    _append_orders(orders_jsonl, new_orders)
    _append_jsonl(errors_jsonl, failed_rows)

    payload = {
        "status": "ok",
        "ym": ym,
        "ingestion_channel": str(ingestion_channel or "manual_inbox"),
        "provider_filter": sorted(normalized_provider_filter) if normalized_provider_filter is not None else [],
        "found_files": len(receipt_files),
        "found_pdfs": len(receipt_files),
        "imported": imported,
        "updated_duplicates": updated_duplicates,
        "imported_missing_amount": missing_amount,
        "skipped_duplicates": skipped_duplicates,
        "failed": failed,
        "provider_counts": provider_counts,
        "output_root": str(output_root),
        "inbox_dir": str(inbox_dir),
        "pdfs_dir": str(pdfs_dir),
        "orders_jsonl": str(orders_jsonl),
        "errors_jsonl": str(errors_jsonl),
        "report_json": str(report_json),
        "provider_report_json": str(provider_report_json),
        "imported_rows": imported_rows,
        "skipped_rows": skipped_rows,
        "failed_rows": failed_rows,
        "processed_dir": str(processed_dir) if imported_rows else "",
    }
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    provider_report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _default_output_root(year: int, month: int) -> Path:
    return _artifact_root() / f"{year:04d}-{month:02d}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import manually uploaded receipt files into manual/orders.jsonl")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--output-root", help="Path to artifacts root for target month")
    args = ap.parse_args(argv)

    year = int(args.year)
    month = int(args.month)
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12.")

    output_root = Path(args.output_root).expanduser() if args.output_root else _default_output_root(year, month)
    result = import_manual_receipts_for_month(output_root, year, month)
    print(json.dumps({"status": "success", "data": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

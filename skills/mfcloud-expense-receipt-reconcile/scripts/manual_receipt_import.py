#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
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

DATE_RE = re.compile(r"(20\d{2})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})")
AMAZON_ORDER_ID_RE = re.compile(r"\b\d{3}-\d{7}-\d{7}\b")
RAKUTEN_ORDER_ID_RE = re.compile(r"\b\d{6}-\d{8}-\d{10}\b")

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


def _extract_date_from_text(text: str) -> date | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    date_keywords = ("注文日", "発行日", "領収日", "利用日", "日付")
    for line in lines[:80]:
        if not any(token in line for token in date_keywords):
            continue
        m = DATE_RE.search(line)
        if not m:
            continue
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
    pattern = re.compile(rf"{re.escape(label)}\s*[:：]?\s*[¥￥]?\s*([0-9][0-9,]*)", re.IGNORECASE)
    m = pattern.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def _extract_total_yen(text: str) -> int | None:
    for label in AMOUNT_LABELS:
        hit = _extract_amount_after_label(text, label)
        if hit is not None:
            return hit

    yen_hits: list[int] = []
    for m in re.finditer(r"[¥￥]\s*([0-9][0-9,]*)", text):
        raw = m.group(1).replace(",", "")
        try:
            yen_hits.append(int(raw))
        except ValueError:
            continue
    if yen_hits:
        return max(yen_hits)

    plain_hits: list[int] = []
    for m in re.finditer(r"\b([0-9][0-9,]{2,})\b", text):
        raw = m.group(1).replace(",", "")
        try:
            plain_hits.append(int(raw))
        except ValueError:
            continue
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


def _move_to_bucket(src: Path, bucket_dir: Path) -> Path:
    bucket_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(bucket_dir / src.name)
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


def _parse_receipt(path: Path) -> ParsedReceipt:
    text = _read_pdf_text(path)
    order_id = _extract_order_id(text)
    order_date = _extract_date_from_text(text)
    total_yen = _extract_total_yen(text)
    source = _detect_source(text, order_id, path.name)
    item_name = _extract_item_name(text)
    return ParsedReceipt(
        source=source,
        order_id=order_id,
        order_date=order_date,
        total_yen=total_yen,
        item_name=item_name,
    )


def import_manual_receipts_for_month(output_root: Path, year: int, month: int) -> dict[str, Any]:
    ym = f"{year:04d}-{month:02d}"
    output_root = output_root.resolve()
    manual_root = output_root / "manual"
    inbox_dir = manual_root / "inbox"
    pdfs_dir = manual_root / "pdfs"
    orders_jsonl = manual_root / "orders.jsonl"
    reports_dir = manual_root / "reports"
    errors_jsonl = reports_dir / "manual_import_errors.jsonl"
    report_json = reports_dir / "manual_import_last.json"

    inbox_dir.mkdir(parents=True, exist_ok=True)
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    processed_dir = inbox_dir / "_processed" / run_stamp
    skipped_dir = inbox_dir / "_skipped" / run_stamp
    failed_dir = inbox_dir / "_failed" / run_stamp

    pdf_files = sorted(p for p in inbox_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    existing_hashes = _load_existing_hashes(orders_jsonl)
    now_iso = datetime.now().isoformat(timespec="seconds")

    imported_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    new_orders: list[dict[str, Any]] = []
    imported = 0
    skipped_duplicates = 0
    failed = 0
    missing_amount = 0

    for src in pdf_files:
        try:
            digest = _file_sha1(src)
        except Exception as exc:
            failed += 1
            moved = _move_to_bucket(src, failed_dir)
            failed_rows.append(
                {
                    "file": src.name,
                    "moved_to": str(moved),
                    "reason": f"hash_error: {exc}",
                }
            )
            continue

        if digest in existing_hashes:
            skipped_duplicates += 1
            moved = _move_to_bucket(src, skipped_dir)
            skipped_rows.append(
                {
                    "file": src.name,
                    "moved_to": str(moved),
                    "reason": "duplicate_doc_hash",
                    "doc_hash": digest,
                }
            )
            continue

        try:
            parsed = _parse_receipt(src)
            fallback_date = _fallback_date_from_name(src.name)
            mtime_date = date.fromtimestamp(src.stat().st_mtime)
            order_date = parsed.order_date or fallback_date or mtime_date
            source = parsed.source if parsed.source in {"amazon", "rakuten", "manual"} else "manual"
            total_yen = parsed.total_yen
            if total_yen is None:
                missing_amount += 1

            order_id = parsed.order_id or f"MANUAL-{digest[:12].upper()}"
            amount_token = str(total_yen) if total_yen is not None else "unknown"
            order_token = _safe_token(order_id, fallback=digest[:8], max_len=32)
            file_name = f"{order_date.isoformat()}_{source}_{amount_token}_{order_token}.pdf"
            dest_pdf = _unique_path(pdfs_dir / file_name)
            shutil.copy2(src, dest_pdf)
            moved = _move_to_bucket(src, processed_dir)

            order_obj: dict[str, Any] = {
                "source": "manual",
                "order_id": order_id,
                "order_date": order_date.isoformat(),
                "total_yen": total_yen,
                "order_total_yen": total_yen,
                "item_name": parsed.item_name,
                "status": "ok",
                "doc_type": "manual_upload",
                "pdf_path": str(dest_pdf),
                "detail_url": None,
                "receipt_url": None,
                "include": True,
                "imported_at": now_iso,
                "import_source_name": src.name,
                "doc_hash": digest,
            }
            new_orders.append(order_obj)
            existing_hashes.add(digest)
            imported += 1
            imported_rows.append(
                {
                    "file": src.name,
                    "moved_to": str(moved),
                    "pdf_path": str(dest_pdf),
                    "source": source,
                    "order_id": order_id,
                    "order_date": order_date.isoformat(),
                    "total_yen": total_yen,
                    "doc_hash": digest,
                }
            )
        except Exception as exc:
            failed += 1
            moved = _move_to_bucket(src, failed_dir)
            failed_rows.append(
                {
                    "file": src.name,
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
        "found_pdfs": len(pdf_files),
        "imported": imported,
        "imported_missing_amount": missing_amount,
        "skipped_duplicates": skipped_duplicates,
        "failed": failed,
        "output_root": str(output_root),
        "inbox_dir": str(inbox_dir),
        "pdfs_dir": str(pdfs_dir),
        "orders_jsonl": str(orders_jsonl),
        "errors_jsonl": str(errors_jsonl),
        "report_json": str(report_json),
        "imported_rows": imported_rows,
        "skipped_rows": skipped_rows,
        "failed_rows": failed_rows,
        "processed_dir": str(processed_dir) if imported_rows else "",
    }
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _default_output_root(year: int, month: int) -> Path:
    return _artifact_root() / f"{year:04d}-{month:02d}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import manually uploaded receipt PDFs into manual/orders.jsonl")
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

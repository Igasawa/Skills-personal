from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .core_shared import (
    ORDER_ID_RE,
    _read_json,
    _read_jsonl,
    _write_json,
)

STATUS_LABELS = {
    "ok": "取得済み",
    "no_receipt": "領収書なし",
    "out_of_month": "対象外",
    "unknown_date": "日付不明",
    "error": "エラー",
    "gift_card": "ギフト券",
}

NOISE_TOKENS = [
    "下書き",
    "アラート",
    "対象外",
    "本部",
    "詳細",
    "削除",
    "未精算",
    "精算済み",
    "経費",
    "領収書",
    "請求書",
    "添付",
    "未添付",
]


def _safe_external_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    if url.startswith("https://") or url.startswith("http://"):
        return url
    return None


def _compact_mf_summary(vendor: str, memo: str) -> str:
    raw = f"{vendor} {memo}".strip()
    raw = raw.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    raw = re.sub(r"\s+", " ", raw).strip()

    raw = re.sub(r"^(?:\d+\s+){1,4}", "", raw).strip()
    raw = re.sub(r"^\d{4}/\d{1,2}/\d{1,2}\([^)]+\)\s*", "", raw).strip()
    for token in NOISE_TOKENS:
        raw = raw.replace(token, " ")

    return re.sub(r"\s+", " ", raw).strip()


def _load_exclusions(reports_dir: Path) -> set[tuple[str, str]]:
    path = reports_dir / "exclude_orders.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return set()
    items = data.get("exclude")
    if not isinstance(items, list):
        return set()
    out: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        order_id = str(item.get("order_id") or "").strip()
        if source not in {"amazon", "rakuten"}:
            continue
        if not order_id or not ORDER_ID_RE.match(order_id):
            continue
        out.add((source, order_id))
    return out


def _workflow_path(reports_dir: Path) -> Path:
    return reports_dir / "workflow.json"


def _read_workflow(reports_dir: Path) -> dict[str, Any]:
    data = _read_json(_workflow_path(reports_dir))
    return data if isinstance(data, dict) else {}


def _write_workflow(reports_dir: Path, data: dict[str, Any]) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    _write_json(_workflow_path(reports_dir), data)


def _resolve_pdf_path_from_order(root: Path, source: str, name_or_path: Any) -> Path | None:
    resolved = _resolve_pdf_path(root, source, name_or_path)
    if resolved:
        return resolved
    if not name_or_path:
        return None
    base_name = Path(str(name_or_path)).name
    if not base_name:
        return None
    return _resolve_pdf_path(root, source, base_name)


def _is_low_confidence_item_name(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if re.match(r"^\d{4}[-/]", text):
        return True
    if re.match(r"^\d{4}\D+\d{1,2}\D+\d{1,2}", text):
        return True
    if re.match(r"^\d{4}.*?/\s*[\u00A5\uFFE5]?\d", text):
        return True
    return False


def _is_missing_total(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in {"", "-", "ー", "―", "—", "–"}
    return False


def _collect_orders(root: Path, ym: str, exclusions: set[tuple[str, str]]) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for source in ("amazon", "rakuten"):
        path = root / source / "orders.jsonl"
        for obj in _read_jsonl(path):
            order_id = str(obj.get("order_id") or "").strip() or None
            order_date = str(obj.get("order_date") or "").strip() or None
            if order_date and not order_date.startswith(ym):
                continue
            status = str(obj.get("status") or "").strip() or "ok"
            total = obj.get("total_yen") if obj.get("total_yen") is not None else obj.get("total")
            item_name = str(obj.get("item_name") or "").strip() or None
            raw_pdf_path = obj.get("pdf_path")
            pdf_path = _resolve_pdf_path_from_order(root, source, raw_pdf_path)
            pdf_name = pdf_path.name if pdf_path else None
            raw.append(
                {
                    "source": source,
                    "order_id": order_id,
                    "order_date": order_date,
                    "total_yen": total,
                    "status": status,
                    "item_name": item_name,
                    "include_flag": obj.get("include"),
                    "has_pdf": bool(pdf_path),
                    "pdf_name": pdf_name,
                    "detail_url": _safe_external_url(obj.get("detail_url")),
                    "receipt_url": _safe_external_url(obj.get("receipt_url")),
                }
            )

    def score(record: dict[str, Any]) -> int:
        s = 0
        if record.get("has_pdf"):
            s += 4
        if record.get("total_yen") not in (None, ""):
            s += 2
        if record.get("item_name"):
            s += 1
        if record.get("order_date"):
            s += 1
        return s

    def merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        base, other = (a, b) if score(a) >= score(b) else (b, a)
        if not base.get("order_date") and other.get("order_date"):
            base["order_date"] = other["order_date"]
        if base.get("total_yen") in (None, "") and other.get("total_yen") not in (None, ""):
            base["total_yen"] = other["total_yen"]
        if not base.get("item_name") and other.get("item_name"):
            base["item_name"] = other["item_name"]
        elif (
            _is_low_confidence_item_name(base.get("item_name"))
            and not _is_low_confidence_item_name(other.get("item_name"))
            and (other.get("has_pdf") or str(other.get("status") or "") == "ok")
        ):
            base["item_name"] = other.get("item_name")
        if base.get("status") in {"unknown_date", "error"} and other.get("status") not in {"unknown_date", "error"}:
            base["status"] = other["status"]
        base["has_pdf"] = base.get("has_pdf") or other.get("has_pdf")
        if not base.get("pdf_name") and other.get("pdf_name"):
            base["pdf_name"] = other.get("pdf_name")
        if base.get("include_flag") is None and other.get("include_flag") is not None:
            base["include_flag"] = other.get("include_flag")
        if not base.get("detail_url") and other.get("detail_url"):
            base["detail_url"] = other.get("detail_url")
        if not base.get("receipt_url") and other.get("receipt_url"):
            base["receipt_url"] = other.get("receipt_url")
        return base

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    extras: list[dict[str, Any]] = []
    for rec in raw:
        order_id = rec.get("order_id")
        if not order_id:
            if not rec.get("has_pdf") and rec.get("status") in {"unknown_date", "error"}:
                continue
            extras.append(rec)
            continue
        key = (rec.get("source"), order_id)
        if key in merged:
            merged[key] = merge(merged[key], rec)
        else:
            merged[key] = rec

    records = list(merged.values()) + extras
    out: list[dict[str, Any]] = []
    for rec in records:
        status = str(rec.get("status") or "ok")
        order_id = rec.get("order_id")
        auto_excluded = status == "gift_card"
        missing_total = _is_missing_total(rec.get("total_yen"))
        default_excluded = (rec.get("include_flag") is False or missing_total) and not auto_excluded
        excluded = auto_excluded or default_excluded or (order_id and (rec.get("source"), order_id) in exclusions)
        can_toggle = bool(order_id) and not auto_excluded
        item_name = rec.get("item_name")
        if _is_low_confidence_item_name(item_name):
            item_name = None
        status_label = STATUS_LABELS.get(status, status)
        has_pdf = bool(rec.get("has_pdf"))
        if status == "ok" and not has_pdf:
            status_label = "\u8981\u518d\u53d6\u5f97\uff08PDF\u306a\u3057\uff09"
        out.append(
            {
                "source": rec.get("source"),
                "source_label": "Amazon" if rec.get("source") == "amazon" else "楽天",
                "order_id": order_id,
                "order_date": rec.get("order_date"),
                "total_yen": rec.get("total_yen"),
                "item_name": item_name,
                "status": status,
                "status_label": status_label,
                "has_pdf": has_pdf,
                "pdf_name": rec.get("pdf_name"),
                "detail_url": rec.get("detail_url"),
                "receipt_url": rec.get("receipt_url"),
                "excluded": excluded,
                "auto_excluded": auto_excluded,
                "can_toggle": can_toggle,
            }
        )

    out.sort(key=lambda x: (x.get("order_date") or "", x.get("order_id") or ""))
    return out


def _resolve_pdf_path(root: Path, source: str, name_or_path: Any) -> Path | None:
    if source not in {"amazon", "rakuten"}:
        return None
    if not name_or_path:
        return None
    raw = str(name_or_path)
    if not raw:
        return None
    p = Path(raw)
    try:
        if not p.is_absolute():
            p = (root / source / "pdfs" / p).resolve()
        else:
            p = p.resolve()
    except Exception:
        return None
    base = (root / source / "pdfs").resolve()
    try:
        p.relative_to(base)
    except Exception:
        return None
    if p.suffix.lower() != ".pdf":
        return None
    if not p.exists():
        return None
    return p


def _collect_excluded_pdfs(root: Path, ym: str, exclusions: set[tuple[str, str]]) -> list[dict[str, Any]]:
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source in ("amazon", "rakuten"):
        path = root / source / "orders.jsonl"
        for obj in _read_jsonl(path):
            order_id = str(obj.get("order_id") or "").strip() or None
            order_date = str(obj.get("order_date") or "").strip() or None
            if order_date and not order_date.startswith(ym):
                continue
            status = str(obj.get("status") or "").strip() or "ok"
            total = obj.get("total_yen") if obj.get("total_yen") is not None else obj.get("total")
            item_name = str(obj.get("item_name") or "").strip() or None
            include_flag = obj.get("include")
            auto_excluded = status == "gift_card"
            missing_total = _is_missing_total(total)
            default_excluded = (include_flag is False or missing_total) and not auto_excluded
            excluded = auto_excluded or default_excluded or (order_id and (source, order_id) in exclusions)
            if not excluded:
                continue
            pdf_path = _resolve_pdf_path_from_order(root, source, obj.get("pdf_path"))
            if not pdf_path:
                continue
            key = (source, order_id or "", pdf_path.name)
            if key in records:
                continue
            records[key] = {
                "source": source,
                "source_label": "Amazon" if source == "amazon" else "楽天",
                "order_id": order_id,
                "order_date": order_date,
                "total_yen": total,
                "item_name": item_name,
                "status": status,
                "status_label": STATUS_LABELS.get(status, status),
                "pdf_name": pdf_path.name,
                "pdf_size_kb": max(1, int(pdf_path.stat().st_size / 1024)),
                "excluded_reason": "自動除外" if auto_excluded or default_excluded else "手動除外",
            }

    rows = list(records.values())
    rows.sort(key=lambda x: (x.get("source") or "", x.get("order_date") or "", x.get("order_id") or ""))
    return rows

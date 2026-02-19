from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .core_shared import (
    DEFAULT_AMAZON_URL,
    DEFAULT_RAKUTEN_URL,
    _archive_action_label,
    YM_RE,
    _artifact_root,
    _ax_home,
    _read_json,
    _read_jsonl,
    _ym_default,
)
from .core_orders import (
    _collect_orders,
    _load_exclusions,
)

DEFAULT_MFCLOUD_EXPENSE_LIST_URL = "https://expense.moneyforward.com/outgo_input"
LEGACY_MFCLOUD_EXPENSE_LIST_URL = "https://expense.moneyforward.com/transactions"


def _format_archive_snapshot_label(name: str) -> str:
    text = str(name or "").strip()
    try:
        dt = datetime.strptime(text, "%Y%m%d_%H%M%S")
    except Exception:
        return text
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _derive_order_counts_from_jsonl(root: Any, ym: str) -> dict[str, int]:
    base = Path(root)
    per_source: dict[str, dict[str, set[str]]] = {
        "amazon": {"total": set(), "in_month": set()},
        "rakuten": {"total": set(), "in_month": set()},
    }
    for source in ("amazon", "rakuten"):
        orders_path = base / source / "orders.jsonl"
        for obj in _read_jsonl(orders_path):
            if not isinstance(obj, dict):
                continue
            order_id = str(obj.get("order_id") or "").strip()
            detail_url = str(obj.get("detail_url") or "").strip()
            record_key = order_id or detail_url
            if not record_key:
                continue
            per_source[source]["total"].add(record_key)
            order_date = str(obj.get("order_date") or "").strip()
            if order_date.startswith(ym):
                per_source[source]["in_month"].add(record_key)
    amazon_total = len(per_source["amazon"]["total"])
    rakuten_total = len(per_source["rakuten"]["total"])
    amazon_in_month = len(per_source["amazon"]["in_month"])
    rakuten_in_month = len(per_source["rakuten"]["in_month"])
    return {
        "amazon_orders_total": amazon_total,
        "rakuten_orders_total": rakuten_total,
        "orders_total": amazon_total + rakuten_total,
        "amazon_orders_in_month": amazon_in_month,
        "rakuten_orders_in_month": rakuten_in_month,
        "orders_in_month": amazon_in_month + rakuten_in_month,
    }


def _derive_exclusion_counts(root: Path, ym: str) -> dict[str, int]:
    reports_dir = root / "reports"
    exclusions = _load_exclusions(reports_dir)
    orders = _collect_orders(root, ym, exclusions)
    excluded_orders = [o for o in orders if o.get("excluded")]
    amazon_excluded = sum(1 for o in excluded_orders if o.get("source") == "amazon")
    rakuten_excluded = sum(1 for o in excluded_orders if o.get("source") == "rakuten")
    return {
        "manual_excluded_orders": len(exclusions),
        "excluded_orders": len(excluded_orders),
        "included_orders": max(0, len(orders) - len(excluded_orders)),
        "amazon_excluded_orders": amazon_excluded,
        "rakuten_excluded_orders": rakuten_excluded,
    }


def _scan_artifacts() -> list[dict[str, Any]]:
    root = _artifact_root()
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for p in root.iterdir():
        if not p.is_dir():
            continue
        if p.name == "_runs":
            continue
        if not YM_RE.match(p.name):
            continue

        reports_dir = p / "reports"
        missing_json = reports_dir / "missing_evidence_candidates.json"
        run_config = p / "run_config.resolved.json"

        data = _read_json(missing_json) or {}
        counts = data.get("counts") if isinstance(data, dict) else {}
        merged_counts = dict(counts or {})
        merged_counts.update(_derive_order_counts_from_jsonl(p, p.name))
        merged_counts.update(_derive_exclusion_counts(p, p.name))
        rows = data.get("rows") if isinstance(data, dict) else None
        rows_count = len(rows) if isinstance(rows, list) else None

        amazon_pdfs = list((p / "amazon" / "pdfs").glob("*.pdf")) if (p / "amazon" / "pdfs").exists() else []
        rakuten_pdfs = list((p / "rakuten" / "pdfs").glob("*.pdf")) if (p / "rakuten" / "pdfs").exists() else []

        items.append(
            {
                "ym": p.name,
                "path": str(p),
                "has_reports": reports_dir.exists(),
                "counts": merged_counts,
                "report_rows": rows_count,
                "amazon_pdf_count": len(amazon_pdfs),
                "rakuten_pdf_count": len(rakuten_pdfs),
                "run_config": _read_json(run_config) or {},
            }
        )

    items.sort(key=lambda x: x["ym"], reverse=True)
    return items


def _scan_archive_history(*, limit: int = 30) -> list[dict[str, Any]]:
    root = _artifact_root()
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for p in root.iterdir():
        if not p.is_dir() or p.name == "_runs" or not YM_RE.match(p.name):
            continue
        audit_path = p / "reports" / "audit_log.jsonl"
        if not audit_path.exists():
            continue
        for line in audit_path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = str(line or "").strip()
            if not text.startswith("{") or not text.endswith("}"):
                continue
            try:
                obj = json.loads(text)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if str(obj.get("event_type") or "").strip() != "archive":
                continue
            if str(obj.get("status") or "").strip() != "success":
                continue
            action = str(obj.get("action") or "").strip()
            if action not in {"manual_archive", "month_close"}:
                continue
            details = obj.get("details") if isinstance(obj.get("details"), dict) else {}
            ts = str(obj.get("ts") or "").strip()
            action_label = _archive_action_label(action)
            rows.append(
                {
                    "ym": p.name,
                    "ts": ts,
                    "action": action,
                    "action_label": action_label,
                    "archived_to": str(details.get("archived_to") or "").strip(),
                    "archive_url": f"/runs/{p.name}/archived-receipts",
                }
            )
    rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    if limit > 0:
        return rows[:limit]
    return rows


def _scan_archived_receipts(root: Any) -> dict[str, Any]:
    base = Path(root)
    archive_root = base / "archive"
    snapshots: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    if not archive_root.exists():
        return {
            "archive_root": str(archive_root),
            "snapshot_count": 0,
            "receipt_count": 0,
            "amazon_count": 0,
            "rakuten_count": 0,
            "snapshots": snapshots,
            "rows": rows,
        }

    for snap_dir in sorted((p for p in archive_root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        snapshot_name = snap_dir.name
        snapshot_label = _format_archive_snapshot_label(snapshot_name)
        source_counts = {"amazon": 0, "rakuten": 0}

        for source in ("amazon", "rakuten"):
            pdf_dir = snap_dir / source / "pdfs"
            if not pdf_dir.exists():
                continue
            for pdf_path in sorted(pdf_dir.glob("*.pdf")):
                try:
                    size_kb = max(1, int(pdf_path.stat().st_size / 1024))
                except Exception:
                    size_kb = 0
                source_counts[source] += 1
                rows.append(
                    {
                        "snapshot": snapshot_name,
                        "snapshot_label": snapshot_label,
                        "source": source,
                        "source_label": "Amazon" if source == "amazon" else "楽天",
                        "pdf_name": pdf_path.name,
                        "pdf_size_kb": size_kb,
                    }
                )

        snapshots.append(
            {
                "snapshot": snapshot_name,
                "snapshot_label": snapshot_label,
                "path": str(snap_dir),
                "amazon_count": source_counts["amazon"],
                "rakuten_count": source_counts["rakuten"],
                "receipt_count": source_counts["amazon"] + source_counts["rakuten"],
            }
        )

    return {
        "archive_root": str(archive_root),
        "snapshot_count": len(snapshots),
        "receipt_count": len(rows),
        "amazon_count": sum(int(item.get("amazon_count") or 0) for item in snapshots),
        "rakuten_count": sum(int(item.get("rakuten_count") or 0) for item in snapshots),
        "snapshots": snapshots,
        "rows": rows,
    }


def _latest_run_config() -> dict[str, Any]:
    for item in _scan_artifacts():
        cfg = item.get("run_config")
        if isinstance(cfg, dict) and cfg:
            return cfg
    return {}


def _load_config_file() -> dict[str, Any]:
    config_path = _ax_home() / "configs" / "mfcloud-expense-receipt-reconcile.json"
    data = _read_json(config_path)
    return data if isinstance(data, dict) else {}


def _extract_urls_from_config_section(section: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    tenant = section.get("tenant") if isinstance(section.get("tenant"), dict) else {}
    tenant_urls = tenant.get("urls") if isinstance(tenant.get("urls"), dict) else {}
    legacy_urls = section.get("urls") if isinstance(section.get("urls"), dict) else {}
    return tenant_urls, legacy_urls


def _coerce_valid_year_month(
    year_value: Any,
    month_value: Any,
    *,
    fallback_year: int,
    fallback_month: int,
) -> tuple[int, int]:
    try:
        year = int(year_value)
    except Exception:
        year = fallback_year
    try:
        month = int(month_value)
    except Exception:
        month = fallback_month
    if year < 2000 or year > 3000:
        year = fallback_year
    if month < 1 or month > 12:
        month = fallback_month
    return year, month


def _resolve_form_defaults() -> dict[str, Any]:
    fallback_year, fallback_month = _ym_default()
    defaults: dict[str, Any] = {
        "year": fallback_year,
        "month": fallback_month,
        "mfcloud_url": DEFAULT_MFCLOUD_EXPENSE_LIST_URL,
        "rakuten_enabled": False,
        "notes": "",
        "rakuten_orders_url": DEFAULT_RAKUTEN_URL,
        "amazon_orders_url": DEFAULT_AMAZON_URL,
    }

    last_run = _latest_run_config()
    if last_run:
        resolved_year, resolved_month = _coerce_valid_year_month(
            last_run.get("year"),
            last_run.get("month"),
            fallback_year=int(defaults["year"]),
            fallback_month=int(defaults["month"]),
        )
        defaults["year"] = resolved_year
        defaults["month"] = resolved_month
        tenant_urls, legacy_urls = _extract_urls_from_config_section(last_run)
        defaults["mfcloud_url"] = (
            tenant_urls.get("mfcloud_expense_list")
            or legacy_urls.get("mfcloud_expense_list")
            or defaults["mfcloud_url"]
        )
        defaults["amazon_orders_url"] = (
            tenant_urls.get("amazon_orders")
            or legacy_urls.get("amazon_orders")
            or defaults["amazon_orders_url"]
        )
        rakuten = last_run.get("rakuten") if isinstance(last_run.get("rakuten"), dict) else {}
        defaults["rakuten_enabled"] = bool(rakuten.get("enabled", defaults["rakuten_enabled"]))
        defaults["rakuten_orders_url"] = (
            tenant_urls.get("rakuten_orders")
            or rakuten.get("orders_url")
            or defaults["rakuten_orders_url"]
        )
        defaults["notes"] = last_run.get("monthly_notes") or defaults["notes"]

    config = _load_config_file()
    cfg = config.get("config") if isinstance(config.get("config"), dict) else {}
    tenant_urls, legacy_urls = _extract_urls_from_config_section(cfg)
    rakuten = cfg.get("rakuten") if isinstance(cfg.get("rakuten"), dict) else {}
    defaults["mfcloud_url"] = (
        tenant_urls.get("mfcloud_expense_list")
        or legacy_urls.get("mfcloud_expense_list")
        or defaults["mfcloud_url"]
    )
    defaults["amazon_orders_url"] = (
        tenant_urls.get("amazon_orders")
        or legacy_urls.get("amazon_orders")
        or defaults["amazon_orders_url"]
    )
    defaults["rakuten_enabled"] = bool(rakuten.get("enabled", defaults["rakuten_enabled"]))
    defaults["rakuten_orders_url"] = (
        tenant_urls.get("rakuten_orders")
        or rakuten.get("orders_url")
        or defaults["rakuten_orders_url"]
    )
    defaults["notes"] = cfg.get("monthly_notes") or defaults["notes"]

    mfcloud_url = str(defaults.get("mfcloud_url") or "").strip()
    if not mfcloud_url or mfcloud_url == LEGACY_MFCLOUD_EXPENSE_LIST_URL:
        defaults["mfcloud_url"] = DEFAULT_MFCLOUD_EXPENSE_LIST_URL

    defaults["year"], defaults["month"] = _coerce_valid_year_month(
        defaults.get("year"),
        defaults.get("month"),
        fallback_year=fallback_year,
        fallback_month=fallback_month,
    )

    return defaults

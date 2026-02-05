from __future__ import annotations

from typing import Any

from .core_shared import (
    DEFAULT_AMAZON_URL,
    DEFAULT_RAKUTEN_URL,
    YM_RE,
    _artifact_root,
    _ax_home,
    _read_json,
    _ym_default,
)


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
        rows = data.get("rows") if isinstance(data, dict) else None
        rows_count = len(rows) if isinstance(rows, list) else None

        amazon_pdfs = list((p / "amazon" / "pdfs").glob("*.pdf")) if (p / "amazon" / "pdfs").exists() else []
        rakuten_pdfs = list((p / "rakuten" / "pdfs").glob("*.pdf")) if (p / "rakuten" / "pdfs").exists() else []

        items.append(
            {
                "ym": p.name,
                "path": str(p),
                "has_reports": reports_dir.exists(),
                "counts": counts or {},
                "report_rows": rows_count,
                "amazon_pdf_count": len(amazon_pdfs),
                "rakuten_pdf_count": len(rakuten_pdfs),
                "run_config": _read_json(run_config) or {},
            }
        )

    items.sort(key=lambda x: x["ym"], reverse=True)
    return items


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


def _resolve_form_defaults() -> dict[str, Any]:
    year, month = _ym_default()
    defaults: dict[str, Any] = {
        "year": year,
        "month": month,
        "mfcloud_url": "",
        "rakuten_enabled": False,
        "notes": "",
        "rakuten_orders_url": DEFAULT_RAKUTEN_URL,
        "amazon_orders_url": DEFAULT_AMAZON_URL,
    }

    last_run = _latest_run_config()
    if last_run:
        defaults["year"] = last_run.get("year") or defaults["year"]
        defaults["month"] = last_run.get("month") or defaults["month"]
        urls = last_run.get("urls") if isinstance(last_run.get("urls"), dict) else {}
        defaults["mfcloud_url"] = urls.get("mfcloud_expense_list") or defaults["mfcloud_url"]
        defaults["amazon_orders_url"] = urls.get("amazon_orders") or defaults["amazon_orders_url"]
        rakuten = last_run.get("rakuten") if isinstance(last_run.get("rakuten"), dict) else {}
        defaults["rakuten_enabled"] = bool(rakuten.get("enabled", defaults["rakuten_enabled"]))
        defaults["rakuten_orders_url"] = rakuten.get("orders_url") or defaults["rakuten_orders_url"]
        defaults["notes"] = last_run.get("monthly_notes") or defaults["notes"]

    config = _load_config_file()
    cfg = config.get("config") if isinstance(config.get("config"), dict) else {}
    urls = cfg.get("urls") if isinstance(cfg.get("urls"), dict) else {}
    rakuten = cfg.get("rakuten") if isinstance(cfg.get("rakuten"), dict) else {}
    defaults["mfcloud_url"] = urls.get("mfcloud_expense_list") or defaults["mfcloud_url"]
    defaults["amazon_orders_url"] = urls.get("amazon_orders") or defaults["amazon_orders_url"]
    defaults["rakuten_enabled"] = bool(rakuten.get("enabled", defaults["rakuten_enabled"]))
    defaults["rakuten_orders_url"] = rakuten.get("orders_url") or defaults["rakuten_orders_url"]
    defaults["notes"] = cfg.get("monthly_notes") or defaults["notes"]

    return defaults

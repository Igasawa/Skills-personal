#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

try:
    from .run_support import (
        _as_bool,
        _as_int,
        _build_report_markdown,
        _now_utc_iso,
    )
    from .run_processing_config import _prepare_audit_context
    from .run_processing_items import _collect_audit_items
except Exception:  # pragma: no cover - direct script execution fallback
    from run_support import (  # type: ignore
        _as_bool,
        _as_int,
        _build_report_markdown,
        _now_utc_iso,
    )
    from run_processing_config import _prepare_audit_context
    from run_processing_items import _collect_audit_items


def _execute_audit(
    args,
    *,
    raw_input: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {"status": "ok", "data": {}, "error": None}

    context = _prepare_audit_context(args, raw_input)

    scan_paths = context["scan_paths"]
    extensions = context["extensions"]
    exclude_dirs = context["exclude_dirs"]
    max_age_days = context["max_age_days"]
    warn_within_days = context["warn_within_days"]
    as_of = context["as_of_raw"]
    if as_of is None:
        as_of = dt.date.today()
    elif isinstance(as_of, str):
        as_of = dt.date.fromisoformat(as_of)
    as_of = dt.date.today() if not isinstance(as_of, dt.date) else as_of

    dry_run = context["dry_run"]
    fail_on_stale = context["fail_on_stale"]
    bootstrap_missing_review_date = context["bootstrap_missing_review_date"]
    bootstrap_review_source = context["bootstrap_review_source"]
    strict_bootstrap = context["strict_bootstrap"]
    write_report_requested = context["write_report_requested"]
    write_report = context["write_report"]
    report_dir = context["report_dir"]
    registry = context["registry"]
    files = context["files"]
    missing_paths = context["missing_paths"]

    default_max_age = _as_int(context["default_max_age"], name="registry.defaults.max_age_days", default=max_age_days)
    default_warn = _as_int(context["default_warn"], name="registry.defaults.warn_within_days", default=warn_within_days)
    default_require_sources = _as_bool(context["default_require_sources"], default=False)

    if max_age_days <= 0:
        raise ValueError("max_age_days must be > 0")
    if warn_within_days < 0:
        raise ValueError("warn_within_days must be >= 0")

    items, stale_items, warning_items, fresh_items = _collect_audit_items(
        files,
        as_of,
        max_age_days=max_age_days,
        warn_within_days=warn_within_days,
        reg_rules=context["reg_rules"],
        default_max_age=default_max_age,
        default_warn=default_warn,
        default_require_sources=default_require_sources,
        bootstrap_missing_review_date=bootstrap_missing_review_date,
        bootstrap_review_source=bootstrap_review_source,
        strict_bootstrap=strict_bootstrap,
        dry_run=dry_run,
        cwd=Path.cwd(),
        scan_roots=context["scan_roots"],
    )
    bootstrap_items = [item for item in items if item.get("bootstrap_applied")]

    generated_at = _now_utc_iso()
    report_path: str | None = None
    if write_report:
        report_dir.mkdir(parents=True, exist_ok=True)
        filename = f"knowledge_refresh_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path = report_dir / filename
        summary = {
            "scanned": len(items),
            "stale": len(stale_items),
            "warning": len(warning_items),
            "fresh": len(fresh_items),
        }
        report_md = _build_report_markdown(
            generated_at=generated_at,
            as_of=as_of.isoformat(),
            scan_paths=scan_paths,
            summary=summary,
            stale_items=stale_items,
            warning_items=warning_items,
            bootstrap_items=bootstrap_items,
        )
        path.write_text(report_md, encoding="utf-8", newline="\n")
        report_path = str(path)

    out["data"] = {
        "generated_at": generated_at,
        "as_of": as_of.isoformat(),
        "planned": {
            "dry_run": dry_run,
            "scan_paths": scan_paths,
            "extensions": extensions,
            "exclude_dirs": exclude_dirs,
            "max_age_days": max_age_days,
            "warn_within_days": warn_within_days,
            "fail_on_stale": fail_on_stale,
            "bootstrap_missing_review_date": bootstrap_missing_review_date,
            "bootstrap_review_source": bootstrap_review_source,
            "strict_bootstrap": strict_bootstrap,
            "write_report_requested": write_report_requested,
            "write_report": write_report,
            "registry_path": registry.get("path"),
        },
        "summary": {
            "scanned": len(items),
            "stale": len(stale_items),
            "warning": len(warning_items),
            "fresh": len(fresh_items),
            "missing_scan_paths": len(missing_paths),
        },
        "missing_scan_paths": missing_paths,
        "items": items,
        "stale_items": stale_items,
        "warning_items": warning_items,
        "bootstrap_items": bootstrap_items,
        "report": {
            "path": report_path,
            "written": bool(report_path),
            "report_dir": str(report_dir),
        },
    }

    if fail_on_stale and len(stale_items) > 0:
        out["status"] = "error"
        out["error"] = {"message": f"stale documents found: {len(stale_items)}"}
        return out, 1

    return out, 0


__all__ = ["_execute_audit"]

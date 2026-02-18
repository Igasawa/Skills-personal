#!/usr/bin/env python3
"""Build execution context for knowledge-refresh audits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .run_support import (
        _as_bool,
        _as_int,
        _as_string_list,
        _ax_home,
        _blank_to_none,
        _coalesce,
        _discover_files,
        _load_registry,
    )
except Exception:  # pragma: no cover - direct script execution fallback
    from run_support import (
        _as_bool,
        _as_int,
        _as_string_list,
        _ax_home,
        _blank_to_none,
        _coalesce,
        _discover_files,
        _load_registry,
    )


def _prepare_audit_context(args, raw_input: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize all runtime values used by audit processing."""
    config = raw_input.get("config") if isinstance(raw_input.get("config"), dict) else {}
    params = raw_input.get("params") if isinstance(raw_input.get("params"), dict) else {}

    targets_cfg = config.get("targets") if isinstance(config.get("targets"), dict) else {}
    policy_cfg = config.get("policy") if isinstance(config.get("policy"), dict) else {}
    report_cfg = config.get("report") if isinstance(config.get("report"), dict) else {}
    registry_cfg = config.get("registry") if isinstance(config.get("registry"), dict) else {}

    scan_paths = (
        args.scan
        if args.scan
        else _as_string_list(
            _coalesce(params.get("scan_paths"), targets_cfg.get("paths")),
            default=["docs"],
        )
    )
    extensions = (
        args.extension
        if args.extension
        else _as_string_list(
            _coalesce(params.get("extensions"), targets_cfg.get("extensions")),
            default=[".md"],
        )
    )
    exclude_dirs = (
        args.exclude_dir
        if args.exclude_dir
        else _as_string_list(
            _coalesce(params.get("exclude_dirs"), targets_cfg.get("exclude_dirs")),
            default=[".git", "output", "node_modules", "__pycache__"],
        )
    )
    scan_roots = [Path(raw).expanduser().resolve() for raw in scan_paths]

    max_age_days = _as_int(
        _coalesce(
            args.max_age_days, params.get("max_age_days"), policy_cfg.get("default_max_age_days")
        ),
        name="max_age_days",
        default=30,
    )
    warn_within_days = _as_int(
        _coalesce(args.warn_within_days, params.get("warn_within_days"), policy_cfg.get("warn_within_days")),
        name="warn_within_days",
        default=7,
    )

    dry_run = True
    if args.apply:
        dry_run = False
    elif args.dry_run:
        dry_run = True
    else:
        dry_run = _as_bool(_coalesce(config.get("dry_run"), params.get("dry_run")), default=True)

    fail_on_stale = _as_bool(
        _coalesce(args.fail_on_stale, params.get("fail_on_stale"), policy_cfg.get("fail_on_stale")),
        default=False,
    )
    bootstrap_missing_review_date = _as_bool(
        _coalesce(args.bootstrap_missing_review_date, params.get("bootstrap_missing_review_date")),
        default=False,
    )
    strict_bootstrap = _as_bool(
        _coalesce(args.strict_bootstrap, params.get("strict_bootstrap")),
        default=False,
    )
    bootstrap_review_source = _blank_to_none(
        _coalesce(args.bootstrap_review_source, params.get("bootstrap_review_source")),
    ) or "knowledge_refresh_weekly"
    write_report_requested = _as_bool(
        _coalesce(args.write_report, params.get("write_report"), report_cfg.get("write_markdown")),
        default=False,
    )
    write_report = bool(write_report_requested and not dry_run)

    report_dir_raw = _blank_to_none(
        _coalesce(args.report_dir, params.get("report_dir"), report_cfg.get("output_dir"))
    )
    report_dir = (
        Path(report_dir_raw).expanduser()
        if report_dir_raw
        else (_ax_home() / "reports" / "knowledge_refresh")
    )

    registry_path = _blank_to_none(
        _coalesce(args.registry, params.get("registry_path"), registry_cfg.get("path"))
    )
    registry = _load_registry(registry_path)

    reg_defaults = registry.get("defaults") if isinstance(registry.get("defaults"), dict) else {}
    reg_rules = registry.get("rules") if isinstance(registry.get("rules"), list) else []

    files, missing_paths = _discover_files(
        scan_paths=scan_paths, extensions=extensions, exclude_dirs=exclude_dirs
    )

    return {
        "scan_paths": scan_paths,
        "extensions": extensions,
        "exclude_dirs": exclude_dirs,
        "scan_roots": scan_roots,
        "max_age_days": max_age_days,
        "warn_within_days": warn_within_days,
        "as_of_raw": _blank_to_none(
            _coalesce(args.as_of, params.get("as_of"), policy_cfg.get("as_of"))
        ),
        "dry_run": dry_run,
        "fail_on_stale": fail_on_stale,
        "bootstrap_missing_review_date": bootstrap_missing_review_date,
        "strict_bootstrap": strict_bootstrap,
        "bootstrap_review_source": bootstrap_review_source,
        "write_report_requested": write_report_requested,
        "write_report": write_report,
        "report_dir": report_dir,
        "registry": registry,
        "files": files,
        "missing_paths": missing_paths,
        "reg_defaults": reg_defaults,
        "reg_rules": reg_rules,
        "default_max_age": reg_defaults.get("max_age_days"),
        "default_warn": reg_defaults.get("warn_within_days"),
        "default_require_sources": reg_defaults.get("require_source_urls"),
    }


__all__ = ["_prepare_audit_context"]

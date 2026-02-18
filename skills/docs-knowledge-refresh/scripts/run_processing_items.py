#!/usr/bin/env python3
"""Collect audit results for knowledge-refresh documents."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

try:
    from .run_support import (
        URL_RE,
        _as_bool,
        _as_int,
        _blank_to_none,
        _extract_review_date,
        _prepend_review_frontmatter,
        _load_text,
        _rel_posix,
        _select_rule,
        _write_text,
    )
except Exception:  # pragma: no cover - direct script execution fallback
    from run_support import (  # type: ignore
        URL_RE,
        _as_bool,
        _as_int,
        _blank_to_none,
        _extract_review_date,
        _prepend_review_frontmatter,
        _load_text,
        _rel_posix,
        _select_rule,
        _write_text,
    )


def _collect_audit_items(
    files: list[Path],
    as_of: dt.date,
    *,
    max_age_days: int,
    warn_within_days: int,
    reg_rules: list[dict[str, Any]],
    default_max_age: int,
    default_warn: int,
    default_require_sources: bool,
    bootstrap_missing_review_date: bool = False,
    bootstrap_review_source: str | None = None,
    strict_bootstrap: bool = False,
    dry_run: bool = False,
    cwd: Path,
    scan_roots: list[Path] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    items: list[dict[str, Any]] = []
    stale_items: list[dict[str, Any]] = []
    warning_items: list[dict[str, Any]] = []
    fresh_items: list[dict[str, Any]] = []

    for file_path in files:
        rel_path = _normalize_match_path(
            file_path,
            scan_roots=scan_roots or [],
            cwd=cwd,
        )
        text, encoding_used = _load_text(file_path)
        review_date, review_date_key, review_source = _extract_review_date(text)
        source_urls = sorted(set(URL_RE.findall(text)))

        matched_rule = _select_rule(rel_path, reg_rules)
        eff_max_age = default_max_age
        eff_warn = default_warn
        eff_owner = None
        eff_require_sources = default_require_sources
        matched_pattern = None

        if matched_rule:
            matched_pattern = matched_rule.get("pattern")
            eff_max_age = _as_int(
                matched_rule.get("max_age_days"),
                name=f"rule({matched_pattern}).max_age_days",
                default=eff_max_age,
            )
            eff_warn = _as_int(
                matched_rule.get("warn_within_days"),
                name=f"rule({matched_pattern}).warn_within_days",
                default=eff_warn,
            )
            eff_owner = _blank_to_none(matched_rule.get("owner"))
            eff_require_sources = _as_bool(
                matched_rule.get("require_source_urls"), default=eff_require_sources
            )

        if eff_max_age <= 0:
            raise ValueError(f"Invalid max_age_days for {rel_path}: {eff_max_age}")
        if eff_warn < 0:
            raise ValueError(f"Invalid warn_within_days for {rel_path}: {eff_warn}")

        state = "fresh"
        reasons: list[str] = []
        age_days: int | None = None
        review_date_str: str | None = None
        bootstrap_applied = False

        if review_date is None:
            if bootstrap_missing_review_date:
                bootstrap_source = _blank_to_none(bootstrap_review_source) or "knowledge_refresh_weekly"
                if not dry_run:
                    try:
                        new_text, _ = _prepend_review_frontmatter(
                            text,
                            as_of.isoformat(),
                            bootstrap_source,
                        )
                        _write_text(file_path, new_text, encoding_used)
                        review_date = as_of
                        review_date_str = as_of.isoformat()
                        review_source = bootstrap_source
                        age_days = 0
                        bootstrap_applied = True
                        state = "stale" if strict_bootstrap else "warning"
                        reasons.append("review_date_bootstrapped")
                        if strict_bootstrap:
                            reasons.append("strict_bootstrap")
                    except OSError as exc:
                        state = "stale"
                        reasons.append("review_date_missing")
                        reasons.append(f"review_date_bootstrap_failed:{exc}")
                else:
                    state = "stale"
                    reasons.append("review_date_missing")
            else:
                state = "stale"
                reasons.append("review_date_missing")
        if review_date is not None and not bootstrap_applied:
            review_date_str = review_date.isoformat()
            age_days = (as_of - review_date).days
            if age_days < 0:
                state = "warning"
                reasons.append("review_date_in_future")
            elif age_days > eff_max_age:
                state = "stale"
                reasons.append("age_over_limit")
            else:
                warn_start = max(0, eff_max_age - eff_warn)
                if age_days >= warn_start:
                    state = "warning"
                    reasons.append("due_soon")

        if eff_require_sources and len(source_urls) == 0:
            state = "stale"
            reasons.append("source_url_missing")

        item = {
            "path": rel_path,
            "review_date": review_date_str,
            "review_date_key": review_date_key,
            "review_source": review_source,
            "age_days": age_days,
            "max_age_days": eff_max_age,
            "warn_within_days": eff_warn,
            "require_source_urls": eff_require_sources,
            "source_url_count": len(source_urls),
            "owner": eff_owner,
            "matched_rule": matched_pattern,
            "state": state,
            "reasons": reasons,
            "encoding_used": encoding_used,
            "bootstrap_applied": bootstrap_applied,
        }
        items.append(item)

        if state == "stale":
            stale_items.append(item)
        elif state == "warning":
            warning_items.append(item)
        else:
            fresh_items.append(item)

    return items, stale_items, warning_items, fresh_items


def _normalize_match_path(
    file_path: Path,
    scan_roots: list[Path] | None = None,
    cwd: Path | None = None,
) -> str:
    import os

    scan_roots = scan_roots or []
    cwd = cwd or Path.cwd()
    file_resolved = file_path.resolve()
    for root in scan_roots:
        root_resolved = root.resolve()
        try:
            relative = file_resolved.relative_to(root_resolved).as_posix()
            root_display = os.path.relpath(root_resolved, cwd).replace("\\", "/")
            while root_display.startswith("../"):
                root_display = root_display[3:]
            root_display = root_display.lstrip("/")
            if root_display:
                return f"{root_display.rstrip('/')}/{relative}" if relative else root_display
            return relative
        except Exception:
            continue

    rel = os.path.relpath(file_resolved, cwd).replace("\\", "/")
    rel = rel.replace("\\", "/")
    while rel.startswith("../"):
        rel = rel[3:]
    rel = rel.lstrip("/")
    return rel


__all__ = ["_collect_audit_items"]

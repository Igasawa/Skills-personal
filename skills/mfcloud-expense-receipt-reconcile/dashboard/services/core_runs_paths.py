from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from .core_shared import YM_RE, _artifact_root, _running_mode_for_ym as _running_mode_for_ym_common


def _preflight_global_path() -> Path:
    return _artifact_root() / "_preflight.json"


def _audit_log_path(year: int, month: int) -> Path:
    return _artifact_root() / f"{year:04d}-{month:02d}" / "reports" / "audit_log.jsonl"


def _mf_draft_actions_path(year: int, month: int) -> Path:
    return _artifact_root() / f"{year:04d}-{month:02d}" / "reports" / "mf_draft_create_actions.jsonl"


def _safe_ym(ym: str) -> str:
    if not YM_RE.match(ym):
        raise HTTPException(status_code=400, detail="Invalid year-month format.")
    return ym


def _running_mode_for_ym(year: int, month: int) -> str | None:
    return _running_mode_for_ym_common(year, month)

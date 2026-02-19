from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from .core_shared import YM_RE, _artifact_root, _read_json, _runs_root


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
    root = _runs_root()
    if not root.exists():
        return None

    running_jobs: list[tuple[str, str]] = []
    for p in root.glob("run_*.json"):
        data = _read_json(p)
        if not isinstance(data, dict):
            continue
        if data.get("status") != "running":
            continue
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        if params.get("year") != year or params.get("month") != month:
            continue
        running_jobs.append((str(data.get("started_at") or ""), str(params.get("mode") or "")))

    running_jobs.sort(key=lambda item: item[0], reverse=True)
    if not running_jobs:
        return None
    return running_jobs[0][1]

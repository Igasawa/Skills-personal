from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def coerce_non_negative_int(value: Any, default: int = 0) -> int:
    parsed = safe_int(value)
    if parsed is None or parsed < 0:
        return default
    return parsed


def normalize_actor(actor: Any) -> dict[str, Any]:
    if isinstance(actor, dict):
        out: dict[str, Any] = {}
        for key in ("channel", "id", "ip", "user_agent"):
            value = actor.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                out[key] = text
        if out:
            return out
    return {"channel": "dashboard", "id": "unknown"}


def tail_text(path: Path, *, max_bytes: int = 32000) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    limit = max(0, int(max_bytes))
    if limit and len(data) > limit:
        data = data[-limit:]
    return data.decode("utf-8", errors="replace")


def append_audit_event(
    *,
    path: Path,
    year: int,
    month: int,
    event_type: str,
    action: str,
    status: str,
    actor: Any = None,
    source: str | None = None,
    mode: str | None = None,
    run_id: str | None = None,
    details: dict[str, Any] | None = None,
    normalize_actor_fn: Callable[[Any], dict[str, Any]] = normalize_actor,
    now: Callable[[], datetime] = datetime.now,
    json_dumps: Callable[..., str] = json.dumps,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "ts": now().isoformat(timespec="seconds"),
        "ym": f"{year:04d}-{month:02d}",
        "year": year,
        "month": month,
        "event_type": str(event_type).strip(),
        "action": str(action).strip(),
        "status": str(status).strip(),
        "actor": normalize_actor_fn(actor),
    }
    if source:
        entry["source"] = str(source).strip()
    if mode:
        entry["mode"] = str(mode).strip()
    if run_id:
        entry["run_id"] = str(run_id).strip()
    if isinstance(details, dict) and details:
        entry["details"] = details
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json_dumps(entry, ensure_ascii=False) + "\n")


def running_mode_for_ym(
    *,
    year: int,
    month: int,
    runs_root: Path,
    read_json: Callable[[Path], Any],
) -> str | None:
    if not runs_root.exists():
        return None

    running_jobs: list[tuple[str, str]] = []
    for path in runs_root.glob("run_*.json"):
        data = read_json(path)
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


def list_run_jobs(
    *,
    runs_root: Path,
    read_json: Callable[[Path], Any],
) -> list[dict[str, Any]]:
    if not runs_root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in runs_root.glob("run_*.json"):
        data = read_json(path) or {}
        if isinstance(data, dict) and data:
            items.append(data)
    items.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    return items


def running_job_exists(jobs: list[dict[str, Any]]) -> bool:
    for job in jobs:
        if str(job.get("status") or "") == "running":
            return True
    return False


def latest_running_job(jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for job in jobs:
        if str(job.get("status") or "") == "running":
            return job
    return None

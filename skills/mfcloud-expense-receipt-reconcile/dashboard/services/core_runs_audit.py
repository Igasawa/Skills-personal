from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .core_runs_paths import _audit_log_path
from .core_shared import SKILL_ROOT, _write_json

_AUTH_REQUIRED_MARKERS = (
    "auth_required",
    "[auth_required]",
    "please complete login in the browser",
    "timeout waiting for manual login",
    "still on login page",
    "storage_state expired",
)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _coerce_non_negative_int(value: Any, default: int = 0) -> int:
    parsed = _safe_int(value)
    if parsed is None:
        return default
    if parsed < 0:
        return default
    return parsed


def _normalize_actor(actor: Any) -> dict[str, Any]:
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


def _tail_text(path: Path, *, max_bytes: int = 32000) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    limit = max(0, int(max_bytes))
    if limit and len(data) > limit:
        data = data[-limit:]
    return data.decode("utf-8", errors="replace")


def _is_test_artifact_log_path(log_path: str) -> bool:
    normalized = str(log_path or "").strip().lower().replace("\\", "/")
    if not normalized:
        return False
    return "pytest-of-" in normalized or "/pytest-" in normalized


def _contains_auth_required_marker(log_tail: str) -> bool:
    lowered = str(log_tail or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in _AUTH_REQUIRED_MARKERS)


def _suppression_reason_for_failed_run_incident(
    *,
    mode: str,
    reason: str,
    log_path: str,
    log_tail: str,
) -> str:
    if mode not in {"amazon_download", "rakuten_download"}:
        return ""
    if _is_test_artifact_log_path(log_path):
        return "test_artifact_run"
    if _contains_auth_required_marker(log_tail):
        return "auth_required"
    compact = " ".join(str(log_tail or "").split())
    if mode == "amazon_download" and reason == "process_ended_without_final_status":
        if compact == "[run] Amazon download start":
            return "incomplete_provider_start_log"
    if mode == "rakuten_download" and reason == "worker_exit":
        if compact in {"", "[run] Rakuten download start"}:
            return "incomplete_provider_start_log"
    return ""


def _append_audit_event(
    *,
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
    _audit_log_path_fn=_audit_log_path,
    _normalize_actor_fn=_normalize_actor,
    _json_dumps=json.dumps,
    _now=datetime.now,
) -> None:
    path = _audit_log_path_fn(year, month)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "ts": _now().isoformat(timespec="seconds"),
        "ym": f"{year:04d}-{month:02d}",
        "year": year,
        "month": month,
        "event_type": str(event_type).strip(),
        "action": str(action).strip(),
        "status": str(status).strip(),
        "actor": _normalize_actor_fn(actor),
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
        handle.write(_json_dumps(entry, ensure_ascii=False) + "\n")


def _capture_failed_run_incident(
    *,
    meta_path: Path,
    meta: dict[str, Any],
    reason: str,
    inferred_from: str = "",
    _safe_int_fn=_safe_int,
    _subprocess_fn: Any = subprocess,
    _write_json_fn=_write_json,
    _append_audit_event_fn=_append_audit_event,
    _audit_log_path_fn=_audit_log_path,
    _skill_root: Path = SKILL_ROOT,
    _json_loads=json.loads,
    _json_dumps=json.dumps,
    _now=datetime.now,
    _tail_text_fn=_tail_text,
    _suppression_reason_fn=_suppression_reason_for_failed_run_incident,
) -> None:
    status = str(meta.get("status") or "").strip().lower()
    if status != "failed":
        return
    if str(meta.get("error_incident_id") or "").strip():
        return
    if str(meta.get("error_capture_attempted_at") or "").strip():
        return

    ts = _now().isoformat(timespec="seconds")
    meta["error_capture_attempted_at"] = ts

    params = meta.get("params") if isinstance(meta.get("params"), dict) else {}
    year = _safe_int_fn(params.get("year"))
    month = _safe_int_fn(params.get("month"))
    mode = str(params.get("mode") or "").strip() or "unknown"
    run_id = str(meta.get("run_id") or "").strip()
    returncode = _safe_int_fn(meta.get("returncode"))
    log_path = str(meta.get("log_path") or "").strip()
    log_tail = _tail_text_fn(Path(log_path)) if log_path else ""

    suppression_reason = _suppression_reason_fn(
        mode=mode,
        reason=reason,
        log_path=log_path,
        log_tail=log_tail,
    )
    if suppression_reason:
        meta["error_capture_skipped_at"] = ts
        meta["error_capture_skipped_reason"] = suppression_reason
        meta.pop("error_capture_error", None)
        _write_json_fn(meta_path, meta)
        if year is not None and month is not None:
            _append_audit_event_fn(
                year=year,
                month=month,
                event_type="error_incident",
                action="capture",
                status="skipped",
                actor=meta.get("actor"),
                mode=mode,
                run_id=run_id,
                details={
                    "reason": reason,
                    "inferred_from": inferred_from,
                    "returncode": returncode if returncode is not None else -1,
                    "suppression_reason": suppression_reason,
                },
            )
        return

    script_path = _skill_root / "scripts" / "error_capture.py"
    if not script_path.exists():
        meta["error_capture_error"] = f"script_not_found: {script_path}"
        _write_json_fn(meta_path, meta)
        return

    message = (
        f"Run failed: mode={mode} reason={reason} "
        f"returncode={returncode if returncode is not None else -1}"
    )

    context_payload: dict[str, Any] = {
        "source": "dashboard_run_capture",
        "reason": reason,
        "inferred_from": inferred_from,
        "mode": mode,
        "run_id": run_id,
        "returncode": returncode if returncode is not None else -1,
    }
    cmd = [
        sys.executable,
        str(script_path),
        "--run-id",
        run_id,
        "--step",
        mode,
        "--failure-class",
        "run_failed",
        "--message",
        message,
        "--status",
        "new",
        "--context-json",
        _json_dumps(context_payload, ensure_ascii=False),
    ]
    if year is not None and month is not None:
        cmd += ["--year", str(year), "--month", str(month)]
        audit_path = _audit_log_path_fn(year, month)
        if audit_path.exists():
            cmd += ["--audit-path", str(audit_path)]
    if log_path:
        cmd += ["--log-path", log_path]

    try:
        res = _subprocess_fn.run(
            cmd,
            cwd=str(_skill_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except Exception as exc:
        meta["error_capture_error"] = f"capture_exception: {exc}"
        _write_json_fn(meta_path, meta)
        return

    if res.returncode != 0:
        stderr = str(res.stderr or "").strip()
        stdout = str(res.stdout or "").strip()
        message_text = stderr or stdout or f"exit={res.returncode}"
        meta["error_capture_error"] = f"capture_failed: {message_text[:500]}"
        _write_json_fn(meta_path, meta)
        return

    payload: dict[str, Any] = {}
    try:
        payload = _json_loads(str(res.stdout or "{}"))
    except Exception:
        payload = {}

    incident_id = str(payload.get("incident_id") or "").strip()
    if incident_id:
        meta["error_incident_id"] = incident_id
        meta.pop("error_capture_error", None)
    else:
        meta["error_capture_error"] = "capture_succeeded_but_incident_id_missing"
    _write_json_fn(meta_path, meta)

    if year is not None and month is not None:
        details = {
            "reason": reason,
            "inferred_from": inferred_from,
            "returncode": returncode if returncode is not None else -1,
            "incident_id": incident_id,
        }
        _append_audit_event_fn(
            year=year,
            month=month,
            event_type="error_incident",
            action="capture",
            status="success" if incident_id else "failed",
            actor=meta.get("actor"),
            mode=mode,
            run_id=run_id,
            details=details,
        )

from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import core_runs
from .core_shared import SKILL_ROOT, _read_json, _write_json

SCHEDULER_ALLOWED_MODES = {
    "preflight",
    "preflight_mf",
    "amazon_download",
    "rakuten_download",
    "amazon_print",
    "rakuten_print",
    "mf_reconcile",
}
CATCH_UP_POLICIES = {"run_on_startup", "skip"}
DEFAULT_RUN_TIME = "09:00"
SCHEDULER_POLL_SECONDS = 15
AUTOSTART_SCRIPT_NAME = "MF_Expense_Dashboard_Autostart.cmd"
SCHEDULE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SCHEDULE_TIME_RE = re.compile(r"^\d{2}:\d{2}$")

_state_lock = threading.Lock()
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()
_started_at = datetime.now()
_next_retry_at: datetime | None = None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _scheduler_root() -> Path:
    return core_runs._artifact_root() / "_scheduler"


def _state_path() -> Path:
    return _scheduler_root() / "scheduler_state.json"


def _default_state() -> dict[str, Any]:
    return {
        "enabled": False,
        "mode": "preflight",
        "year": None,
        "month": None,
        "mfcloud_url": "",
        "notes": "",
        "run_date": None,
        "run_time": DEFAULT_RUN_TIME,
        "catch_up_policy": "run_on_startup",
        "auth_handoff": False,
        "auto_receipt_name": True,
        "mf_draft_create": True,
        "auto_start_enabled": False,
        "updated_at": None,
        "last_evaluated_at": None,
        "last_result": None,
        "last_triggered_signature": "",
        "last_triggered_at": None,
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _normalize_mode(value: Any) -> str:
    mode = str(value or "").strip()
    if mode in SCHEDULER_ALLOWED_MODES:
        return mode
    return "preflight"


def _normalize_catch_up_policy(value: Any) -> str:
    policy = str(value or "").strip().lower()
    if policy in CATCH_UP_POLICIES:
        return policy
    return "run_on_startup"


def _normalize_run_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not SCHEDULE_DATE_RE.fullmatch(text):
        return None
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return text


def _normalize_run_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return DEFAULT_RUN_TIME
    if not SCHEDULE_TIME_RE.fullmatch(text):
        return DEFAULT_RUN_TIME
    hour = _as_int(text[:2])
    minute = _as_int(text[3:5])
    if hour is None or minute is None:
        return DEFAULT_RUN_TIME
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return DEFAULT_RUN_TIME
    return f"{hour:02d}:{minute:02d}"


def _normalize_text(value: Any, *, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def _startup_dir() -> Path:
    override = str(os.environ.get("AX_DASHBOARD_STARTUP_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    appdata = str(os.environ.get("APPDATA") or "").strip()
    if appdata:
        return Path(appdata).expanduser() / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return (
        Path.home()
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def _autostart_script_path() -> Path:
    return _startup_dir() / AUTOSTART_SCRIPT_NAME


def _autostart_supported() -> bool:
    return os.name == "nt" and (SKILL_ROOT / "scripts" / "start_dashboard.ps1").exists()


def _autostart_active() -> bool:
    return _autostart_script_path().exists()


def _set_autostart_enabled(enabled: bool) -> None:
    target = _autostart_script_path()
    if not enabled:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return

    if not _autostart_supported():
        raise HTTPException(status_code=409, detail="Autostart is supported only on Windows.")

    target.parent.mkdir(parents=True, exist_ok=True)
    script_path = (SKILL_ROOT / "scripts" / "start_dashboard.ps1").resolve()
    command = f'"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "{script_path}" -NoOpen'
    content = "@echo off\r\n" + command + "\r\n"
    target.write_text(content, encoding="utf-8")


def _normalize_state(payload: Any) -> dict[str, Any]:
    src = payload if isinstance(payload, dict) else {}
    out = _default_state()

    year = _as_int(src.get("year"))
    month = _as_int(src.get("month"))
    if year is not None:
        out["year"] = year
    if month is not None and 1 <= month <= 12:
        out["month"] = month

    out["enabled"] = bool(src.get("enabled"))
    out["mode"] = _normalize_mode(src.get("mode"))
    out["mfcloud_url"] = _normalize_text(src.get("mfcloud_url"), max_len=2000)
    out["notes"] = _normalize_text(src.get("notes"), max_len=2000)
    out["run_date"] = _normalize_run_date(src.get("run_date"))
    out["run_time"] = _normalize_run_time(src.get("run_time"))
    out["catch_up_policy"] = _normalize_catch_up_policy(src.get("catch_up_policy"))
    out["auth_handoff"] = bool(src.get("auth_handoff"))
    out["auto_receipt_name"] = bool(src.get("auto_receipt_name", True))
    out["mf_draft_create"] = bool(src.get("mf_draft_create", True))
    out["auto_start_enabled"] = bool(src.get("auto_start_enabled", False))
    out["updated_at"] = str(src.get("updated_at") or "").strip() or None
    out["last_evaluated_at"] = str(src.get("last_evaluated_at") or "").strip() or None

    last_result = src.get("last_result")
    out["last_result"] = last_result if isinstance(last_result, dict) else None
    out["last_triggered_signature"] = str(src.get("last_triggered_signature") or "").strip()
    out["last_triggered_at"] = str(src.get("last_triggered_at") or "").strip() or None
    return out


def _read_state_unlocked() -> dict[str, Any]:
    return _normalize_state(_read_json(_state_path()))


def _write_state_unlocked(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, _normalize_state(state))


def _scheduled_datetime(state: dict[str, Any]) -> datetime | None:
    run_date = _normalize_run_date(state.get("run_date"))
    run_time = _normalize_run_time(state.get("run_time"))
    if not run_date:
        return None
    try:
        return datetime.strptime(f"{run_date} {run_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _schedule_signature(state: dict[str, Any]) -> str:
    year = _as_int(state.get("year"))
    month = _as_int(state.get("month"))
    ym = f"{year:04d}-{month:02d}" if year is not None and month is not None and 1 <= month <= 12 else ""
    items = [
        str(state.get("mode") or ""),
        ym,
        str(state.get("run_date") or ""),
        str(state.get("run_time") or ""),
        "1" if bool(state.get("auth_handoff")) else "0",
        "1" if bool(state.get("auto_receipt_name")) else "0",
        "1" if bool(state.get("mf_draft_create")) else "0",
        str(state.get("mfcloud_url") or ""),
        str(state.get("notes") or ""),
    ]
    return "|".join(items)


def _build_run_payload(state: dict[str, Any]) -> dict[str, Any]:
    year = _as_int(state.get("year"))
    month = _as_int(state.get("month"))
    if year is None or month is None or month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Scheduler year/month is invalid.")
    payload = {
        "year": year,
        "month": month,
        "mode": _normalize_mode(state.get("mode")),
        "mfcloud_url": _normalize_text(state.get("mfcloud_url"), max_len=2000),
        "notes": _normalize_text(state.get("notes"), max_len=2000),
        "auth_handoff": bool(state.get("auth_handoff")),
        "auto_receipt_name": bool(state.get("auto_receipt_name", True)),
        "mf_draft_create": bool(state.get("mf_draft_create", True)),
    }
    if payload["mode"] == "mf_reconcile" and not payload["mfcloud_url"]:
        raise HTTPException(status_code=400, detail="Scheduler requires MF Cloud URL for mf_reconcile.")
    return payload


def _validate_enabled_state(state: dict[str, Any]) -> None:
    year = _as_int(state.get("year"))
    month = _as_int(state.get("month"))
    if year is None or month is None or month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Scheduler year/month is required.")
    if not _normalize_run_date(state.get("run_date")):
        raise HTTPException(status_code=400, detail="Scheduler run_date is required.")
    if not _scheduled_datetime(state):
        raise HTTPException(status_code=400, detail="Scheduler run_time is invalid.")
    _build_run_payload(state)


def _enrich_state(state: dict[str, Any]) -> dict[str, Any]:
    view = _normalize_state(state)
    scheduled = _scheduled_datetime(view)
    view["next_run_at"] = scheduled.isoformat(timespec="seconds") if scheduled else None
    view["autostart_supported"] = _autostart_supported()
    view["autostart_path"] = str(_autostart_script_path())
    view["auto_start_active"] = _autostart_active()
    return view


def evaluate_once() -> dict[str, Any]:
    global _next_retry_at
    now = datetime.now()
    with _state_lock:
        state = _read_state_unlocked()
        state["last_evaluated_at"] = now.isoformat(timespec="seconds")

        if not bool(state.get("enabled")):
            _write_state_unlocked(state)
            return _enrich_state(state)

        scheduled = _scheduled_datetime(state)
        if scheduled is None:
            state["enabled"] = False
            state["last_result"] = {
                "status": "failed",
                "at": _now_iso(),
                "detail": "Scheduler run_date/run_time is invalid.",
            }
            _write_state_unlocked(state)
            _next_retry_at = None
            return _enrich_state(state)

        signature = _schedule_signature(state)
        if signature and signature == str(state.get("last_triggered_signature") or ""):
            _write_state_unlocked(state)
            return _enrich_state(state)

        if now < scheduled:
            _write_state_unlocked(state)
            return _enrich_state(state)

        missed = scheduled < _started_at
        if missed and str(state.get("catch_up_policy")) == "skip":
            state["enabled"] = False
            state["last_triggered_signature"] = signature
            state["last_triggered_at"] = now.isoformat(timespec="seconds")
            state["last_result"] = {
                "status": "skipped_missed",
                "at": _now_iso(),
                "scheduled_for": scheduled.isoformat(timespec="seconds"),
            }
            _write_state_unlocked(state)
            _next_retry_at = None
            return _enrich_state(state)

        if _next_retry_at is not None and now < _next_retry_at:
            _write_state_unlocked(state)
            return _enrich_state(state)

        try:
            run_payload = _build_run_payload(state)
            run_result = core_runs._start_run(run_payload)
        except HTTPException as exc:
            detail = str(exc.detail)
            if exc.status_code == 409 and "already in progress" in detail.lower():
                _next_retry_at = now + timedelta(seconds=60)
                state["last_result"] = {
                    "status": "deferred",
                    "at": _now_iso(),
                    "detail": detail,
                    "scheduled_for": scheduled.isoformat(timespec="seconds"),
                }
            else:
                state["enabled"] = False
                state["last_triggered_signature"] = signature
                state["last_triggered_at"] = now.isoformat(timespec="seconds")
                state["last_result"] = {
                    "status": "failed",
                    "at": _now_iso(),
                    "code": int(exc.status_code),
                    "detail": detail,
                    "scheduled_for": scheduled.isoformat(timespec="seconds"),
                }
                _next_retry_at = None
            _write_state_unlocked(state)
            return _enrich_state(state)
        except Exception as exc:  # noqa: BLE001
            state["enabled"] = False
            state["last_triggered_signature"] = signature
            state["last_triggered_at"] = now.isoformat(timespec="seconds")
            state["last_result"] = {
                "status": "failed",
                "at": _now_iso(),
                "detail": str(exc),
                "scheduled_for": scheduled.isoformat(timespec="seconds"),
            }
            _write_state_unlocked(state)
            _next_retry_at = None
            return _enrich_state(state)

        state["enabled"] = False
        state["last_triggered_signature"] = signature
        state["last_triggered_at"] = now.isoformat(timespec="seconds")
        state["last_result"] = {
            "status": "started",
            "at": _now_iso(),
            "scheduled_for": scheduled.isoformat(timespec="seconds"),
            "run_id": str(run_result.get("run_id") or ""),
        }
        _write_state_unlocked(state)
        _next_retry_at = None
        return _enrich_state(state)


def get_state() -> dict[str, Any]:
    with _state_lock:
        return _enrich_state(_read_state_unlocked())


def update_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    keys = set(body.keys())
    mutable = {
        "enabled",
        "mode",
        "year",
        "month",
        "mfcloud_url",
        "notes",
        "run_date",
        "run_time",
        "catch_up_policy",
        "auth_handoff",
        "auto_receipt_name",
        "mf_draft_create",
        "auto_start_enabled",
    }
    unknown = sorted([k for k in keys if k not in mutable])
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported scheduler field: {unknown[0]}")

    with _state_lock:
        state = _read_state_unlocked()
        rearm = False

        if "enabled" in body:
            state["enabled"] = bool(body.get("enabled"))
            if state["enabled"]:
                rearm = True
        if "mode" in body:
            state["mode"] = _normalize_mode(body.get("mode"))
        if "year" in body:
            year = _as_int(body.get("year"))
            state["year"] = year
        if "month" in body:
            month = _as_int(body.get("month"))
            state["month"] = month if month is not None and 1 <= month <= 12 else None
        if "mfcloud_url" in body:
            state["mfcloud_url"] = _normalize_text(body.get("mfcloud_url"), max_len=2000)
        if "notes" in body:
            state["notes"] = _normalize_text(body.get("notes"), max_len=2000)
        if "run_date" in body:
            state["run_date"] = _normalize_run_date(body.get("run_date"))
        if "run_time" in body:
            state["run_time"] = _normalize_run_time(body.get("run_time"))
        if "catch_up_policy" in body:
            state["catch_up_policy"] = _normalize_catch_up_policy(body.get("catch_up_policy"))
        if "auth_handoff" in body:
            state["auth_handoff"] = bool(body.get("auth_handoff"))
        if "auto_receipt_name" in body:
            state["auto_receipt_name"] = bool(body.get("auto_receipt_name"))
        if "mf_draft_create" in body:
            state["mf_draft_create"] = bool(body.get("mf_draft_create"))
        if "auto_start_enabled" in body:
            auto_start_enabled = bool(body.get("auto_start_enabled"))
            _set_autostart_enabled(auto_start_enabled)
            state["auto_start_enabled"] = auto_start_enabled

        if rearm:
            state["last_result"] = None
            state["last_triggered_signature"] = ""
            state["last_triggered_at"] = None

        if bool(state.get("enabled")):
            _validate_enabled_state(state)

        state["updated_at"] = _now_iso()
        _write_state_unlocked(state)

    return evaluate_once()


def _worker_loop() -> None:
    while not _stop_event.wait(SCHEDULER_POLL_SECONDS):
        try:
            evaluate_once()
        except Exception:
            # Keep the worker alive even when evaluation fails.
            continue


def start_worker() -> None:
    global _worker_thread
    global _started_at
    global _next_retry_at
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _started_at = datetime.now()
        _next_retry_at = None
        _stop_event.clear()
        try:
            evaluate_once()
        except Exception:
            pass
        _worker_thread = threading.Thread(target=_worker_loop, name="dashboard-scheduler", daemon=True)
        _worker_thread.start()


def stop_worker() -> None:
    global _worker_thread
    with _worker_lock:
        _stop_event.set()
        if _worker_thread and _worker_thread.is_alive():
            _worker_thread.join(timeout=1.5)
        _worker_thread = None

from __future__ import annotations

import re
import threading
import calendar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import core_runs
from .core_shared import _read_json, _write_json

SCHEDULER_ALLOWED_ACTION_KEYS = {
    "preflight",
    "preflight_mf",
    "amazon_download",
    "rakuten_download",
    "amazon_print",
    "rakuten_print",
    "mf_reconcile",
}
CATCH_UP_POLICIES = {"run_on_startup", "skip"}
SCHEDULER_RECURRENCE = {"once", "daily", "weekly", "monthly"}
DEFAULT_RUN_TIME = "09:00"
DEFAULT_ACTION_KEY = "preflight"
SCHEDULER_POLL_SECONDS = 15
SCHEDULE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SCHEDULE_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_DEFAULT_TEMPLATE_ID = "__default__"
_TIMER_STATE_KEYS = {
    "enabled",
    "card_id",
    "action_key",
    "year",
    "month",
    "mfcloud_url",
    "notes",
    "run_date",
    "run_time",
    "catch_up_policy",
    "recurrence",
    "updated_at",
    "last_evaluated_at",
    "last_result",
    "last_triggered_signature",
    "last_triggered_at",
}
_TIMER_STATE_COPY_KEYS = {
    "card_id",
    "action_key",
    "year",
    "month",
    "mfcloud_url",
    "notes",
    "run_date",
    "run_time",
    "catch_up_policy",
    "recurrence",
}

_state_lock = threading.Lock()
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()
_started_at = datetime.now()
_next_retry_at_by_template: dict[str, datetime | None] = {}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _scheduler_root() -> Path:
    return core_runs._artifact_root() / "_scheduler"


def _state_path() -> Path:
    return _scheduler_root() / "scheduler_state.json"


def _default_state() -> dict[str, Any]:
    return {
        "enabled": False,
        "card_id": "",
        "action_key": DEFAULT_ACTION_KEY,
        "year": None,
        "month": None,
        "mfcloud_url": "",
        "notes": "",
        "run_date": None,
        "run_time": DEFAULT_RUN_TIME,
        "catch_up_policy": "run_on_startup",
        "recurrence": "once",
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


def _normalize_action_key(value: Any) -> str:
    action_key = str(value or "").strip()
    if action_key in SCHEDULER_ALLOWED_ACTION_KEYS:
        return action_key
    return DEFAULT_ACTION_KEY


def _normalize_catch_up_policy(value: Any) -> str:
    policy = str(value or "").strip().lower()
    if policy in CATCH_UP_POLICIES:
        return policy
    return "run_on_startup"


def _normalize_recurrence(value: Any) -> str:
    recurrence = str(value or "once").strip().lower()
    if recurrence in SCHEDULER_RECURRENCE:
        return recurrence
    return "once"


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


def _normalize_card_id(value: Any) -> str:
    return _normalize_text(value, max_len=128)


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
    out["card_id"] = _normalize_card_id(src.get("card_id"))
    out["action_key"] = _normalize_action_key(src.get("action_key"))
    out["mfcloud_url"] = _normalize_text(src.get("mfcloud_url"), max_len=2000)
    out["notes"] = _normalize_text(src.get("notes"), max_len=2000)
    out["run_date"] = _normalize_run_date(src.get("run_date"))
    out["run_time"] = _normalize_run_time(src.get("run_time"))
    out["catch_up_policy"] = _normalize_catch_up_policy(src.get("catch_up_policy"))
    out["recurrence"] = _normalize_recurrence(src.get("recurrence"))
    out["updated_at"] = str(src.get("updated_at") or "").strip() or None
    out["last_evaluated_at"] = str(src.get("last_evaluated_at") or "").strip() or None

    last_result = src.get("last_result")
    out["last_result"] = last_result if isinstance(last_result, dict) else None
    out["last_triggered_signature"] = str(src.get("last_triggered_signature") or "").strip()
    out["last_triggered_at"] = str(src.get("last_triggered_at") or "").strip() or None
    return out


def _read_state_unlocked() -> dict[str, Any]:
    raw = _read_json(_state_path())
    if not isinstance(raw, dict):
        return {"template_timers": {_DEFAULT_TEMPLATE_ID: _default_state()}}

    template_timers: dict[str, dict[str, Any]] = {}
    raw_timers = raw.get("template_timers")
    if isinstance(raw_timers, dict):
        for template_id, source_state in raw_timers.items():
            if not isinstance(template_id, str):
                continue
            template_id = template_id.strip()
            if not template_id:
                continue
            template_timers[template_id] = _normalize_state(source_state)

    legacy_state = _normalize_state({k: v for k, v in raw.items() if k != "template_timers" and k in _TIMER_STATE_KEYS})
    if legacy_state and not template_timers:
        template_timers[_DEFAULT_TEMPLATE_ID] = legacy_state
    elif _DEFAULT_TEMPLATE_ID not in template_timers and any(k in raw for k in _TIMER_STATE_KEYS):
        template_timers[_DEFAULT_TEMPLATE_ID] = legacy_state

    if not template_timers:
        template_timers[_DEFAULT_TEMPLATE_ID] = _default_state()
    return {"template_timers": template_timers}


def _write_state_unlocked(state: dict[str, Any]) -> None:
    raw_timers = state.get("template_timers") if isinstance(state, dict) else None
    timers: dict[str, dict[str, Any]] = {}
    if isinstance(raw_timers, dict):
        for template_id, source_state in raw_timers.items():
            if not isinstance(template_id, str):
                continue
            template_id = template_id.strip()
            if not template_id:
                continue
            timers[template_id] = _normalize_state(source_state)

    if not timers:
        timers[_DEFAULT_TEMPLATE_ID] = _default_state()
    default_state = timers.get(_DEFAULT_TEMPLATE_ID, _default_state())

    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(default_state)
    payload["template_timers"] = timers
    _write_json(path, payload)


def _normalize_template_id(template_id: Any) -> str:
    raw = str(template_id or "").strip()
    return raw or _DEFAULT_TEMPLATE_ID


def _build_copied_timer_state(source_state: dict[str, Any] | None) -> dict[str, Any]:
    source_state = _normalize_state(source_state)
    copied = _default_state()
    for key in _TIMER_STATE_COPY_KEYS:
        copied[key] = source_state.get(key)
    copied["enabled"] = False
    copied["updated_at"] = _now_iso()
    copied["last_evaluated_at"] = None
    copied["last_result"] = None
    copied["last_triggered_signature"] = ""
    copied["last_triggered_at"] = None
    return copied


def _get_template_timers(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_timers = state.get("template_timers")
    if not isinstance(raw_timers, dict):
        return {_DEFAULT_TEMPLATE_ID: _default_state()}
    timers: dict[str, dict[str, Any]] = {}
    for key, value in raw_timers.items():
        if not isinstance(key, str):
            continue
        template_id = key.strip()
        if not template_id:
            continue
        timers[template_id] = _normalize_state(value)
    if not timers:
        timers[_DEFAULT_TEMPLATE_ID] = _default_state()
    return timers


def _ensure_template_state_container(state: dict[str, Any], template_id: str) -> dict[str, Any]:
    normalized_id = _normalize_template_id(template_id)
    timers = _get_template_timers(state)
    if normalized_id not in timers:
        timers[normalized_id] = _default_state()
    state["template_timers"] = timers
    return timers[normalized_id]


def copy_timer_state(source_template_id: str | None, target_template_id: str | None) -> None:
    source_id = _normalize_template_id(source_template_id)
    target_id = _normalize_template_id(target_template_id)
    if target_id == source_id:
        return

    with _state_lock:
        state = _read_state_unlocked()
        timers = _get_template_timers(state)
        source_state = timers.get(source_id)
        copied = _build_copied_timer_state(source_state)
        timers[target_id] = copied
        _next_retry_at_by_template.pop(target_id, None)
        state["template_timers"] = timers
        _write_state_unlocked(state)


def delete_timer_state(template_id: str | None) -> None:
    normalized_id = _normalize_template_id(template_id)
    if normalized_id == _DEFAULT_TEMPLATE_ID:
        return

    with _state_lock:
        state = _read_state_unlocked()
        timers = _get_template_timers(state)
        if normalized_id not in timers:
            return
        timers.pop(normalized_id, None)
        state["template_timers"] = timers
        _next_retry_at_by_template.pop(normalized_id, None)
        _write_state_unlocked(state)


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
    action_key = _normalize_action_key(state.get("action_key"))
    card_id = _normalize_card_id(state.get("card_id"))
    items = [
        card_id,
        action_key,
        ym,
        str(state.get("run_date") or ""),
        str(state.get("run_time") or ""),
        str(state.get("recurrence") or "once"),
        str(state.get("mfcloud_url") or ""),
        str(state.get("notes") or ""),
    ]
    return "|".join(items)


def _scheduled_month_from_state(state: dict[str, Any], scheduled: datetime | None = None) -> tuple[int, int]:
    if scheduled is None:
        year = _as_int(state.get("year"))
        month = _as_int(state.get("month"))
    else:
        year = scheduled.year
        month = scheduled.month
    if year is None or month is None or month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Scheduler year/month is invalid.")
    return year, month


def _build_run_payload(state: dict[str, Any], *, scheduled: datetime | None = None) -> dict[str, Any]:
    year, month = _scheduled_month_from_state(state, scheduled=scheduled)
    action_key = _normalize_action_key(state.get("action_key"))
    card_id = _normalize_card_id(state.get("card_id"))
    payload = {
        "year": year,
        "month": month,
        "mode": action_key,
        "mfcloud_url": _normalize_text(state.get("mfcloud_url"), max_len=2000),
        "notes": _normalize_text(state.get("notes"), max_len=2000),
        # Scheduler runs are unattended by default.
        "auth_handoff": False,
        "auto_receipt_name": True,
        "mf_draft_create": True,
        "_scheduler_card_id": card_id,
        "_scheduler_action_key": action_key,
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


def _is_repeating(state: dict[str, Any]) -> bool:
    return _normalize_recurrence(state.get("recurrence")) != "once"


def _next_recurrence_datetime(scheduled: datetime, recurrence: str) -> datetime:
    normalized = _normalize_recurrence(recurrence)
    if normalized == "daily":
        return scheduled + timedelta(days=1)
    if normalized == "weekly":
        return scheduled + timedelta(weeks=1)
    if normalized == "monthly":
        year = scheduled.year
        month = scheduled.month + 1
        if month > 12:
            year += 1
            month = 1
        max_day = calendar.monthrange(year, month)[1]
        day = min(scheduled.day, max_day)
        return scheduled.replace(year=year, month=month, day=day)
    return scheduled


def _align_state_for_repetition(state: dict[str, Any], scheduled: datetime) -> None:
    next_scheduled = _next_recurrence_datetime(scheduled, _normalize_recurrence(state.get("recurrence")))
    state["enabled"] = True
    state["year"] = next_scheduled.year
    state["month"] = next_scheduled.month
    state["run_date"] = next_scheduled.strftime("%Y-%m-%d")
    state["run_time"] = next_scheduled.strftime("%H:%M")


def _enrich_state(
    state: dict[str, Any], *, template_id: str | None = None, template_timers_count: int | None = None
) -> dict[str, Any]:
    view = _normalize_state(state)
    scheduled = _scheduled_datetime(view)
    view["next_run_at"] = scheduled.isoformat(timespec="seconds") if scheduled else None
    if template_id is not None:
        view["template_id"] = _normalize_template_id(template_id)
    if template_timers_count is not None:
        view["template_timers_count"] = template_timers_count
    return view


def _evaluate_single_timer(timer_state: dict[str, Any], template_id: str, now: datetime) -> None:
    next_retry_at = _next_retry_at_by_template.get(template_id)
    if not bool(timer_state.get("enabled")):
        timer_state["last_evaluated_at"] = now.isoformat(timespec="seconds")
        _next_retry_at_by_template.pop(template_id, None)
        return

    timer_state["last_evaluated_at"] = now.isoformat(timespec="seconds")

    scheduled = _scheduled_datetime(timer_state)
    if scheduled is None:
        timer_state["enabled"] = False
        timer_state["last_result"] = {
            "status": "failed",
            "at": _now_iso(),
            "detail": "Scheduler run_date/run_time is invalid.",
        }
        _next_retry_at_by_template.pop(template_id, None)
        return

    signature = _schedule_signature(timer_state)
    if signature and signature == str(timer_state.get("last_triggered_signature") or ""):
        _next_retry_at_by_template.pop(template_id, None)
        return

    if now < scheduled:
        _next_retry_at_by_template.pop(template_id, None)
        return

    missed = scheduled < _started_at
    if missed and str(timer_state.get("catch_up_policy")) == "skip":
        if _is_repeating(timer_state):
            _align_state_for_repetition(timer_state, scheduled)
        else:
            timer_state["enabled"] = False
        timer_state["last_triggered_signature"] = signature
        timer_state["last_triggered_at"] = now.isoformat(timespec="seconds")
        timer_state["last_result"] = {
            "status": "skipped_missed",
            "at": _now_iso(),
            "scheduled_for": scheduled.isoformat(timespec="seconds"),
        }
        _next_retry_at_by_template.pop(template_id, None)
        return

    if next_retry_at is not None and now < next_retry_at:
        return

    try:
        run_payload = _build_run_payload(timer_state, scheduled=scheduled)
        run_result = core_runs._start_run(run_payload)
    except HTTPException as exc:
        detail = str(exc.detail)
        if exc.status_code == 409 and "already in progress" in detail.lower():
            _next_retry_at_by_template[template_id] = now + timedelta(seconds=60)
            timer_state["last_result"] = {
                "status": "deferred",
                "at": _now_iso(),
                "detail": detail,
                "scheduled_for": scheduled.isoformat(timespec="seconds"),
            }
        else:
            timer_state["enabled"] = False
            timer_state["last_triggered_signature"] = signature
            timer_state["last_triggered_at"] = now.isoformat(timespec="seconds")
            timer_state["last_result"] = {
                "status": "failed",
                "at": _now_iso(),
                "code": int(exc.status_code),
                "detail": detail,
                "scheduled_for": scheduled.isoformat(timespec="seconds"),
            }
            _next_retry_at_by_template.pop(template_id, None)
        return
    except Exception as exc:  # noqa: BLE001
        timer_state["enabled"] = False
        timer_state["last_triggered_signature"] = signature
        timer_state["last_triggered_at"] = now.isoformat(timespec="seconds")
        timer_state["last_result"] = {
            "status": "failed",
            "at": _now_iso(),
            "detail": str(exc),
            "scheduled_for": scheduled.isoformat(timespec="seconds"),
        }
        _next_retry_at_by_template.pop(template_id, None)
        return

    if _is_repeating(timer_state):
        _align_state_for_repetition(timer_state, scheduled)
    else:
        timer_state["enabled"] = False
    timer_state["last_triggered_signature"] = signature
    timer_state["last_triggered_at"] = now.isoformat(timespec="seconds")
    timer_state["last_result"] = {
        "status": "started",
        "at": _now_iso(),
        "scheduled_for": scheduled.isoformat(timespec="seconds"),
        "run_id": str(run_result.get("run_id") or ""),
    }
    _next_retry_at_by_template.pop(template_id, None)


def evaluate_once(template_id: str | None = None) -> dict[str, Any]:
    now = datetime.now()
    with _state_lock:
        state = _read_state_unlocked()
        timers = _get_template_timers(state)
        if template_id is None:
            ids = list(timers.keys())
            for template_key in ids:
                _evaluate_single_timer(timers[template_key], template_key, now)
            default_template_id = _DEFAULT_TEMPLATE_ID if _DEFAULT_TEMPLATE_ID in timers else (ids[0] if ids else _DEFAULT_TEMPLATE_ID)
            default_state = timers.get(default_template_id, _default_state())
            _write_state_unlocked({"template_timers": timers})
            return _enrich_state(
                default_state,
                template_id=default_template_id,
                template_timers_count=len(timers),
            )

        template_key = _normalize_template_id(template_id)
        timer_state = _ensure_template_state_container(state, template_key)
        _evaluate_single_timer(timer_state, template_key, now)
        _write_state_unlocked(state)
        return _enrich_state(
            timer_state,
            template_id=template_key,
            template_timers_count=len(_get_template_timers(state)),
        )


def get_state(template_id: str | None = None) -> dict[str, Any]:
    with _state_lock:
        state = _read_state_unlocked()
        template_key = _normalize_template_id(template_id)
        timer_state = _ensure_template_state_container(state, template_key)
        return _enrich_state(
            timer_state,
            template_id=template_key,
            template_timers_count=len(_get_template_timers(state)),
        )


def update_state(payload: dict[str, Any] | None, template_id: str | None = None) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    keys = set(body.keys())
    mutable = {
        "enabled",
        "card_id",
        "action_key",
        "year",
        "month",
        "mfcloud_url",
        "notes",
        "run_date",
        "run_time",
        "catch_up_policy",
        "recurrence",
    }
    unknown = sorted([k for k in keys if k not in mutable])
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported scheduler field: {unknown[0]}")

    with _state_lock:
        state = _read_state_unlocked()
        timer_state = _ensure_template_state_container(state, template_id)
        rearm = False

        if "enabled" in body:
            timer_state["enabled"] = bool(body.get("enabled"))
            if timer_state["enabled"]:
                rearm = True
        if "card_id" in body:
            timer_state["card_id"] = _normalize_card_id(body.get("card_id"))
        if "action_key" in body:
            timer_state["action_key"] = _normalize_action_key(body.get("action_key"))
        if "year" in body:
            year = _as_int(body.get("year"))
            timer_state["year"] = year
        if "month" in body:
            month = _as_int(body.get("month"))
            timer_state["month"] = month if month is not None and 1 <= month <= 12 else None
        if "mfcloud_url" in body:
            timer_state["mfcloud_url"] = _normalize_text(body.get("mfcloud_url"), max_len=2000)
        if "notes" in body:
            timer_state["notes"] = _normalize_text(body.get("notes"), max_len=2000)
        if "run_date" in body:
            timer_state["run_date"] = _normalize_run_date(body.get("run_date"))
        if "run_time" in body:
            timer_state["run_time"] = _normalize_run_time(body.get("run_time"))
        if "catch_up_policy" in body:
            timer_state["catch_up_policy"] = _normalize_catch_up_policy(body.get("catch_up_policy"))
        if "recurrence" in body:
            timer_state["recurrence"] = _normalize_recurrence(body.get("recurrence"))

        if rearm:
            timer_state["last_result"] = None
            timer_state["last_triggered_signature"] = ""
            timer_state["last_triggered_at"] = None

        if bool(timer_state.get("enabled")):
            _validate_enabled_state(timer_state)

        timer_state["updated_at"] = _now_iso()
        state["template_timers"][_normalize_template_id(template_id)] = timer_state
        _write_state_unlocked(state)

    return evaluate_once(template_id)


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
    global _next_retry_at_by_template
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _started_at = datetime.now()
        _next_retry_at_by_template = {}
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

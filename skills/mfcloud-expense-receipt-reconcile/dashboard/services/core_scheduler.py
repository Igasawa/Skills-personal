from __future__ import annotations

import json
import re
import threading
import calendar
import os
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
ONCE_RECEIPT_MAX_ITEMS = 5000
TRIGGER_LOCK_STALE_SECONDS = 6 * 60 * 60
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
    "monthly_anchor_day",
    "catch_up_policy",
    "recurrence",
    "updated_at",
    "last_evaluated_at",
    "last_result",
    "last_triggered_signature",
    "last_triggered_at",
    "failure_retry_signature",
    "failure_retry_attempts",
    "failure_retry_next_at",
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
    "monthly_anchor_day",
    "catch_up_policy",
    "recurrence",
}
_ONCE_RECEIPT_KEYS = {
    "template_id",
    "run_date",
    "run_time",
    "run_id",
    "status",
    "triggered_at",
}

_state_lock = threading.Lock()
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()
_started_at = datetime.now()
_next_retry_at_by_template: dict[str, datetime | None] = {}


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except Exception:
        return default
    if value < minimum:
        return default
    return value


SCHEDULER_POLL_SECONDS = _env_int("AX_SCHEDULER_POLL_SECONDS", 15, minimum=1)
SCHEDULER_FAILURE_RETRY_SECONDS = _env_int("AX_SCHEDULER_FAILURE_RETRY_SECONDS", 60, minimum=1)
SCHEDULER_FAILURE_RETRY_MAX_ATTEMPTS = _env_int("AX_SCHEDULER_FAILURE_RETRY_MAX_ATTEMPTS", 1, minimum=1)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _scheduler_root() -> Path:
    return core_runs._artifact_root() / "_scheduler"


def _state_path() -> Path:
    return _scheduler_root() / "scheduler_state.json"


def _trigger_lock_dir() -> Path:
    return _scheduler_root() / "trigger_locks"


def _trigger_lock_path(template_id: Any) -> Path:
    normalized = _normalize_template_id(template_id)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", normalized).strip("._-")
    if not safe_name:
        safe_name = "default"
    if len(safe_name) > 180:
        safe_name = safe_name[:180]
    return _trigger_lock_dir() / f"{safe_name}.json"


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
        "monthly_anchor_day": None,
        "catch_up_policy": "run_on_startup",
        "recurrence": "once",
        "updated_at": None,
        "last_evaluated_at": None,
        "last_result": None,
        "last_triggered_signature": "",
        "last_triggered_at": None,
        "failure_retry_signature": "",
        "failure_retry_attempts": 0,
        "failure_retry_next_at": None,
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


def _day_from_run_date(value: Any) -> int | None:
    normalized = _normalize_run_date(value)
    if not normalized:
        return None
    day = _as_int(normalized[-2:])
    if day is None or day < 1 or day > 31:
        return None
    return day


def _normalize_monthly_anchor_day(value: Any, *, fallback_run_date: Any = None) -> int | None:
    day = _as_int(value)
    if day is None:
        day = _day_from_run_date(fallback_run_date)
    if day is None:
        return None
    if day < 1 or day > 31:
        return None
    return day


def _normalize_text(value: Any, *, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def _normalize_card_id(value: Any) -> str:
    return _normalize_text(value, max_len=128)


def _validate_action_key_input(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return DEFAULT_ACTION_KEY
    if text not in SCHEDULER_ALLOWED_ACTION_KEYS:
        raise HTTPException(status_code=400, detail="Scheduler action_key is invalid.")
    return text


def _validate_catch_up_policy_input(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "run_on_startup"
    if text not in CATCH_UP_POLICIES:
        raise HTTPException(status_code=400, detail="Scheduler catch_up_policy is invalid.")
    return text


def _validate_recurrence_input(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "once"
    if text not in SCHEDULER_RECURRENCE:
        raise HTTPException(status_code=400, detail="Scheduler recurrence is invalid.")
    return text


def _validate_run_date_input(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = _normalize_run_date(text)
    if not normalized:
        raise HTTPException(status_code=400, detail="Scheduler run_date is invalid.")
    return normalized


def _validate_run_time_input(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return DEFAULT_RUN_TIME
    normalized = _normalize_run_time(text)
    hour = _as_int(text[:2]) if len(text) >= 2 else None
    minute = _as_int(text[3:5]) if len(text) >= 5 else None
    if not SCHEDULE_TIME_RE.fullmatch(text) or hour is None or minute is None:
        raise HTTPException(status_code=400, detail="Scheduler run_time is invalid.")
    if normalized != text:
        raise HTTPException(status_code=400, detail="Scheduler run_time is invalid.")
    return normalized


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
    out["monthly_anchor_day"] = _normalize_monthly_anchor_day(
        src.get("monthly_anchor_day"),
        fallback_run_date=out["run_date"],
    )
    out["catch_up_policy"] = _normalize_catch_up_policy(src.get("catch_up_policy"))
    out["recurrence"] = _normalize_recurrence(src.get("recurrence"))
    out["updated_at"] = str(src.get("updated_at") or "").strip() or None
    out["last_evaluated_at"] = str(src.get("last_evaluated_at") or "").strip() or None

    last_result = src.get("last_result")
    out["last_result"] = last_result if isinstance(last_result, dict) else None
    out["last_triggered_signature"] = str(src.get("last_triggered_signature") or "").strip()
    out["last_triggered_at"] = str(src.get("last_triggered_at") or "").strip() or None
    out["failure_retry_signature"] = str(src.get("failure_retry_signature") or "").strip()
    retry_attempts = _as_int(src.get("failure_retry_attempts"))
    out["failure_retry_attempts"] = retry_attempts if retry_attempts is not None and retry_attempts >= 0 else 0
    out["failure_retry_next_at"] = str(src.get("failure_retry_next_at") or "").strip() or None
    return out


def _read_state_unlocked() -> dict[str, Any]:
    raw = _read_json(_state_path())
    if not isinstance(raw, dict):
        return {
            "template_timers": {_DEFAULT_TEMPLATE_ID: _default_state()},
            "once_trigger_receipts": {},
        }

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
    return {
        "template_timers": template_timers,
        "once_trigger_receipts": _get_once_receipts(raw),
    }


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
    payload["once_trigger_receipts"] = _get_once_receipts(state)
    _write_json(path, payload)


def _normalize_template_id(template_id: Any) -> str:
    raw = str(template_id or "").strip()
    return raw or _DEFAULT_TEMPLATE_ID


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is not None:
        try:
            parsed = parsed.astimezone().replace(tzinfo=None)
        except Exception:
            return None
    return parsed


def _is_trigger_lock_stale(path: Path, payload: dict[str, Any], *, now: datetime) -> bool:
    acquired_at = _parse_datetime(payload.get("acquired_at"))
    if acquired_at is None:
        try:
            acquired_at = datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            return True
    age_seconds = (now - acquired_at).total_seconds()
    return age_seconds >= TRIGGER_LOCK_STALE_SECONDS


def _acquire_trigger_lock(
    *,
    template_id: str,
    signature: str,
    scheduled: datetime,
    now: datetime,
) -> tuple[str, str]:
    path = _trigger_lock_path(template_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = f"{now.isoformat(timespec='seconds')}|{threading.get_ident()}"
    payload = {
        "template_id": _normalize_template_id(template_id),
        "signature": str(signature or "").strip(),
        "scheduled_for": scheduled.isoformat(timespec="seconds"),
        "acquired_at": now.isoformat(timespec="seconds"),
        "token": token,
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    for _ in range(2):
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(serialized)
            return token, ""
        except FileExistsError:
            existing = _read_json(path)
            if isinstance(existing, dict) and _is_trigger_lock_stale(path, existing, now=now):
                try:
                    path.unlink()
                except Exception:
                    return "", "template_lock_active"
                continue
            return "", "template_lock_active"
        except Exception:
            return "", "template_lock_error"

    return "", "template_lock_active"


def _release_trigger_lock(*, template_id: str, token: str) -> None:
    lock_token = str(token or "").strip()
    if not lock_token:
        return
    path = _trigger_lock_path(template_id)
    if not path.exists():
        return
    payload = _read_json(path)
    if isinstance(payload, dict):
        existing = str(payload.get("token") or "").strip()
        if existing and existing != lock_token:
            return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception:
        return


def _trigger_lock_rows(now: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lock_dir = _trigger_lock_dir()
    if not lock_dir.exists():
        return rows
    try:
        paths = sorted(lock_dir.glob("*.json"))
    except Exception:
        return rows
    for path in paths:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        stale = _is_trigger_lock_stale(path, payload, now=now)
        rows.append(
            {
                "template_id": _normalize_template_id(payload.get("template_id")),
                "signature": str(payload.get("signature") or "").strip(),
                "scheduled_for": str(payload.get("scheduled_for") or "").strip(),
                "acquired_at": str(payload.get("acquired_at") or "").strip(),
                "stale": bool(stale),
            }
        )
    return rows


def _once_receipt_key(template_id: str, run_date: Any, run_time: Any) -> str:
    normalized_template_id = _normalize_template_id(template_id)
    normalized_run_date = _normalize_run_date(run_date)
    normalized_run_time = _normalize_run_time(run_time)
    if not normalized_run_date:
        return ""
    return f"{normalized_template_id}|{normalized_run_date}|{normalized_run_time}"


def _normalize_once_receipt(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    out = {key: None for key in _ONCE_RECEIPT_KEYS}
    out["template_id"] = _normalize_template_id(row.get("template_id"))
    out["run_date"] = _normalize_run_date(row.get("run_date"))
    out["run_time"] = _normalize_run_time(row.get("run_time"))
    out["run_id"] = str(row.get("run_id") or "").strip()
    status = str(row.get("status") or "").strip().lower()
    out["status"] = status or "started"
    out["triggered_at"] = str(row.get("triggered_at") or "").strip() or None
    return out


def _get_once_receipts(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = state.get("once_trigger_receipts") if isinstance(state, dict) else {}
    receipts: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return receipts
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        receipt_key = key.strip()
        if not receipt_key:
            continue
        normalized = _normalize_once_receipt(value)
        if not normalized.get("run_date"):
            continue
        if not normalized.get("template_id"):
            continue
        receipts[receipt_key] = normalized
        if len(receipts) >= ONCE_RECEIPT_MAX_ITEMS:
            break
    return receipts


def _record_once_receipt(
    once_receipts: dict[str, dict[str, Any]],
    *,
    template_id: str,
    run_date: Any,
    run_time: Any,
    run_id: str = "",
    status: str = "started",
) -> str:
    receipt_key = _once_receipt_key(template_id, run_date, run_time)
    if not receipt_key:
        return ""
    once_receipts[receipt_key] = {
        "template_id": _normalize_template_id(template_id),
        "run_date": _normalize_run_date(run_date),
        "run_time": _normalize_run_time(run_time),
        "run_id": str(run_id or "").strip(),
        "status": str(status or "started").strip().lower() or "started",
        "triggered_at": _now_iso(),
    }
    if len(once_receipts) > ONCE_RECEIPT_MAX_ITEMS:
        drop = len(once_receipts) - ONCE_RECEIPT_MAX_ITEMS
        for stale_key in sorted(once_receipts.keys())[:drop]:
            once_receipts.pop(stale_key, None)
    return receipt_key


def _purge_once_receipts_for_template(once_receipts: dict[str, dict[str, Any]], template_id: str) -> None:
    normalized_template_id = _normalize_template_id(template_id)
    prefix = f"{normalized_template_id}|"
    for key in list(once_receipts.keys()):
        if key.startswith(prefix):
            once_receipts.pop(key, None)


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
        once_receipts = _get_once_receipts(state)
        _purge_once_receipts_for_template(once_receipts, normalized_id)
        state["once_trigger_receipts"] = once_receipts
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


def _next_recurrence_datetime(scheduled: datetime, recurrence: str, *, monthly_anchor_day: int | None = None) -> datetime:
    normalized = _normalize_recurrence(recurrence)
    if normalized == "daily":
        return scheduled + timedelta(days=1)
    if normalized == "weekly":
        return scheduled + timedelta(weeks=1)
    if normalized == "monthly":
        anchor_day = _normalize_monthly_anchor_day(monthly_anchor_day, fallback_run_date=scheduled.strftime("%Y-%m-%d"))
        if anchor_day is None:
            anchor_day = scheduled.day
        year = scheduled.year
        month = scheduled.month + 1
        if month > 12:
            year += 1
            month = 1
        max_day = calendar.monthrange(year, month)[1]
        day = min(anchor_day, max_day)
        return scheduled.replace(year=year, month=month, day=day)
    return scheduled


def _align_state_for_repetition(
    state: dict[str, Any],
    scheduled: datetime,
    *,
    reference: datetime | None = None,
) -> None:
    recurrence = _normalize_recurrence(state.get("recurrence"))
    monthly_anchor_day = None
    if recurrence == "monthly":
        monthly_anchor_day = _normalize_monthly_anchor_day(
            state.get("monthly_anchor_day"),
            fallback_run_date=state.get("run_date"),
        )
        if monthly_anchor_day is None:
            monthly_anchor_day = scheduled.day
        state["monthly_anchor_day"] = monthly_anchor_day

    next_scheduled = _next_recurrence_datetime(
        scheduled,
        recurrence,
        monthly_anchor_day=monthly_anchor_day,
    )
    if reference is not None:
        guard = 0
        while next_scheduled <= reference:
            guard += 1
            # Guard against malformed recurrence progression.
            if guard > 5000:
                break
            advanced = _next_recurrence_datetime(
                next_scheduled,
                recurrence,
                monthly_anchor_day=monthly_anchor_day,
            )
            if advanced <= next_scheduled:
                break
            next_scheduled = advanced
    state["enabled"] = True
    state["year"] = next_scheduled.year
    state["month"] = next_scheduled.month
    state["run_date"] = next_scheduled.strftime("%Y-%m-%d")
    state["run_time"] = next_scheduled.strftime("%H:%M")


def _enrich_state(
    state: dict[str, Any], *, template_id: str | None = None, template_timers_count: int | None = None
) -> dict[str, Any]:
    view = _normalize_state(state)
    view.pop("monthly_anchor_day", None)
    view.pop("failure_retry_signature", None)
    view.pop("failure_retry_attempts", None)
    view.pop("failure_retry_next_at", None)
    scheduled = _scheduled_datetime(view)
    view["next_run_at"] = scheduled.isoformat(timespec="seconds") if scheduled else None
    if template_id is not None:
        view["template_id"] = _normalize_template_id(template_id)
    if template_timers_count is not None:
        view["template_timers_count"] = template_timers_count
    return view


def _append_scheduler_audit_event(
    *,
    timer_state: dict[str, Any],
    template_id: str,
    status: str,
    scheduled: datetime | None = None,
    detail: str = "",
    run_id: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        year, month = _scheduled_month_from_state(timer_state, scheduled=scheduled)
    except Exception:
        return
    action = _normalize_action_key(timer_state.get("action_key"))
    details = {
        "template_id": _normalize_template_id(template_id),
        "recurrence": _normalize_recurrence(timer_state.get("recurrence")),
    }
    if scheduled is not None:
        details["scheduled_for"] = scheduled.isoformat(timespec="seconds")
    if detail:
        details["reason"] = detail
    if extra and isinstance(extra, dict):
        details.update(extra)
    try:
        core_runs._append_audit_event(
            year=year,
            month=month,
            event_type="scheduler",
            action=action,
            status=str(status or "unknown").strip() or "unknown",
            actor={"type": "system", "id": "scheduler"},
            mode=action,
            run_id=str(run_id or "").strip() or None,
            details=details,
        )
    except Exception:
        return


def _set_last_result(
    timer_state: dict[str, Any],
    *,
    status: str,
    scheduled: datetime | None = None,
    detail: str = "",
    run_id: str = "",
    code: int | None = None,
    reason_code: str = "",
) -> None:
    result: dict[str, Any] = {
        "status": str(status or "").strip() or "unknown",
        "at": _now_iso(),
    }
    if scheduled is not None:
        result["scheduled_for"] = scheduled.isoformat(timespec="seconds")
    if detail:
        result["detail"] = detail
    if run_id:
        result["run_id"] = str(run_id or "").strip()
    if code is not None:
        result["code"] = int(code)
    if reason_code:
        result["reason_code"] = str(reason_code).strip().lower()
    timer_state["last_result"] = result


def _clear_failure_retry_state(timer_state: dict[str, Any]) -> None:
    timer_state["failure_retry_signature"] = ""
    timer_state["failure_retry_attempts"] = 0
    timer_state["failure_retry_next_at"] = None


def _schedule_failure_retry(
    timer_state: dict[str, Any],
    *,
    template_id: str,
    signature: str,
    now: datetime,
    scheduled: datetime,
    detail: str,
) -> bool:
    current_signature = str(timer_state.get("failure_retry_signature") or "").strip()
    attempts = _as_int(timer_state.get("failure_retry_attempts")) or 0
    if current_signature != signature:
        current_signature = ""
        attempts = 0

    if attempts >= SCHEDULER_FAILURE_RETRY_MAX_ATTEMPTS:
        _clear_failure_retry_state(timer_state)
        return False

    retry_attempt = attempts + 1
    retry_at = now + timedelta(seconds=SCHEDULER_FAILURE_RETRY_SECONDS)
    timer_state["failure_retry_signature"] = signature
    timer_state["failure_retry_attempts"] = retry_attempt
    timer_state["failure_retry_next_at"] = retry_at.isoformat(timespec="seconds")
    _set_last_result(
        timer_state,
        status="deferred",
        scheduled=scheduled,
        detail=detail,
        reason_code="retry_scheduled",
    )
    _append_scheduler_audit_event(
        timer_state=timer_state,
        template_id=template_id,
        status="deferred",
        scheduled=scheduled,
        detail="retry_scheduled",
        extra={
            "retry_attempt": retry_attempt,
            "retry_at": retry_at.isoformat(timespec="seconds"),
        },
    )
    return True


def _evaluate_single_timer(
    timer_state: dict[str, Any],
    template_id: str,
    now: datetime,
    *,
    once_receipts: dict[str, dict[str, Any]],
) -> None:
    next_retry_at = _next_retry_at_by_template.get(template_id)
    if not bool(timer_state.get("enabled")):
        timer_state["last_evaluated_at"] = now.isoformat(timespec="seconds")
        _clear_failure_retry_state(timer_state)
        _next_retry_at_by_template.pop(template_id, None)
        return

    timer_state["last_evaluated_at"] = now.isoformat(timespec="seconds")

    scheduled = _scheduled_datetime(timer_state)
    if scheduled is None:
        timer_state["enabled"] = False
        _clear_failure_retry_state(timer_state)
        _set_last_result(
            timer_state,
            status="failed",
            detail="Scheduler run_date/run_time is invalid.",
            reason_code="invalid_schedule",
        )
        _append_scheduler_audit_event(
            timer_state=timer_state,
            template_id=template_id,
            status="failed",
            detail="Scheduler run_date/run_time is invalid.",
        )
        _next_retry_at_by_template.pop(template_id, None)
        return

    signature = _schedule_signature(timer_state)
    retry_signature = str(timer_state.get("failure_retry_signature") or "").strip()
    retry_attempts = _as_int(timer_state.get("failure_retry_attempts")) or 0
    retry_next_at = _parse_datetime(timer_state.get("failure_retry_next_at"))
    if retry_signature and retry_signature != signature:
        _clear_failure_retry_state(timer_state)
        retry_signature = ""
        retry_attempts = 0
        retry_next_at = None
    has_failure_retry = bool(retry_signature and retry_signature == signature and retry_attempts > 0)

    is_repeating = _is_repeating(timer_state)
    once_receipt_key = ""
    if not is_repeating:
        once_receipt_key = _once_receipt_key(template_id, timer_state.get("run_date"), timer_state.get("run_time"))
        existing_receipt = once_receipts.get(once_receipt_key)
        if existing_receipt:
            timer_state["enabled"] = False
            timer_state["last_triggered_signature"] = signature
            timer_state["last_triggered_at"] = (
                str(existing_receipt.get("triggered_at") or "").strip() or now.isoformat(timespec="seconds")
            )
            _clear_failure_retry_state(timer_state)
            _set_last_result(
                timer_state,
                status="skipped_duplicate",
                scheduled=scheduled,
                run_id=str(existing_receipt.get("run_id") or "").strip(),
                reason_code="duplicate_once_schedule",
            )
            _append_scheduler_audit_event(
                timer_state=timer_state,
                template_id=template_id,
                status="skipped",
                scheduled=scheduled,
                run_id=str(existing_receipt.get("run_id") or "").strip(),
                detail="duplicate_once_schedule",
                extra={"idempotency_key": once_receipt_key},
            )
            _next_retry_at_by_template.pop(template_id, None)
            return

    if signature and signature == str(timer_state.get("last_triggered_signature") or ""):
        _next_retry_at_by_template.pop(template_id, None)
        return

    if now < scheduled:
        _next_retry_at_by_template.pop(template_id, None)
        return

    if has_failure_retry and retry_next_at is not None and now < retry_next_at:
        return

    missed = scheduled < _started_at
    if missed and str(timer_state.get("catch_up_policy")) == "skip":
        if is_repeating:
            _align_state_for_repetition(timer_state, scheduled, reference=now)
        else:
            timer_state["enabled"] = False
        timer_state["last_triggered_signature"] = signature
        timer_state["last_triggered_at"] = now.isoformat(timespec="seconds")
        _clear_failure_retry_state(timer_state)
        _set_last_result(
            timer_state,
            status="skipped_missed",
            scheduled=scheduled,
            reason_code="skipped_missed",
        )
        if once_receipt_key:
            _record_once_receipt(
                once_receipts,
                template_id=template_id,
                run_date=timer_state.get("run_date"),
                run_time=timer_state.get("run_time"),
                run_id="",
                status="skipped_missed",
            )
        _append_scheduler_audit_event(
            timer_state=timer_state,
            template_id=template_id,
            status="skipped",
            scheduled=scheduled,
            detail="skipped_missed",
            extra={"idempotency_key": once_receipt_key} if once_receipt_key else None,
        )
        _next_retry_at_by_template.pop(template_id, None)
        return

    if next_retry_at is not None and now < next_retry_at:
        return

    lock_token, lock_error = _acquire_trigger_lock(
        template_id=template_id,
        signature=signature,
        scheduled=scheduled,
        now=now,
    )
    if not lock_token:
        _next_retry_at_by_template[template_id] = now + timedelta(seconds=60)
        reason = str(lock_error or "template_lock_active").strip().lower() or "template_lock_active"
        _set_last_result(
            timer_state,
            status="deferred",
            scheduled=scheduled,
            detail="Scheduler trigger is locked by another worker.",
            reason_code=reason,
        )
        _append_scheduler_audit_event(
            timer_state=timer_state,
            template_id=template_id,
            status="deferred",
            scheduled=scheduled,
            detail=reason,
        )
        return

    try:
        try:
            run_payload = _build_run_payload(timer_state, scheduled=scheduled)
            run_result = core_runs._start_run(run_payload)
        except HTTPException as exc:
            detail = str(exc.detail)
            if exc.status_code == 409 and "already in progress" in detail.lower():
                _next_retry_at_by_template[template_id] = now + timedelta(seconds=60)
                _set_last_result(
                    timer_state,
                    status="deferred",
                    scheduled=scheduled,
                    detail=detail,
                    reason_code="run_in_progress",
                )
                _append_scheduler_audit_event(
                    timer_state=timer_state,
                    template_id=template_id,
                    status="deferred",
                    scheduled=scheduled,
                    detail=detail,
                )
            else:
                if _schedule_failure_retry(
                    timer_state,
                    template_id=template_id,
                    signature=signature,
                    now=now,
                    scheduled=scheduled,
                    detail=detail,
                ):
                    return
                timer_state["enabled"] = False
                timer_state["last_triggered_signature"] = signature
                timer_state["last_triggered_at"] = now.isoformat(timespec="seconds")
                _clear_failure_retry_state(timer_state)
                _set_last_result(
                    timer_state,
                    status="failed",
                    scheduled=scheduled,
                    detail=detail,
                    code=int(exc.status_code),
                    reason_code="retry_exhausted",
                )
                _append_scheduler_audit_event(
                    timer_state=timer_state,
                    template_id=template_id,
                    status="failed",
                    scheduled=scheduled,
                    detail="retry_exhausted",
                )
                _next_retry_at_by_template.pop(template_id, None)
            return
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
            if _schedule_failure_retry(
                timer_state,
                template_id=template_id,
                signature=signature,
                now=now,
                scheduled=scheduled,
                detail=detail,
            ):
                return
            timer_state["enabled"] = False
            timer_state["last_triggered_signature"] = signature
            timer_state["last_triggered_at"] = now.isoformat(timespec="seconds")
            _clear_failure_retry_state(timer_state)
            _set_last_result(
                timer_state,
                status="failed",
                scheduled=scheduled,
                detail=detail,
                reason_code="retry_exhausted",
            )
            _append_scheduler_audit_event(
                timer_state=timer_state,
                template_id=template_id,
                status="failed",
                scheduled=scheduled,
                detail="retry_exhausted",
            )
            _next_retry_at_by_template.pop(template_id, None)
            return

        if is_repeating:
            _align_state_for_repetition(timer_state, scheduled, reference=now)
        else:
            timer_state["enabled"] = False
        timer_state["last_triggered_signature"] = signature
        timer_state["last_triggered_at"] = now.isoformat(timespec="seconds")
        _clear_failure_retry_state(timer_state)
        run_id = str(run_result.get("run_id") or "")
        _set_last_result(
            timer_state,
            status="started",
            scheduled=scheduled,
            run_id=run_id,
            reason_code="started",
        )
        if once_receipt_key:
            _record_once_receipt(
                once_receipts,
                template_id=template_id,
                run_date=timer_state.get("run_date"),
                run_time=timer_state.get("run_time"),
                run_id=run_id,
                status="started",
            )
        _append_scheduler_audit_event(
            timer_state=timer_state,
            template_id=template_id,
            status="started",
            scheduled=scheduled,
            run_id=run_id,
            extra={"idempotency_key": once_receipt_key} if once_receipt_key else None,
        )
        _next_retry_at_by_template.pop(template_id, None)
    finally:
        _release_trigger_lock(template_id=template_id, token=lock_token)


def evaluate_once(template_id: str | None = None) -> dict[str, Any]:
    now = datetime.now()
    with _state_lock:
        state = _read_state_unlocked()
        timers = _get_template_timers(state)
        once_receipts = _get_once_receipts(state)
        if template_id is None:
            ids = list(timers.keys())
            for template_key in ids:
                _evaluate_single_timer(
                    timers[template_key],
                    template_key,
                    now,
                    once_receipts=once_receipts,
                )
            default_template_id = _DEFAULT_TEMPLATE_ID if _DEFAULT_TEMPLATE_ID in timers else (ids[0] if ids else _DEFAULT_TEMPLATE_ID)
            default_state = timers.get(default_template_id, _default_state())
            state["template_timers"] = timers
            state["once_trigger_receipts"] = once_receipts
            _write_state_unlocked(state)
            return _enrich_state(
                default_state,
                template_id=default_template_id,
                template_timers_count=len(timers),
            )

        template_key = _normalize_template_id(template_id)
        timer_state = _ensure_template_state_container(state, template_key)
        _evaluate_single_timer(
            timer_state,
            template_key,
            now,
            once_receipts=once_receipts,
        )
        state["once_trigger_receipts"] = once_receipts
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
            enabled_before = bool(timer_state.get("enabled"))
            enabled_after = bool(body.get("enabled"))
            timer_state["enabled"] = enabled_after
            if enabled_after and not enabled_before:
                rearm = True
            if not enabled_after:
                _clear_failure_retry_state(timer_state)
        if "card_id" in body:
            timer_state["card_id"] = _normalize_card_id(body.get("card_id"))
        if "action_key" in body:
            timer_state["action_key"] = _validate_action_key_input(body.get("action_key"))
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
            timer_state["run_date"] = _validate_run_date_input(body.get("run_date"))
            timer_state["monthly_anchor_day"] = _normalize_monthly_anchor_day(
                timer_state.get("monthly_anchor_day"),
                fallback_run_date=timer_state.get("run_date"),
            )
        if "run_time" in body:
            timer_state["run_time"] = _validate_run_time_input(body.get("run_time"))
        if "catch_up_policy" in body:
            timer_state["catch_up_policy"] = _validate_catch_up_policy_input(body.get("catch_up_policy"))
        if "recurrence" in body:
            timer_state["recurrence"] = _validate_recurrence_input(body.get("recurrence"))
            if timer_state["recurrence"] == "monthly":
                timer_state["monthly_anchor_day"] = _normalize_monthly_anchor_day(
                    timer_state.get("monthly_anchor_day"),
                    fallback_run_date=timer_state.get("run_date"),
                )

        if rearm:
            timer_state["last_result"] = None
            timer_state["last_triggered_signature"] = ""
            timer_state["last_triggered_at"] = None
            _clear_failure_retry_state(timer_state)

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


def worker_snapshot() -> dict[str, Any]:
    with _worker_lock:
        thread = _worker_thread
        running = bool(thread and thread.is_alive())
    return {
        "running": running,
        "poll_seconds": int(SCHEDULER_POLL_SECONDS),
        "started_at": _started_at.isoformat(timespec="seconds"),
    }


def health_snapshot(*, limit: int = 50) -> dict[str, Any]:
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    now = datetime.now()
    with _state_lock:
        state = _read_state_unlocked()
        timers = _get_template_timers(state)
    lock_rows = _trigger_lock_rows(now)
    active_locks = sum(1 for row in lock_rows if not bool(row.get("stale")))
    stale_locks = sum(1 for row in lock_rows if bool(row.get("stale")))

    rows: list[dict[str, Any]] = []
    enabled_timers = 0
    due_timers = 0
    for template_id, timer_state in timers.items():
        row = _enrich_state(timer_state, template_id=template_id)
        enabled = bool(row.get("enabled"))
        if enabled:
            enabled_timers += 1

        scheduled = _scheduled_datetime(timer_state)
        if enabled and scheduled is not None and scheduled <= now:
            due_timers += 1

        # Hide default empty slot from monitoring list.
        is_default_slot = template_id == _DEFAULT_TEMPLATE_ID
        has_any_context = bool(
            str(row.get("card_id") or "").strip()
            or str(row.get("run_date") or "").strip()
            or str(row.get("updated_at") or "").strip()
            or isinstance(row.get("last_result"), dict)
        )
        if is_default_slot and not has_any_context:
            continue
        rows.append(row)

    rows.sort(
        key=lambda row: (
            0 if bool(row.get("enabled")) else 1,
            0 if str(row.get("next_run_at") or "").strip() else 1,
            str(row.get("next_run_at") or "9999-99-99T99:99:99"),
            str(row.get("template_id") or ""),
        )
    )
    worker = worker_snapshot()
    return {
        "worker_running": bool(worker.get("running")),
        "worker_poll_seconds": int(worker.get("poll_seconds") or 0),
        "worker_started_at": str(worker.get("started_at") or ""),
        "failure_retry_seconds": int(SCHEDULER_FAILURE_RETRY_SECONDS),
        "failure_retry_max_attempts": int(SCHEDULER_FAILURE_RETRY_MAX_ATTEMPTS),
        "total_timers": len(rows),
        "enabled_timers": int(enabled_timers),
        "due_timers": int(due_timers),
        "active_locks": int(active_locks),
        "stale_locks": int(stale_locks),
        "timers": rows[:limit],
    }


def restart_worker() -> dict[str, Any]:
    stop_worker()
    start_worker()
    return worker_snapshot()

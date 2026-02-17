from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Any

from fastapi import HTTPException

from .core_shared import (
    DEFAULT_MFCLOUD_ACCOUNTS_URL,
    DEFAULT_RAKUTEN_URL,
    RUN_ID_RE,
    YM_RE,
    SKILL_ROOT,
    _artifact_root,
    _read_json,
    _read_jsonl,
    _runs_root,
    _write_json,
)
from .core_manual import _provider_inbox_status_for_ym
from .core_orders import _collect_excluded_pdfs, _load_exclusions, _read_workflow

STEP_RESET_SPECS: dict[str, dict[str, Any]] = {
    "amazon_download": {
        "run_modes": {"amazon_download", "amazon_print"},
        "clear_source": "amazon",
        "clear_download": True,
    },
    "amazon_decide_print": {
        "run_modes": {"amazon_print"},
        "clear_source": "amazon",
        "clear_download": False,
    },
    "rakuten_download": {
        "run_modes": {"rakuten_download", "rakuten_print"},
        "clear_source": "rakuten",
        "clear_download": True,
    },
    "rakuten_decide_print": {
        "run_modes": {"rakuten_print"},
        "clear_source": "rakuten",
        "clear_download": False,
    },
}


def _preflight_global_path() -> Path:
    return _artifact_root() / "_preflight.json"


def _audit_log_path(year: int, month: int) -> Path:
    return _artifact_root() / f"{year:04d}-{month:02d}" / "reports" / "audit_log.jsonl"

def _mf_draft_actions_path(year: int, month: int) -> Path:
    return _artifact_root() / f"{year:04d}-{month:02d}" / "reports" / "mf_draft_create_actions.jsonl"


def _mf_draft_actions_summary_for_ym(
    year: int,
    month: int,
    *,
    limit_events: int = 0,
) -> dict[str, Any]:
    path = _mf_draft_actions_path(year, month)
    if not path.exists():
        return {
            "ym": f"{year:04d}-{month:02d}",
            "exists": False,
            "path": str(path),
            "file_url": f"/files/{year:04d}-{month:02d}/mf_draft_actions",
            "summary": {"targets": 0, "created": 0, "skipped": 0, "failed": 0},
            "items": [],
            "events_total": 0,
            "events_loaded": 0,
        }

    events = _read_jsonl(path, required=False, strict=False)
    events_total = len(events)
    if limit_events and limit_events > 0 and events_total > limit_events:
        events = events[-limit_events:]

    items_by_id: dict[str, dict[str, Any]] = {}

    def _get_item(expense_id: str) -> dict[str, Any]:
        item = items_by_id.get(expense_id)
        if item is not None:
            return item
        item = {
            "mf_expense_id": expense_id,
            "status": "",
            "reason": "",
            "detail": "",
            "stage": "",
            "ts_first": None,
            "ts_last": None,
            "mf_use_date": None,
            "mf_amount_yen": None,
            "mf_vendor": None,
            "mf_memo": None,
            "order_id": None,
            "order_source": None,
            "order_date": None,
            "order_total_yen": None,
            "pdf_path": None,
            "row_score": None,
            "row_date": None,
            "row_amount_yen": None,
            "click_selector": None,
            "autofill": [],
            "validation_errors": [],
        }
        items_by_id[expense_id] = item
        return item

    for ev in events:
        if not isinstance(ev, dict):
            continue
        expense_id = str(ev.get("mf_expense_id") or "").strip()
        if not expense_id:
            continue
        action = str(ev.get("action") or "").strip()
        ts = str(ev.get("ts") or "").strip() or None

        item = _get_item(expense_id)
        if ts:
            if not item.get("ts_first"):
                item["ts_first"] = ts
            item["ts_last"] = ts

        if action == "target_start":
            for key in (
                "mf_use_date",
                "mf_amount_yen",
                "mf_vendor",
                "mf_memo",
                "order_id",
                "order_source",
                "order_date",
                "order_total_yen",
                "pdf_path",
            ):
                if key in ev and ev.get(key) is not None:
                    item[key] = ev.get(key)
            continue

        if action == "matching_row_found":
            for key in ("row_score", "row_date", "row_amount_yen"):
                if key in ev and ev.get(key) is not None:
                    item[key] = ev.get(key)
            continue

        if action == "create_validation_failed":
            errors = ev.get("errors")
            if isinstance(errors, list):
                item["validation_errors"] = [str(x) for x in errors if str(x).strip()][:20]
            continue

        if action == "autofill_required_fields":
            filled = ev.get("filled")
            if isinstance(filled, list):
                item["autofill"] = [x for x in filled if isinstance(x, dict)][:20]
            continue

        if action == "target_created":
            item["status"] = "created"
            item["stage"] = str(ev.get("stage") or item.get("stage") or "")
            item["reason"] = ""
            item["detail"] = ""
            item["click_selector"] = ev.get("click_selector") or item.get("click_selector")
            if isinstance(ev.get("autofill"), list):
                item["autofill"] = [x for x in ev.get("autofill") if isinstance(x, dict)][:20]
            continue

        if action == "target_skipped":
            item["status"] = "skipped"
            item["stage"] = str(ev.get("stage") or item.get("stage") or "")
            item["reason"] = str(ev.get("reason") or "").strip()
            item["detail"] = ""
            item["click_selector"] = ev.get("click_selector") or item.get("click_selector")
            continue

        if action == "target_failed":
            item["status"] = "failed"
            item["stage"] = str(ev.get("stage") or item.get("stage") or "")
            item["reason"] = str(ev.get("reason") or "").strip()
            item["detail"] = str(ev.get("detail") or "").strip()
            item["click_selector"] = ev.get("click_selector") or item.get("click_selector")
            continue

    items = list(items_by_id.values())

    def _severity_key(row: dict[str, Any]) -> tuple[int, str]:
        status = str(row.get("status") or "")
        if status == "failed":
            sev = 0
        elif status == "skipped":
            sev = 1
        elif status == "created":
            sev = 2
        else:
            sev = 3
        return (sev, str(row.get("mf_expense_id") or ""))

    items.sort(key=_severity_key)

    created = sum(1 for x in items if x.get("status") == "created")
    failed = sum(1 for x in items if x.get("status") == "failed")
    skipped = sum(1 for x in items if x.get("status") == "skipped")

    return {
        "ym": f"{year:04d}-{month:02d}",
        "exists": True,
        "path": str(path),
        "file_url": f"/files/{year:04d}-{month:02d}/mf_draft_actions",
        "summary": {
            "targets": len(items),
            "created": created,
            "skipped": skipped,
            "failed": failed,
        },
        "items": items,
        "events_total": events_total,
        "events_loaded": len(events),
    }


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


def _build_mf_summary(reports_dir: Path, mf_draft_payload: Any) -> dict[str, Any]:
    missing_candidates_value: int | None = None
    missing_payload = _read_json(reports_dir / "missing_evidence_candidates.json")
    if isinstance(missing_payload, dict):
        counts = missing_payload.get("counts")
        if isinstance(counts, dict):
            missing_candidates_value = _safe_int(counts.get("mf_missing_evidence"))
        if missing_candidates_value is None:
            rows = missing_payload.get("rows")
            if isinstance(rows, list):
                missing_candidates_value = len(rows)

    draft_status = ""
    draft_data: dict[str, Any] = {}
    if isinstance(mf_draft_payload, dict):
        draft_status = str(mf_draft_payload.get("status") or "").strip().lower()
        maybe_data = mf_draft_payload.get("data")
        if isinstance(maybe_data, dict):
            draft_data = maybe_data

    return {
        "missing_candidates": _coerce_non_negative_int(missing_candidates_value),
        "targets_total": _coerce_non_negative_int(draft_data.get("targets_total")),
        "created": _coerce_non_negative_int(draft_data.get("created")),
        "failed": _coerce_non_negative_int(draft_data.get("failed")),
        "status": draft_status,
    }


def _mf_bulk_upload_state_for_ym(reports_dir: Path) -> dict[str, Any]:
    result_path = reports_dir / "mf_bulk_upload_result.json"
    payload = _read_json(result_path)
    if not isinstance(payload, dict):
        return {
            "attempted": False,
            "done": False,
            "status": "",
            "files_found": 0,
            "read_count": 0,
            "queued_count": 0,
            "submitted_count": 0,
            "updated_at": None,
        }

    status = str(payload.get("status") or "").strip().lower()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    files_found = _coerce_non_negative_int(data.get("files_found"))
    read_count = _coerce_non_negative_int(data.get("read_count"))
    queued_count = _coerce_non_negative_int(data.get("queued_count"))
    submitted_count = _coerce_non_negative_int(data.get("submitted_count"))
    done = status in {"ok", "success"}
    updated_at = str(payload.get("updated_at") or "").strip() or None
    if not updated_at and result_path.exists():
        try:
            updated_at = datetime.fromtimestamp(result_path.stat().st_mtime).isoformat(timespec="seconds")
        except Exception:
            updated_at = None

    return {
        "attempted": True,
        "done": done,
        "status": status,
        "files_found": files_found,
        "read_count": read_count,
        "queued_count": queued_count,
        "submitted_count": submitted_count,
        "updated_at": updated_at,
    }


def _mf_csv_import_state_for_ym(reports_dir: Path) -> dict[str, Any]:
    result_path = reports_dir / "mf_csv_import_result.json"
    payload = _read_json(result_path)
    if not isinstance(payload, dict):
        return {
            "attempted": False,
            "done": False,
            "status": "",
            "files_found": 0,
            "queued_count": 0,
            "submitted_count": 0,
            "updated_at": None,
        }

    status = str(payload.get("status") or "").strip().lower()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    files_found = _coerce_non_negative_int(data.get("files_found"))
    queued_count = _coerce_non_negative_int(data.get("queued_count"))
    submitted_count = _coerce_non_negative_int(data.get("submitted_count"))
    done = status in {"ok", "success"}
    updated_at = str(payload.get("updated_at") or "").strip() or None
    if not updated_at and result_path.exists():
        try:
            updated_at = datetime.fromtimestamp(result_path.stat().st_mtime).isoformat(timespec="seconds")
        except Exception:
            updated_at = None

    return {
        "attempted": True,
        "done": done,
        "status": status,
        "files_found": files_found,
        "queued_count": queued_count,
        "submitted_count": submitted_count,
        "updated_at": updated_at,
    }


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
) -> None:
    path = _audit_log_path(year, month)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ym": f"{year:04d}-{month:02d}",
        "year": year,
        "month": month,
        "event_type": str(event_type).strip(),
        "action": str(action).strip(),
        "status": str(status).strip(),
        "actor": _normalize_actor(actor),
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
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _capture_failed_run_incident(
    *,
    meta_path: Path,
    meta: dict[str, Any],
    reason: str,
    inferred_from: str = "",
) -> None:
    status = str(meta.get("status") or "").strip().lower()
    if status != "failed":
        return
    if str(meta.get("error_incident_id") or "").strip():
        return
    if str(meta.get("error_capture_attempted_at") or "").strip():
        return

    script_path = SKILL_ROOT / "scripts" / "error_capture.py"
    ts = datetime.now().isoformat(timespec="seconds")
    meta["error_capture_attempted_at"] = ts
    if not script_path.exists():
        meta["error_capture_error"] = f"script_not_found: {script_path}"
        _write_json(meta_path, meta)
        return

    params = meta.get("params") if isinstance(meta.get("params"), dict) else {}
    year = _safe_int(params.get("year"))
    month = _safe_int(params.get("month"))
    mode = str(params.get("mode") or "").strip() or "unknown"
    run_id = str(meta.get("run_id") or "").strip()
    returncode = _safe_int(meta.get("returncode"))
    log_path = str(meta.get("log_path") or "").strip()
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
        json.dumps(context_payload, ensure_ascii=False),
    ]
    if year is not None and month is not None:
        cmd += ["--year", str(year), "--month", str(month)]
        audit_path = _audit_log_path(year, month)
        if audit_path.exists():
            cmd += ["--audit-path", str(audit_path)]
    if log_path:
        cmd += ["--log-path", log_path]

    try:
        res = subprocess.run(
            cmd,
            cwd=str(SKILL_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except Exception as exc:
        meta["error_capture_error"] = f"capture_exception: {exc}"
        _write_json(meta_path, meta)
        return

    if res.returncode != 0:
        stderr = str(res.stderr or "").strip()
        stdout = str(res.stdout or "").strip()
        message_text = stderr or stdout or f"exit={res.returncode}"
        meta["error_capture_error"] = f"capture_failed: {message_text[:500]}"
        _write_json(meta_path, meta)
        return

    payload: dict[str, Any] = {}
    try:
        payload = json.loads(str(res.stdout or "{}"))
    except Exception:
        payload = {}

    incident_id = str(payload.get("incident_id") or "").strip()
    if incident_id:
        meta["error_incident_id"] = incident_id
        meta.pop("error_capture_error", None)
    else:
        meta["error_capture_error"] = "capture_succeeded_but_incident_id_missing"
    _write_json(meta_path, meta)

    if year is not None and month is not None:
        details = {
            "reason": reason,
            "inferred_from": inferred_from,
            "returncode": returncode if returncode is not None else -1,
            "incident_id": incident_id,
        }
        _append_audit_event(
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


def _is_preflight_success(payload: Any, *, year: int, month: int) -> bool:
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or "").strip().lower()
    if status != "success":
        return False
    try:
        return int(payload.get("year")) == year and int(payload.get("month")) == month
    except Exception:
        return False


def _latest_archive_state_for_ym(year: int, month: int) -> dict[str, Any]:
    latest_success: dict[str, Any] | None = None
    audit_path = _audit_log_path(year, month)
    if audit_path.exists():
        for line in audit_path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = str(line or "").strip()
            if not text.startswith("{") or not text.endswith("}"):
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if str(payload.get("event_type") or "").strip() != "archive":
                continue
            action = str(payload.get("action") or "").strip()
            if action not in {"manual_archive", "month_close"}:
                continue
            if str(payload.get("status") or "").strip() != "success":
                continue
            details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
            latest_success = {
                "created": True,
                "created_at": str(payload.get("ts") or "").strip() or None,
                "archived_to": str(details.get("archived_to") or "").strip() or None,
                "include_pdfs": bool(details.get("include_pdfs")),
                "include_debug": bool(details.get("include_debug")),
                "cleanup": bool(details.get("cleanup")),
            }
    if latest_success:
        return latest_success

    ym = f"{year:04d}-{month:02d}"
    root = _artifact_root() / ym / "archive"
    candidates = [p for p in root.glob("*") if p.is_dir()] if root.exists() else []
    if not candidates:
        return {
            "created": False,
            "created_at": None,
            "archived_to": None,
            "include_pdfs": False,
            "include_debug": False,
            "cleanup": False,
        }
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "created": True,
        "created_at": None,
        "archived_to": str(candidates[0]),
        "include_pdfs": True,
        "include_debug": False,
        "cleanup": False,
    }


def _workflow_state_for_ym(year: int, month: int) -> dict[str, Any]:
    ym = f"{year:04d}-{month:02d}"
    root = _artifact_root() / ym
    reports_dir = root / "reports"
    workflow = _read_workflow(reports_dir)
    amazon_section = workflow.get("amazon") if isinstance(workflow.get("amazon"), dict) else {}
    rakuten_section = workflow.get("rakuten") if isinstance(workflow.get("rakuten"), dict) else {}

    local_preflight = _read_json(reports_dir / "preflight.json")
    global_preflight = _read_json(_preflight_global_path())
    preflight_done = _is_preflight_success(local_preflight, year=year, month=month) or _is_preflight_success(
        global_preflight,
        year=year,
        month=month,
    )
    amazon_orders_exists = (root / "amazon" / "orders.jsonl").exists()
    rakuten_orders_exists = (root / "rakuten" / "orders.jsonl").exists()

    def _resolve_downloaded(section: dict[str, Any], orders_exists: bool) -> bool:
        status = str(section.get("download_status") or "").strip().lower()
        downloaded_at = bool(section.get("downloaded_at"))
        confirmed_printed = bool(section.get("confirmed_at")) and bool(section.get("printed_at"))
        if status == "failed":
            return False
        if status == "success":
            return downloaded_at or orders_exists or confirmed_printed
        return downloaded_at or orders_exists or confirmed_printed

    amazon_downloaded = _resolve_downloaded(amazon_section, amazon_orders_exists)
    rakuten_downloaded = _resolve_downloaded(rakuten_section, rakuten_orders_exists)
    amazon_confirmed = bool(amazon_section.get("confirmed_at"))
    amazon_printed = bool(amazon_section.get("printed_at"))
    rakuten_confirmed = bool(rakuten_section.get("confirmed_at"))
    rakuten_printed = bool(rakuten_section.get("printed_at"))
    providers_state = _provider_inbox_status_for_ym(year, month)
    providers_pending = int(providers_state.get("pending_total") or 0)
    archive_state = _latest_archive_state_for_ym(year, month)
    mf_reconciled = (reports_dir / "missing_evidence_candidates.json").exists()
    mf_draft_result_path = reports_dir / "mf_draft_create_result.json"
    mf_draft_payload = _read_json(mf_draft_result_path)
    mf_summary = _build_mf_summary(reports_dir, mf_draft_payload)
    mf_bulk_upload_state = _mf_bulk_upload_state_for_ym(reports_dir)
    mf_csv_import_state = _mf_csv_import_state_for_ym(reports_dir)
    mf_drafted = bool(
        isinstance(mf_draft_payload, dict) and str(mf_draft_payload.get("status") or "").strip().lower() in {"ok", "success"}
    )
    mf_step_done = bool(mf_reconciled and (mf_drafted or not mf_draft_result_path.exists()))
    amazon_done = amazon_downloaded and amazon_confirmed and amazon_printed
    rakuten_done = rakuten_downloaded and rakuten_confirmed and rakuten_printed
    amazon_pending = amazon_downloaded and not amazon_done
    rakuten_pending = rakuten_downloaded and not rakuten_done
    any_source_downloaded = amazon_downloaded or rakuten_downloaded
    source_ready_for_reconcile = amazon_done and rakuten_done
    can_reconcile = bool(source_ready_for_reconcile)

    can_archive = bool(amazon_done or rakuten_done)

    next_step = "done"
    next_step_reason = "workflow_complete"
    if not preflight_done:
        next_step = "preflight"
        next_step_reason = "preflight_required"
    elif mf_step_done:
        next_step = "done"
        next_step_reason = "workflow_complete"
    elif amazon_pending:
        next_step = "amazon_decide_print"
        next_step_reason = "amazon_print_pending"
    elif rakuten_pending:
        next_step = "rakuten_decide_print"
        next_step_reason = "rakuten_print_pending"
    elif providers_pending > 0:
        next_step = "provider_ingest"
        next_step_reason = "provider_ingest_pending"
    elif can_reconcile:
        next_step = "mf_reconcile"
        next_step_reason = "mf_reconcile_ready"
    elif not amazon_downloaded and not rakuten_downloaded:
        next_step = "amazon_or_rakuten_download"
        next_step_reason = "source_download_required"
    elif not amazon_downloaded:
        next_step = "amazon_download"
        next_step_reason = "amazon_download_required"
    elif not rakuten_downloaded:
        next_step = "rakuten_download"
        next_step_reason = "rakuten_download_required"

    allowed_run_modes: list[str] = ["preflight"]
    if preflight_done:
        allowed_run_modes.extend(["amazon_download", "rakuten_download"])
        if amazon_downloaded:
            allowed_run_modes.append("amazon_print")
        if rakuten_downloaded:
            allowed_run_modes.append("rakuten_print")
        if can_reconcile:
            allowed_run_modes.append("mf_reconcile")
    allowed_run_modes = list(dict.fromkeys(allowed_run_modes))

    archive_state = dict(archive_state)
    archive_state["can_archive"] = can_archive

    return {
        "ym": ym,
        "preflight": {"done": preflight_done},
        "amazon": {"downloaded": amazon_downloaded, "confirmed": amazon_confirmed, "printed": amazon_printed},
        "rakuten": {"downloaded": rakuten_downloaded, "confirmed": rakuten_confirmed, "printed": rakuten_printed},
        "providers": providers_state,
        "mf_bulk_upload": mf_bulk_upload_state,
        "mf_csv_import": mf_csv_import_state,
        "archive": archive_state,
        "mf": {"reconciled": mf_reconciled, "drafted": mf_drafted, "step_done": mf_step_done, "summary": mf_summary},
        "next_step": next_step,
        "next_step_reason": next_step_reason,
        "can_reconcile": can_reconcile,
        "ready_for_reconcile": can_reconcile,
        "any_source_downloaded": any_source_downloaded,
        "allowed_run_modes": allowed_run_modes,
        "running_mode": _running_mode_for_ym(year, month),
    }


def _reset_workflow_for_redownload(year: int, month: int, source: str) -> None:
    ym = f"{year:04d}-{month:02d}"
    reports_dir = _artifact_root() / ym / "reports"
    workflow = _read_workflow(reports_dir)
    if not isinstance(workflow, dict):
        workflow = {}
    changed = False
    if source == "amazon":
        if "amazon" in workflow:
            workflow.pop("amazon", None)
            changed = True
    elif source == "rakuten":
        if "rakuten" in workflow:
            workflow.pop("rakuten", None)
            changed = True
    _remove_reconcile_outputs_only(reports_dir)
    if changed:
        _write_json(reports_dir / "workflow.json", workflow)


def _assert_run_mode_allowed(year: int, month: int, mode: str) -> None:
    if mode in {"preflight", "preflight_mf"}:
        return
    state = _workflow_state_for_ym(year, month)
    allowed = state.get("allowed_run_modes") if isinstance(state.get("allowed_run_modes"), list) else []
    if mode in allowed:
        return
    next_step = str(state.get("next_step") or "")
    allowed_label = ", ".join(str(x) for x in allowed) if allowed else "none"
    raise HTTPException(
        status_code=409,
        detail=(
            "Workflow order violation: "
            f"next_step={next_step}; allowed_modes={allowed_label}; requested_mode={mode}"
        ),
    )


def _assert_source_action_allowed(year: int, month: int, source: str, action: str) -> None:
    if source not in {"amazon", "rakuten"}:
        raise HTTPException(status_code=400, detail="Invalid source.")
    if action not in {"confirm", "print"}:
        raise HTTPException(status_code=400, detail="Invalid action.")

    state = _workflow_state_for_ym(year, month)
    if not state["preflight"]["done"]:
        raise HTTPException(
            status_code=409,
            detail="Workflow order violation: preflight is required before confirmation/print.",
        )

    branch = state["amazon"] if source == "amazon" else state["rakuten"]
    label = "amazon" if source == "amazon" else "rakuten"
    if not branch["downloaded"]:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow order violation: {label}_download must be completed before {label} confirmation/print.",
        )
    if action == "print" and not branch["confirmed"]:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow order violation: {label} confirmation is required before {label} print.",
        )


def _assert_archive_allowed(year: int, month: int) -> None:
    state = _workflow_state_for_ym(year, month)
    archive_state = state.get("archive") if isinstance(state.get("archive"), dict) else {}
    if bool(archive_state.get("can_archive")):
        return
    raise HTTPException(
        status_code=409,
        detail="Workflow order violation: archive requires at least one source to complete confirmation and print first.",
    )


def _archive_outputs_for_ym(
    year: int,
    month: int,
    *,
    include_pdfs: bool = True,
    include_debug: bool = False,
    cleanup: bool = True,
) -> dict[str, Any]:
    ym = f"{year:04d}-{month:02d}"
    output_root = _artifact_root() / ym
    if not output_root.exists():
        raise HTTPException(status_code=404, detail="Artifacts for target month were not found.")

    has_artifacts = any(
        (
            (output_root / "reports").exists(),
            (output_root / "amazon" / "orders.jsonl").exists(),
            (output_root / "rakuten" / "orders.jsonl").exists(),
            (output_root / "mfcloud" / "expenses.jsonl").exists(),
            (output_root / "run_config.resolved.json").exists(),
        )
    )
    if not has_artifacts:
        raise HTTPException(status_code=404, detail="Artifacts for target month were not found.")

    reports_dir = output_root / "reports"
    exclusions = _load_exclusions(reports_dir)
    excluded_rows = _collect_excluded_pdfs(output_root, ym, exclusions)
    excluded_manifest_path = reports_dir / "excluded_pdfs.json"
    _write_json(
        excluded_manifest_path,
        {
            "ym": ym,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(excluded_rows),
            "rows": excluded_rows,
        },
    )

    script = SKILL_ROOT / "scripts" / "archive_outputs.ps1"
    if not script.exists():
        raise HTTPException(status_code=500, detail=f"archive script not found: {script}")

    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-OutputRoot",
        str(output_root),
    ]
    if include_pdfs:
        cmd.append("-IncludePdfs")
    if include_debug:
        cmd.append("-IncludeDebug")
    if cleanup:
        cmd.append("-Cleanup")
    else:
        cmd.append("-NoCleanup")

    res = subprocess.run(
        cmd,
        cwd=str(script.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=(
                "archive_outputs.ps1 failed:\n"
                f"cmd: {cmd}\n"
                f"exit: {res.returncode}\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            ),
        )

    archived_to = ""
    cleanup_report = ""
    cleanup_removed = 0
    archive_zip = ""
    archive_manifest = ""
    archive_checksums = ""
    for line in reversed((res.stdout or "").splitlines()):
        text = str(line).strip()
        if text.lower().startswith("archived to:"):
            archived_to = text.split(":", 1)[1].strip()
            continue
        if text.lower().startswith("cleanup report:"):
            cleanup_report = text.split(":", 1)[1].strip()
            continue
        if text.lower().startswith("cleanup removed:"):
            cleanup_removed = _coerce_non_negative_int(text.split(":", 1)[1].strip(), default=0)
            continue
        if text.lower().startswith("archive zip:"):
            archive_zip = text.split(":", 1)[1].strip()
            continue
        if text.lower().startswith("archive manifest:"):
            archive_manifest = text.split(":", 1)[1].strip()
            continue
        if text.lower().startswith("archive checksums:"):
            archive_checksums = text.split(":", 1)[1].strip()
            continue

    if not archived_to:
        archive_root = output_root / "archive"
        candidates = [p for p in archive_root.glob("*") if p.is_dir()] if archive_root.exists() else []
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            archived_to = str(candidates[0])

    if not archived_to:
        raise HTTPException(
            status_code=500,
            detail=(
                "archive_outputs.ps1 did not report archive destination.\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            ),
        )

    if cleanup and not cleanup_report:
        fallback_cleanup = output_root / "reports" / "archive_cleanup_report.json"
        if fallback_cleanup.exists():
            cleanup_report = str(fallback_cleanup)

    if not archive_manifest:
        fallback_manifest = Path(archived_to) / "manifest.json"
        if fallback_manifest.exists():
            archive_manifest = str(fallback_manifest)
    if not archive_zip:
        fallback_zip = Path(archived_to) / "full_snapshot.zip"
        if fallback_zip.exists():
            archive_zip = str(fallback_zip)
    if not archive_checksums:
        fallback_checksums = Path(archived_to) / "checksums.sha256"
        if fallback_checksums.exists():
            archive_checksums = str(fallback_checksums)

    return {
        "status": "ok",
        "ym": ym,
        "archived_to": archived_to,
        "include_pdfs": bool(include_pdfs),
        "include_debug": bool(include_debug),
        "cleanup": bool(cleanup),
        "cleanup_report": cleanup_report,
        "cleanup_removed": int(cleanup_removed),
        "archive_manifest": archive_manifest,
        "archive_zip": archive_zip,
        "archive_checksums": archive_checksums,
        "excluded_pdfs_manifest": str(excluded_manifest_path),
        "excluded_pdfs_count": len(excluded_rows),
    }


def _tail_text(path: Path, max_bytes: int = 5000) -> str:
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _infer_run_exit_code_from_log(log_path: Path) -> tuple[int | None, str | None]:
    text = _tail_text(log_path, max_bytes=200_000)
    if not text:
        return None, None
    decoder = json.JSONDecoder()

    def _status_from_payload(payload: Any) -> int | None:
        if not isinstance(payload, dict):
            return None
        status = str(payload.get("status") or "").strip().lower()
        if status == "success":
            return 0
        if status in {"failed", "error", "cancelled", "canceled"}:
            return 1
        return None

    # scripts/run.py prints a final pretty JSON object; prefer it when present.
    for marker in ('{\n  "status"', '{\r\n  "status"'):
        idx = text.rfind(marker)
        if idx < 0:
            continue
        candidate = text[idx:].strip()
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        status_code = _status_from_payload(payload)
        if status_code is not None:
            return status_code, "final_json"

    # Fallback: inspect trailing single-line JSON emitted by child scripts.
    for line in reversed(text.splitlines()):
        item = line.strip()
        if not item.startswith("{") or not item.endswith("}"):
            continue
        try:
            payload = json.loads(item)
        except Exception:
            continue
        status_code = _status_from_payload(payload)
        if status_code is not None:
            return status_code, "line_json"

    # Fallback: parse JSON objects embedded in the log tail to tolerate
    # log format variants (prefix text, mixed lines, spacing differences).
    scan_pos = len(text)
    while scan_pos > 0:
        idx = text.rfind("{", 0, scan_pos)
        if idx < 0:
            break
        try:
            payload, _ = decoder.raw_decode(text, idx)
        except Exception:
            scan_pos = idx
            continue
        status_code = _status_from_payload(payload)
        if status_code is not None:
            return status_code, "json_scan"
        scan_pos = idx

    return None, None


def _record_download_result(year: int, month: int, mode: str, exit_code: int) -> None:
    source = "amazon" if mode == "amazon_download" else "rakuten" if mode == "rakuten_download" else ""
    if not source:
        return
    reports_dir = _artifact_root() / f"{year:04d}-{month:02d}" / "reports"
    workflow = _read_workflow(reports_dir)
    section = workflow.get(source) if isinstance(workflow.get(source), dict) else {}
    ts = datetime.now().isoformat(timespec="seconds")
    section["download_status"] = "success" if exit_code == 0 else "failed"
    section["download_updated_at"] = ts
    if exit_code == 0:
        section["downloaded_at"] = ts
    else:
        section.pop("downloaded_at", None)
        section.pop("confirmed_at", None)
        section.pop("print_prepared_at", None)
        section.pop("printed_at", None)
    workflow[source] = section
    _write_json(reports_dir / "workflow.json", workflow)


def _mark_preflight_started(year: int, month: int) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    data = {"status": "started", "started_at": ts, "year": year, "month": month}
    output_root = _artifact_root() / f"{year:04d}-{month:02d}"
    reports_dir = output_root / "reports"
    _write_json(reports_dir / "preflight.json", data)
    _write_json(_preflight_global_path(), data)


def _pid_alive(pid: Any) -> bool:
    if not pid:
        return False
    try:
        pid_int = int(pid)
    except Exception:
        return False
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid_int}"],
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return True
        return re.search(rf"\b{pid_int}\b", out) is not None
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True
    return True


def _reconcile_running_jobs() -> None:
    root = _runs_root()
    if not root.exists():
        return
    for p in root.glob("run_*.json"):
        data = _read_json(p)
        if not isinstance(data, dict):
            continue
        if data.get("status") != "running":
            continue
        if _pid_alive(data.get("pid")):
            continue
        # Re-read to avoid racing with worker thread finalization.
        latest = _read_json(p)
        if not isinstance(latest, dict):
            continue
        if latest.get("status") != "running":
            continue
        data = latest
        log_path = Path(str(data.get("log_path") or ""))
        inferred_returncode, inferred_from = _infer_run_exit_code_from_log(log_path)
        if inferred_returncode is None:
            data["status"] = "failed"
            if data.get("returncode") is None:
                data["returncode"] = -1
            reason = "process_ended_without_final_status"
        else:
            data["status"] = "success" if inferred_returncode == 0 else "failed"
            data["returncode"] = inferred_returncode
            reason = "process_ended_reconciled_from_log"
        if not data.get("finished_at"):
            data["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json(p, data)
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        year = _safe_int(params.get("year"))
        month = _safe_int(params.get("month"))
        if year is None or month is None:
            continue
        mode = str(params.get("mode") or "unknown")
        returncode = _safe_int(data.get("returncode"))
        if returncode is None:
            returncode = -1
        _record_download_result(year, month, mode, returncode)
        if returncode != 0:
            _capture_failed_run_incident(
                meta_path=p,
                meta=data,
                reason=reason,
                inferred_from=inferred_from,
            )
        _append_audit_event(
            year=year,
            month=month,
            event_type="run",
            action=mode,
            status=str(data.get("status") or "failed"),
            actor=data.get("actor"),
            mode=mode,
            run_id=str(data.get("run_id") or ""),
            details={
                "reason": reason,
                "returncode": returncode,
                "inferred_from": inferred_from,
            },
        )


def _scan_run_jobs() -> list[dict[str, Any]]:
    _reconcile_running_jobs()
    root = _runs_root()
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for p in root.glob("run_*.json"):
        data = _read_json(p) or {}
        if not data:
            continue
        items.append(data)
    items.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    return items


def _running_job_exists() -> bool:
    for job in _scan_run_jobs():
        if job.get("status") == "running":
            return True
    return False


def _get_latest_running_job() -> dict[str, Any] | None:
    for job in _scan_run_jobs():
        if job.get("status") == "running":
            return job
    return None


def _run_worker(process: subprocess.Popen, meta_path: Path) -> None:
    exit_code = process.wait()
    meta = _read_json(meta_path) or {}
    meta["status"] = "success" if exit_code == 0 else "failed"
    meta["finished_at"] = datetime.now().isoformat(timespec="seconds")
    meta["returncode"] = exit_code
    _write_json(meta_path, meta)
    params = meta.get("params") if isinstance(meta.get("params"), dict) else {}
    year = _safe_int(params.get("year"))
    month = _safe_int(params.get("month"))
    if year is None or month is None:
        return
    mode = str(params.get("mode") or "unknown")
    _record_download_result(year, month, mode, exit_code)
    if exit_code != 0:
        _capture_failed_run_incident(
            meta_path=meta_path,
            meta=meta,
            reason="worker_exit",
            inferred_from="process_wait",
        )
    _append_audit_event(
        year=year,
        month=month,
        event_type="run",
        action=mode,
        status="success" if exit_code == 0 else "failed",
        actor=meta.get("actor"),
        mode=mode,
        run_id=str(meta.get("run_id") or ""),
        details={"returncode": exit_code},
    )


def _terminate_pid(pid: Any) -> None:
    pid_int = _safe_int(pid)
    if pid_int is None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid_int), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.kill(pid_int, 9)
    except Exception:
        pass


def _delete_path(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return True
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def _remove_mf_outputs(reports_dir: Path) -> list[str]:
    cleared: list[str] = []
    for name in (
        "missing_evidence_candidates.json",
        "missing_evidence_candidates.csv",
        "quality_gate.json",
        "monthly_thread.md",
        "mf_draft_create_result.json",
        "print_manifest.json",
        "print_manifest.amazon.json",
        "print_manifest.rakuten.json",
        "print_list.txt",
        "print_list.amazon.txt",
        "print_list.rakuten.txt",
        "print_all.ps1",
        "print_merged_amazon.pdf",
        "print_merged_rakuten.pdf",
    ):
        path = reports_dir / name
        if _delete_path(path):
            cleared.append(str(path))
    return cleared


def _remove_reconcile_outputs_only(reports_dir: Path) -> list[str]:
    cleared: list[str] = []
    for name in (
        "missing_evidence_candidates.json",
        "missing_evidence_candidates.csv",
        "mf_draft_actions.jsonl",
        "quality_gate.json",
        "monthly_thread.md",
        "mf_draft_create_result.json",
    ):
        path = reports_dir / name
        if _delete_path(path):
            cleared.append(str(path))
    return cleared


def _cancel_step_runs(
    *,
    year: int,
    month: int,
    step: str,
    allowed_modes: set[str],
    actor: Any = None,
) -> list[str]:
    cancelled_run_ids: list[str] = []
    for job in _scan_run_jobs():
        if job.get("status") != "running":
            continue
        params = job.get("params") if isinstance(job.get("params"), dict) else {}
        if _safe_int(params.get("year")) != year or _safe_int(params.get("month")) != month:
            continue
        mode = str(params.get("mode") or "")
        if mode not in allowed_modes:
            raise HTTPException(
                status_code=409,
                detail=f"現在この年月で別の実行中です（{mode}）。停止してからリセットしてください。",
            )
        run_id = str(job.get("run_id") or "")
        if not run_id:
            continue
        _terminate_pid(job.get("pid"))
        job["status"] = "cancelled"
        job["finished_at"] = datetime.now().isoformat(timespec="seconds")
        job["returncode"] = -1
        _write_json(_runs_root() / f"{run_id}.json", job)
        cancelled_run_ids.append(run_id)
        _append_audit_event(
            year=year,
            month=month,
            event_type="run",
            action="step_reset_stop",
            status="success",
            actor=actor,
            mode=mode,
            run_id=run_id,
            details={"step": step, "returncode": -1},
        )
    return cancelled_run_ids


def _reset_step_state(year: int, month: int, step: str, actor: Any = None) -> dict[str, Any]:
    spec = STEP_RESET_SPECS.get(step)
    if not spec:
        raise HTTPException(status_code=400, detail="Invalid step id for reset.")

    root = _artifact_root() / f"{year:04d}-{month:02d}"
    reports_dir = root / "reports"
    clear_source = str(spec["clear_source"])
    clear_download = bool(spec["clear_download"])
    run_modes = set(spec["run_modes"])

    cancelled = _cancel_step_runs(year=year, month=month, step=step, allowed_modes=run_modes, actor=actor)

    cleared_paths: list[str] = []
    if clear_download:
        orders_jsonl = root / clear_source / "orders.jsonl"
        if _delete_path(orders_jsonl):
            cleared_paths.append(str(orders_jsonl))
        pdfs_dir = root / clear_source / "pdfs"
        if _delete_path(pdfs_dir):
            cleared_paths.append(str(pdfs_dir))
        pdfs_dir.mkdir(parents=True, exist_ok=True)
        exclude_path = reports_dir / "exclude_orders.json"
        exclude_payload = _read_json(exclude_path)
        if isinstance(exclude_payload, dict):
            items = exclude_payload.get("exclude")
            if isinstance(items, list):
                kept_items: list[Any] = []
                removed = False
                for item in items:
                    if not isinstance(item, dict):
                        kept_items.append(item)
                        continue
                    item_source = str(item.get("source") or "").strip()
                    if item_source == clear_source:
                        removed = True
                        continue
                    kept_items.append(item)
                if removed:
                    if kept_items:
                        exclude_payload["exclude"] = kept_items
                        exclude_payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
                        _write_json(exclude_path, exclude_payload)
                        cleared_paths.append(str(exclude_path))
                    elif _delete_path(exclude_path):
                        cleared_paths.append(str(exclude_path))

    workflow = _read_workflow(reports_dir)
    changed_workflow = False
    if clear_source in workflow:
        workflow.pop(clear_source, None)
        changed_workflow = True
    if changed_workflow:
        _write_json(reports_dir / "workflow.json", workflow)
        cleared_paths.append(str(reports_dir / "workflow.json"))

    cleared_paths.extend(_remove_mf_outputs(reports_dir))

    _append_audit_event(
        year=year,
        month=month,
        event_type="step_reset",
        action=step,
        status="success",
        actor=actor,
        source=clear_source,
        details={
            "cancelled_runs": cancelled,
            "cleared_paths": cleared_paths,
            "clear_download": clear_download,
        },
    )

    return {
        "step": step,
        "source": clear_source,
        "cancelled_runs": cancelled,
        "cleared_paths": cleared_paths,
        "clear_download": clear_download,
    }


def _start_run(payload: dict[str, Any]) -> dict[str, Any]:
    if _running_job_exists():
        raise HTTPException(status_code=409, detail="Another run is already in progress.")

    mode = str(payload.get("mode") or "full").strip()
    valid_modes = {
        "preflight",
        "preflight_mf",
        "amazon_download",
        "rakuten_download",
        "amazon_print",
        "rakuten_print",
        "mf_reconcile",
    }
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail="Invalid mode.")

    try:
        year = int(payload.get("year"))
        month = int(payload.get("month"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid year/month.") from exc
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12.")
    actor = _normalize_actor(payload.get("_audit_actor"))
    try:
        _assert_run_mode_allowed(year, month, mode)
    except HTTPException as exc:
        _append_audit_event(
            year=year,
            month=month,
            event_type="run",
            action=mode,
            status="rejected",
            actor=actor,
            mode=mode,
            details={"reason": str(exc.detail)},
        )
        raise
    mfcloud_url = str(payload.get("mfcloud_url") or "").strip()
    if mode == "mf_reconcile" and not mfcloud_url:
        _append_audit_event(
            year=year,
            month=month,
            event_type="run",
            action=mode,
            status="rejected",
            actor=actor,
            mode=mode,
            details={"reason": "MF Cloud expense list URL is required."},
        )
        raise HTTPException(status_code=400, detail="MF Cloud expense list URL is required.")

    rakuten_enabled = bool(payload.get("rakuten_enabled"))
    notes = str(payload.get("notes") or "").strip()
    rakuten_orders_url = str(payload.get("rakuten_orders_url") or DEFAULT_RAKUTEN_URL)

    runs_root = _runs_root()
    runs_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_id = f"run_{ts}"
    log_path = runs_root / f"{run_id}.log"
    meta_path = runs_root / f"{run_id}.json"

    auth_handoff = bool(payload.get("auth_handoff", True))
    auto_receipt_name = bool(payload.get("auto_receipt_name", True))
    skip_receipt_name = not auto_receipt_name
    cmd = [
        sys.executable,
        "-u",
        "scripts/run.py",
        "--year",
        str(year),
        "--month",
        str(month),
    ]
    if auth_handoff:
        cmd += ["--interactive", "--headed"]
    else:
        cmd += ["--non-interactive", "--headless"]
    if mfcloud_url:
        cmd += ["--mfcloud-expense-list-url", mfcloud_url]
    if notes:
        cmd += ["--notes", notes]
    if skip_receipt_name:
        cmd += ["--skip-receipt-name"]

    if mode in {"preflight", "preflight_mf"}:
        _mark_preflight_started(year, month)
        cmd += ["--preflight", "--mfcloud-accounts-url", DEFAULT_MFCLOUD_ACCOUNTS_URL]
        if mode == "preflight_mf":
            cmd += ["--skip-amazon", "--skip-rakuten"]
    elif mode in {"amazon_download", "amazon_print"}:
        if mode == "amazon_download":
            _reset_workflow_for_redownload(year, month, "amazon")
        cmd += ["--skip-mfcloud", "--skip-rakuten", "--skip-reconcile"]
        if mode == "amazon_print":
            cmd += ["--print-list", "--print-sources", "amazon"]
    elif mode in {"rakuten_download", "rakuten_print"}:
        if mode == "rakuten_download":
            _reset_workflow_for_redownload(year, month, "rakuten")
        cmd += [
            "--skip-mfcloud",
            "--skip-amazon",
            "--skip-reconcile",
            "--enable-rakuten",
        ]
        if mode == "rakuten_print":
            cmd += ["--print-list", "--print-sources", "rakuten"]
        if rakuten_orders_url:
            cmd += ["--rakuten-orders-url", rakuten_orders_url]
    elif mode == "mf_reconcile":
        _remove_reconcile_outputs_only(_artifact_root() / f"{year:04d}-{month:02d}" / "reports")
        cmd += ["--skip-amazon", "--skip-rakuten"]
        if bool(payload.get("mf_draft_create", True)):
            cmd += ["--mf-draft-create"]
        output_root = _artifact_root() / f"{year:04d}-{month:02d}"
        if (output_root / "rakuten" / "orders.jsonl").exists():
            cmd += ["--enable-rakuten"]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            cmd,
            cwd=str(SKILL_ROOT),
            stdout=log,
            stderr=log,
            env=env,
        )

    meta = {
        "run_id": run_id,
        "status": "running",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "pid": process.pid,
        "actor": actor,
        "log_path": str(log_path),
        "cmd": cmd,
        "params": {
            "year": year,
            "month": month,
            "mfcloud_url": mfcloud_url,
            "rakuten_enabled": rakuten_enabled,
            "notes": notes,
            "rakuten_orders_url": rakuten_orders_url,
            "mode": mode,
            "auth_handoff": auth_handoff,
            "auto_receipt_name": auto_receipt_name,
            "mf_draft_create": bool(payload.get("mf_draft_create", True)) if mode == "mf_reconcile" else False,
        },
    }
    _write_json(meta_path, meta)
    _append_audit_event(
        year=year,
        month=month,
        event_type="run",
        action=mode,
        status="started",
        actor=actor,
        mode=mode,
        run_id=run_id,
        details={"auth_handoff": auth_handoff, "auto_receipt_name": auto_receipt_name},
    )

    watcher = threading.Thread(target=_run_worker, args=(process, meta_path), daemon=True)
    watcher.start()

    return {"run_id": run_id, "status": "running"}


def _safe_ym(ym: str) -> str:
    if not YM_RE.match(ym):
        raise HTTPException(status_code=400, detail="Invalid year-month format.")
    return ym


def _safe_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id.")
    return run_id


def _split_ym(ym: str) -> tuple[int, int]:
    return int(ym[:4]), int(ym[5:7])


def _running_mode_for_ym(year: int, month: int) -> str | None:
    for job in _scan_run_jobs():
        if job.get("status") != "running":
            continue
        params = job.get("params") if isinstance(job.get("params"), dict) else {}
        if params.get("year") == year and params.get("month") == month:
            return str(params.get("mode") or "")
    return None

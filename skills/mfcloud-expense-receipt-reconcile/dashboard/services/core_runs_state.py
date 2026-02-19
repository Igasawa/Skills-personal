from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .core_orders import _collect_excluded_pdfs, _load_exclusions, _read_workflow
from .core_manual import _provider_inbox_status_for_ym
from .core_runs_audit import _coerce_non_negative_int
from .core_runs_paths import (
    _audit_log_path,
    _mf_draft_actions_path,
    _preflight_global_path,
    _running_mode_for_ym,
)
from .core_shared import SKILL_ROOT, _artifact_root, _read_json, _read_jsonl, _write_json

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
        mf_expense_id = str(ev.get("mf_expense_id") or "").strip()
        if not mf_expense_id:
            continue
        action = str(ev.get("action") or "").strip()
        ts = str(ev.get("ts") or "").strip() or None

        item = _get_item(mf_expense_id)
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


def _build_mf_summary(reports_dir: Path, mf_draft_payload: Any) -> dict[str, Any]:
    missing_candidates_value: int | None = None
    missing_payload = _read_json(reports_dir / "missing_evidence_candidates.json")
    if isinstance(missing_payload, dict):
        counts = missing_payload.get("counts")
        if isinstance(counts, dict):
            missing_candidates_value = _coerce_non_negative_int(counts.get("mf_missing_evidence"))
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
    archive_state["can_archive"] = bool(amazon_done or rakuten_done)

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


def _mark_preflight_started(year: int, month: int) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    data = {"status": "started", "started_at": ts, "year": year, "month": month}
    output_root = _artifact_root() / f"{year:04d}-{month:02d}"
    reports_dir = output_root / "reports"
    _write_json(reports_dir / "preflight.json", data)
    _write_json(_preflight_global_path(), data)


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


def _tail_text(path: Path, max_bytes: int = 5000) -> str:
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(0, 2)
                f.seek(-max_bytes, 1)
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


def _archive_outputs_for_ym(
    year: int,
    month: int,
    *,
    include_pdfs: bool = True,
    include_debug: bool = False,
    cleanup: bool = True,
    _load_exclusions_fn=_load_exclusions,
    _collect_excluded_pdfs_fn=_collect_excluded_pdfs,
    _coerce_non_negative_int_fn=_coerce_non_negative_int,
    _write_json_fn=_write_json,
    _subprocess_fn: Any = subprocess,
    _artifact_root_fn=_artifact_root,
    _skill_root=SKILL_ROOT,
    _read_json_fn=_read_json,
) -> dict[str, Any]:
    ym = f"{year:04d}-{month:02d}"
    output_root = _artifact_root_fn() / ym
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
    exclusions = _load_exclusions_fn(reports_dir)
    excluded_rows = _collect_excluded_pdfs_fn(output_root, ym, exclusions)
    excluded_manifest_path = reports_dir / "excluded_pdfs.json"
    _write_json_fn(
        excluded_manifest_path,
        {
            "ym": ym,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(excluded_rows),
            "rows": excluded_rows,
        },
    )

    script = _skill_root / "scripts" / "archive_outputs.ps1"
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

    res = _subprocess_fn.run(
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
            cleanup_removed = _coerce_non_negative_int_fn(text.split(":", 1)[1].strip(), default=0)
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


def _reset_step_state(
    year: int,
    month: int,
    step: str,
    actor: Any = None,
    *,
    _cancel_step_runs_fn=None,
    _read_json_fn=_read_json,
    _write_json_fn=_write_json,
    _delete_path_fn=_delete_path,
    _remove_mf_outputs_fn=_remove_mf_outputs,
    _append_audit_event_fn=None,
    _artifact_root_fn=_artifact_root,
) -> dict[str, Any]:
    spec = STEP_RESET_SPECS.get(step)
    if not spec:
        raise HTTPException(status_code=400, detail="Invalid step id for reset.")

    if _cancel_step_runs_fn is None:
        raise RuntimeError("cancel_step_runs dependency is required.")
    if _append_audit_event_fn is None:
        raise RuntimeError("append_audit_event dependency is required.")

    root = _artifact_root_fn() / f"{year:04d}-{month:02d}"
    reports_dir = root / "reports"
    clear_source = str(spec["clear_source"])
    clear_download = bool(spec["clear_download"])
    run_modes = set(spec["run_modes"])

    cancelled = _cancel_step_runs_fn(year=year, month=month, step=step, allowed_modes=run_modes, actor=actor)

    cleared_paths: list[str] = []
    if clear_download:
        orders_jsonl = root / clear_source / "orders.jsonl"
        if _delete_path_fn(orders_jsonl):
            cleared_paths.append(str(orders_jsonl))
        pdfs_dir = root / clear_source / "pdfs"
        if _delete_path_fn(pdfs_dir):
            cleared_paths.append(str(pdfs_dir))
        pdfs_dir.mkdir(parents=True, exist_ok=True)
        exclude_path = reports_dir / "exclude_orders.json"
        exclude_payload = _read_json_fn(exclude_path)
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
                        _write_json_fn(exclude_path, exclude_payload)
                        cleared_paths.append(str(exclude_path))
                    elif _delete_path_fn(exclude_path):
                        cleared_paths.append(str(exclude_path))

    workflow = _read_json_fn(reports_dir / "workflow.json")
    if not isinstance(workflow, dict):
        workflow = {}
    changed_workflow = False
    if isinstance(workflow, dict) and clear_source in workflow:
        workflow.pop(clear_source, None)
        changed_workflow = True
    if changed_workflow:
        _write_json_fn(reports_dir / "workflow.json", workflow)
        cleared_paths.append(str(reports_dir / "workflow.json"))

    cleared_paths.extend(_remove_mf_outputs_fn(reports_dir))

    _append_audit_event_fn(
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

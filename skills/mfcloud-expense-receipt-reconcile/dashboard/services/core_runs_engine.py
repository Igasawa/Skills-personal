from __future__ import annotations

import os
import re
import subprocess
import threading
import sys
from pathlib import Path
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from .core_shared import (
    DEFAULT_MFCLOUD_ACCOUNTS_URL,
    DEFAULT_RAKUTEN_URL,
    _artifact_root,
    _latest_running_job as _latest_running_job_common,
    _list_run_jobs as _list_run_jobs_common,
    _read_json,
    _running_job_exists as _running_job_exists_common,
    _runs_root,
    _write_json,
    SKILL_ROOT,
)
from .core_runs_audit import _append_audit_event, _capture_failed_run_incident, _safe_int, _normalize_actor
from .core_runs_state import (
    _infer_run_exit_code_from_log,
    _mark_preflight_started,
    _record_download_result,
    _remove_reconcile_outputs_only,
    _reset_workflow_for_redownload,
)
from .core_runs_validation import _assert_run_mode_allowed


def _pid_alive(
    pid: Any,
    *,
    _os=os,
    _subprocess=subprocess,
    _re=re,
) -> bool:
    if not pid:
        return False
    try:
        pid_int = int(pid)
    except Exception:
        return False
    if _os.name == "nt":
        try:
            out = _subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid_int}"],
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return True
        return _re.search(rf"\b{pid_int}\b", out) is not None
    try:
        _os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True
    return True


def _terminate_pid(
    pid: Any,
    *,
    _safe_int_fn=_safe_int,
    _os=os,
    _subprocess=subprocess,
) -> None:
    pid_int = _safe_int_fn(pid)
    if pid_int is None:
        return
    if _os.name == "nt":
        _subprocess.run(
            ["taskkill", "/PID", str(pid_int), "/T", "/F"],
            stdout=_subprocess.DEVNULL if hasattr(_subprocess, "DEVNULL") else subprocess.DEVNULL,
            stderr=_subprocess.DEVNULL if hasattr(_subprocess, "DEVNULL") else subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        _os.kill(pid_int, 9)
    except Exception:
        pass


def _run_worker(
    process,
    meta_path,
    *,
    _read_json_fn=_read_json,
    _write_json_fn=_write_json,
    _safe_int_fn=_safe_int,
    _append_audit_event_fn=_append_audit_event,
    _capture_failed_run_incident_fn=_capture_failed_run_incident,
    _record_download_result_fn=_record_download_result,
    _datetime_now=datetime.now,
) -> None:
    exit_code = process.wait()
    meta = _read_json_fn(meta_path) or {}
    meta["status"] = "success" if exit_code == 0 else "failed"
    meta["finished_at"] = _datetime_now().isoformat(timespec="seconds")
    meta["returncode"] = exit_code
    _write_json_fn(meta_path, meta)
    params = meta.get("params") if isinstance(meta.get("params"), dict) else {}
    year = _safe_int_fn(params.get("year"))
    month = _safe_int_fn(params.get("month"))
    if year is None or month is None:
        return
    mode = str(params.get("mode") or "unknown")
    _record_download_result_fn(year, month, mode, exit_code)
    if exit_code != 0:
        _capture_failed_run_incident_fn(
            meta_path=meta_path,
            meta=meta,
            reason="worker_exit",
            inferred_from="process_wait",
        )
    _append_audit_event_fn(
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


def _reconcile_running_jobs(
    *,
    _runs_root_fn=_runs_root,
    _read_json_fn=_read_json,
    _write_json_fn=_write_json,
    _safe_int_fn=_safe_int,
    _pid_alive_fn=_pid_alive,
    _infer_run_exit_code_from_log_fn=_infer_run_exit_code_from_log,
    _record_download_result_fn=_record_download_result,
    _append_audit_event_fn=_append_audit_event,
    _capture_failed_run_incident_fn=_capture_failed_run_incident,
    _datetime_now=datetime.now,
) -> None:
    root = _runs_root_fn()
    if not root.exists():
        return
    for p in root.glob("run_*.json"):
        data = _read_json_fn(p)
        if not isinstance(data, dict):
            continue
        if data.get("status") != "running":
            continue
        if _pid_alive_fn(data.get("pid")):
            continue
        latest = _read_json_fn(p)
        if not isinstance(latest, dict):
            continue
        if latest.get("status") != "running":
            continue
        data = latest
        if data.get("log_path"):
            log_path = Path(str(data.get("log_path")))
        else:
            log_path = p.with_suffix(".log")
        inferred_returncode, inferred_from = _infer_run_exit_code_from_log_fn(log_path)
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
            data["finished_at"] = _datetime_now().isoformat(timespec="seconds")
        _write_json_fn(p, data)
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        year = _safe_int_fn(params.get("year"))
        month = _safe_int_fn(params.get("month"))
        if year is None or month is None:
            continue
        mode = str(params.get("mode") or "unknown")
        returncode = _safe_int_fn(data.get("returncode"))
        if returncode is None:
            returncode = -1
        _record_download_result_fn(year, month, mode, returncode)
        if returncode != 0:
            _capture_failed_run_incident_fn(
                meta_path=p,
                meta=data,
                reason=reason,
                inferred_from=inferred_from,
            )
        _append_audit_event_fn(
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


def _scan_run_jobs(
    *,
    _reconcile_running_jobs_fn=None,
    _runs_root_fn=_runs_root,
    _read_json_fn=_read_json,
) -> list[dict[str, Any]]:
    reconcile_jobs = _reconcile_running_jobs_fn or _reconcile_running_jobs
    reconcile_jobs(_runs_root_fn=_runs_root_fn, _read_json_fn=_read_json_fn)
    return _list_run_jobs_common(
        runs_root_fn=_runs_root_fn(),
        read_json_fn=_read_json_fn,
    )


def _running_job_exists(*, _scan_run_jobs_fn=_scan_run_jobs) -> bool:
    return _running_job_exists_common(_scan_run_jobs_fn())


def _get_latest_running_job(*, _scan_run_jobs_fn=_scan_run_jobs) -> dict[str, Any] | None:
    return _latest_running_job_common(_scan_run_jobs_fn())


def _cancel_step_runs(
    *,
    year: int,
    month: int,
    step: str,
    allowed_modes: set[str],
    actor: Any = None,
    _scan_run_jobs_fn=_scan_run_jobs,
    _safe_int_fn=_safe_int,
    _terminate_pid_fn=_terminate_pid,
    _write_json_fn=_write_json,
    _append_audit_event_fn=_append_audit_event,
    _runs_root_fn=_runs_root,
    _datetime_now=datetime.now,
) -> list[str]:
    cancelled_run_ids: list[str] = []
    for job in _scan_run_jobs_fn():
        if job.get("status") != "running":
            continue
        params = job.get("params") if isinstance(job.get("params"), dict) else {}
        if _safe_int_fn(params.get("year")) != year or _safe_int_fn(params.get("month")) != month:
            continue
        mode = str(params.get("mode") or "")
        if mode not in allowed_modes:
            raise HTTPException(
                status_code=409,
                detail=f"Step '{step}' cannot reset mode '{mode}' for {year:04d}-{month:02d}.",
            )
        run_id = str(job.get("run_id") or "")
        if not run_id:
            continue
        _terminate_pid_fn(job.get("pid"))
        job["status"] = "cancelled"
        job["finished_at"] = _datetime_now().isoformat(timespec="seconds")
        job["returncode"] = -1
        _write_json_fn(_runs_root_fn() / f"{run_id}.json", job)
        cancelled_run_ids.append(run_id)
        _append_audit_event_fn(
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


def _start_run(
    payload: dict[str, Any],
    *,
    _running_job_exists_fn=_running_job_exists,
    _assert_run_mode_allowed_fn=_assert_run_mode_allowed,
    _normalize_actor_fn=_normalize_actor,
    _append_audit_event_fn=_append_audit_event,
    _mark_preflight_started_fn=_mark_preflight_started,
    _reset_workflow_for_redownload_fn=_reset_workflow_for_redownload,
    _remove_reconcile_outputs_only_fn=_remove_reconcile_outputs_only,
    _runs_root_fn=_runs_root,
    _write_json_fn=_write_json,
    _subprocess=subprocess,
    _threading=threading,
    _os=os,
    _artifact_root_fn=_artifact_root,
    _datetime_now=datetime.now,
    _run_worker_fn=_run_worker,
    _default_mfc_accounts: str = DEFAULT_MFCLOUD_ACCOUNTS_URL,
    _default_rakuten_url: str = DEFAULT_RAKUTEN_URL,
    _skill_root=SKILL_ROOT,
) -> dict[str, Any]:
    if _running_job_exists_fn():
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
    actor = _normalize_actor_fn(payload.get("_audit_actor"))
    try:
        _assert_run_mode_allowed_fn(year, month, mode)
    except HTTPException as exc:
        _append_audit_event_fn(
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
        _append_audit_event_fn(
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
    rakuten_orders_url = str(payload.get("rakuten_orders_url") or _default_rakuten_url)

    runs_root = _runs_root_fn()
    runs_root.mkdir(parents=True, exist_ok=True)

    ts = _datetime_now().strftime("%Y%m%d_%H%M%S_%f")
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
        _mark_preflight_started_fn(year, month)
        cmd += ["--preflight", "--mfcloud-accounts-url", _default_mfc_accounts]
        if mode == "preflight_mf":
            cmd += ["--skip-amazon", "--skip-rakuten"]
    elif mode in {"amazon_download", "amazon_print"}:
        if mode == "amazon_download":
            _reset_workflow_for_redownload_fn(year, month, "amazon")
        cmd += ["--skip-mfcloud", "--skip-rakuten", "--skip-reconcile"]
        if mode == "amazon_print":
            cmd += ["--print-list", "--print-sources", "amazon"]
    elif mode in {"rakuten_download", "rakuten_print"}:
        if mode == "rakuten_download":
            _reset_workflow_for_redownload_fn(year, month, "rakuten")
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
        _remove_reconcile_outputs_only_fn(_artifact_root_fn() / f"{year:04d}-{month:02d}" / "reports")
        cmd += ["--skip-amazon", "--skip-rakuten"]
        if bool(payload.get("mf_draft_create", True)):
            cmd += ["--mf-draft-create"]
        output_root = _artifact_root_fn() / f"{year:04d}-{month:02d}"
        if (output_root / "rakuten" / "orders.jsonl").exists():
            cmd += ["--enable-rakuten"]

    env = _os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    with log_path.open("w", encoding="utf-8") as log:
        process = _subprocess.Popen(
            cmd,
            cwd=str(_skill_root),
            stdout=log,
            stderr=log,
            env=env,
        )

    meta = {
        "run_id": run_id,
        "status": "running",
        "started_at": _datetime_now().isoformat(timespec="seconds"),
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
    _write_json_fn(meta_path, meta)
    _append_audit_event_fn(
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

    watcher = _threading.Thread(target=_run_worker_fn, args=(process, meta_path), daemon=True)
    watcher.start()

    return {"run_id": run_id, "status": "running"}

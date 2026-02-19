from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import re
import subprocess
import sys
import threading
from typing import Any

from fastapi import HTTPException

from .core_manual import _provider_inbox_status_for_ym
from .core_orders import _collect_excluded_pdfs, _load_exclusions, _read_workflow
from .core_shared import (
    DEFAULT_MFCLOUD_ACCOUNTS_URL,
    DEFAULT_RAKUTEN_URL,
    RUN_ID_RE,
    SKILL_ROOT,
    _artifact_root,
    _read_json,
    _read_jsonl,
    _runs_root,
    _write_json,
)
from . import core_runs_audit as _audit
from . import core_runs_engine as _engine
from . import core_runs_paths as _paths
from . import core_runs_state as _state
from . import core_runs_validation as _validation


def _preflight_global_path() -> Path:
    return _paths._preflight_global_path()


def _audit_log_path(year: int, month: int) -> Path:
    return _paths._audit_log_path(year, month)


def _mf_draft_actions_path(year: int, month: int) -> Path:
    return _paths._mf_draft_actions_path(year, month)


def _mf_draft_actions_summary_for_ym(
    year: int,
    month: int,
    *,
    limit_events: int = 0,
) -> dict[str, Any]:
    return _state._mf_draft_actions_summary_for_ym(year, month, limit_events=limit_events)

def _safe_int(value: Any) -> int | None:
    return _audit._safe_int(value)


def _coerce_non_negative_int(value: Any, default: int = 0) -> int:
    return _audit._coerce_non_negative_int(value, default=default)


def _normalize_actor(actor: Any) -> dict[str, Any]:
    return _audit._normalize_actor(actor)


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
    return _audit._append_audit_event(
        year=year,
        event_type=event_type,
        action=action,
        status=status,
        actor=actor,
        source=source,
        month=month,
        mode=mode,
        run_id=run_id,
        details=details,
        _audit_log_path_fn=_paths._audit_log_path,
        _normalize_actor_fn=_normalize_actor,
    )


def _capture_failed_run_incident(
    *,
    meta_path: Path,
    meta: dict[str, Any],
    reason: str,
    inferred_from: str = "",
) -> None:
    return _audit._capture_failed_run_incident(
        meta_path=meta_path,
        meta=meta,
        reason=reason,
        inferred_from=inferred_from,
        _safe_int_fn=_safe_int,
        _subprocess_fn=subprocess,
        _write_json_fn=_write_json,
        _append_audit_event_fn=_append_audit_event,
        _audit_log_path_fn=_paths._audit_log_path,
        _skill_root=SKILL_ROOT,
    )


def _build_mf_summary(reports_dir: Path, mf_draft_payload: Any) -> dict[str, Any]:
    return _state._build_mf_summary(reports_dir, mf_draft_payload)


def _mf_bulk_upload_state_for_ym(reports_dir: Path) -> dict[str, Any]:
    return _state._mf_bulk_upload_state_for_ym(reports_dir)


def _mf_csv_import_state_for_ym(reports_dir: Path) -> dict[str, Any]:
    return _state._mf_csv_import_state_for_ym(reports_dir)


def _latest_archive_state_for_ym(year: int, month: int) -> dict[str, Any]:
    return _state._latest_archive_state_for_ym(year, month)


def _workflow_state_for_ym(year: int, month: int) -> dict[str, Any]:
    return _state._workflow_state_for_ym(year, month)


def _reset_workflow_for_redownload(year: int, month: int, source: str) -> None:
    return _state._reset_workflow_for_redownload(year, month, source)


def _mark_preflight_started(year: int, month: int) -> None:
    return _state._mark_preflight_started(year, month)


def _record_download_result(year: int, month: int, mode: str, exit_code: int) -> None:
    return _state._record_download_result(year, month, mode, exit_code)


def _archive_outputs_for_ym(
    year: int,
    month: int,
    *,
    include_pdfs: bool = True,
    include_debug: bool = False,
    cleanup: bool = True,
) -> dict[str, Any]:
    return _state._archive_outputs_for_ym(
        year,
        month,
        include_pdfs=include_pdfs,
        include_debug=include_debug,
        cleanup=cleanup,
        _load_exclusions_fn=_load_exclusions,
        _collect_excluded_pdfs_fn=_collect_excluded_pdfs,
        _coerce_non_negative_int_fn=_coerce_non_negative_int,
        _write_json_fn=_write_json,
        _subprocess_fn=subprocess,
        _artifact_root_fn=_artifact_root,
        _read_json_fn=_read_json,
    )


def _tail_text(path: Path, max_bytes: int = 5000) -> str:
    return _state._tail_text(path, max_bytes=max_bytes)


def _infer_run_exit_code_from_log(log_path: Path) -> tuple[int | None, str | None]:
    return _state._infer_run_exit_code_from_log(log_path)


def _remove_mf_outputs(reports_dir: Path) -> list[str]:
    return _state._remove_mf_outputs(reports_dir)


def _remove_reconcile_outputs_only(reports_dir: Path) -> list[str]:
    return _state._remove_reconcile_outputs_only(reports_dir)


def _cancel_step_runs(
    *,
    year: int,
    month: int,
    step: str,
    allowed_modes: set[str],
    actor: Any = None,
) -> list[str]:
    return _engine._cancel_step_runs(
        year=year,
        month=month,
        step=step,
        allowed_modes=allowed_modes,
        actor=actor,
        _scan_run_jobs_fn=_scan_run_jobs,
        _safe_int_fn=_safe_int,
        _terminate_pid_fn=_terminate_pid,
        _write_json_fn=_write_json,
        _append_audit_event_fn=_append_audit_event,
    )


def _reset_step_state(year: int, month: int, step: str, actor: Any = None) -> dict[str, Any]:
    return _state._reset_step_state(
        year,
        month,
        step,
        actor=actor,
        _cancel_step_runs_fn=_cancel_step_runs,
        _read_json_fn=_read_json,
        _write_json_fn=_write_json,
        _delete_path_fn=_state._delete_path,
        _remove_mf_outputs_fn=_remove_mf_outputs,
        _append_audit_event_fn=_append_audit_event,
        _artifact_root_fn=_artifact_root,
    )


def _pid_alive(pid: Any) -> bool:
    return _engine._pid_alive(pid, _os=os, _subprocess=subprocess, _re=re)


def _terminate_pid(pid: Any) -> None:
    return _engine._terminate_pid(pid, _safe_int_fn=_safe_int, _os=os, _subprocess=subprocess)


def _scan_run_jobs() -> list[dict[str, Any]]:
    return _engine._scan_run_jobs(
        _reconcile_running_jobs_fn=_reconcile_running_jobs,
        _runs_root_fn=_runs_root,
        _read_json_fn=_read_json,
    )


def _running_job_exists() -> bool:
    return _engine._running_job_exists(_scan_run_jobs_fn=_scan_run_jobs)


def _get_latest_running_job() -> dict[str, Any] | None:
    return _engine._get_latest_running_job(_scan_run_jobs_fn=_scan_run_jobs)


def _run_worker(process, meta_path: Path) -> None:
    return _engine._run_worker(
        process,
        meta_path,
        _read_json_fn=_read_json,
        _write_json_fn=_write_json,
        _safe_int_fn=_safe_int,
        _append_audit_event_fn=_append_audit_event,
        _capture_failed_run_incident_fn=_capture_failed_run_incident,
        _record_download_result_fn=_record_download_result,
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
) -> None:
    return _engine._reconcile_running_jobs(
        _runs_root_fn=_runs_root_fn,
        _read_json_fn=_read_json_fn,
        _write_json_fn=_write_json_fn,
        _safe_int_fn=_safe_int_fn,
        _pid_alive_fn=_pid_alive_fn,
        _infer_run_exit_code_from_log_fn=_infer_run_exit_code_from_log_fn,
        _record_download_result_fn=_record_download_result_fn,
        _append_audit_event_fn=_append_audit_event_fn,
        _capture_failed_run_incident_fn=_capture_failed_run_incident_fn,
    )


def _start_run(payload: dict[str, Any]) -> dict[str, Any]:
    return _engine._start_run(
        payload,
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
        _datetime_now=datetime.now,
        _run_worker_fn=_run_worker,
        _default_mfc_accounts=DEFAULT_MFCLOUD_ACCOUNTS_URL,
        _default_rakuten_url=DEFAULT_RAKUTEN_URL,
        _skill_root=SKILL_ROOT,
    )


def _assert_run_mode_allowed(year: int, month: int, mode: str) -> None:
    return _validation._assert_run_mode_allowed(year, month, mode)


def _assert_source_action_allowed(year: int, month: int, source: str, action: str) -> None:
    return _validation._assert_source_action_allowed(year, month, source, action)


def _assert_archive_allowed(year: int, month: int) -> None:
    return _validation._assert_archive_allowed(year, month)


def _safe_ym(ym: str) -> str:
    return _paths._safe_ym(ym)


def _safe_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id.")
    return run_id


def _split_ym(ym: str) -> tuple[int, int]:
    return int(ym[:4]), int(ym[5:7])


def _running_mode_for_ym(year: int, month: int) -> str | None:
    return _paths._running_mode_for_ym(year, month)

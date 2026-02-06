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
    _runs_root,
    _write_json,
)
from .core_orders import _read_workflow

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


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


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


def _workflow_state_for_ym(year: int, month: int) -> dict[str, Any]:
    ym = f"{year:04d}-{month:02d}"
    root = _artifact_root() / ym
    reports_dir = root / "reports"
    workflow = _read_workflow(reports_dir)

    local_preflight = _read_json(reports_dir / "preflight.json")
    global_preflight = _read_json(_preflight_global_path())
    preflight_done = _is_preflight_success(local_preflight, year=year, month=month) or _is_preflight_success(
        global_preflight,
        year=year,
        month=month,
    )
    amazon_downloaded = (root / "amazon" / "orders.jsonl").exists()
    rakuten_downloaded = (root / "rakuten" / "orders.jsonl").exists()
    amazon_confirmed = bool((workflow.get("amazon") or {}).get("confirmed_at"))
    amazon_printed = bool((workflow.get("amazon") or {}).get("printed_at"))
    rakuten_confirmed = bool((workflow.get("rakuten") or {}).get("confirmed_at"))
    rakuten_printed = bool((workflow.get("rakuten") or {}).get("printed_at"))
    mf_reconciled = (reports_dir / "missing_evidence_candidates.json").exists()
    amazon_done = amazon_confirmed and amazon_printed
    rakuten_done = rakuten_confirmed and rakuten_printed

    next_step = "done"
    if not preflight_done:
        next_step = "preflight"
    elif mf_reconciled:
        next_step = "done"
    elif amazon_done or rakuten_done:
        next_step = "mf_reconcile"
    elif amazon_downloaded and not amazon_done:
        next_step = "amazon_decide_print"
    elif rakuten_downloaded and not rakuten_done:
        next_step = "rakuten_decide_print"
    elif not amazon_downloaded and not rakuten_downloaded:
        next_step = "amazon_or_rakuten_download"
    elif not amazon_downloaded:
        next_step = "amazon_download"
    elif not rakuten_downloaded:
        next_step = "rakuten_download"

    allowed_run_modes: list[str] = ["preflight"]
    if preflight_done:
        allowed_run_modes.extend(["amazon_download", "rakuten_download"])
        if amazon_downloaded:
            allowed_run_modes.append("amazon_print")
        if rakuten_downloaded:
            allowed_run_modes.append("rakuten_print")
        if amazon_done or rakuten_done:
            allowed_run_modes.append("mf_reconcile")
    allowed_run_modes = list(dict.fromkeys(allowed_run_modes))

    return {
        "ym": ym,
        "preflight": {"done": preflight_done},
        "amazon": {"downloaded": amazon_downloaded, "confirmed": amazon_confirmed, "printed": amazon_printed},
        "rakuten": {"downloaded": rakuten_downloaded, "confirmed": rakuten_confirmed, "printed": rakuten_printed},
        "mf": {"reconciled": mf_reconciled},
        "next_step": next_step,
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
        for key in ("amazon", "rakuten"):
            if key in workflow:
                workflow.pop(key, None)
                changed = True
    elif source == "rakuten":
        if "rakuten" in workflow:
            workflow.pop("rakuten", None)
            changed = True
    if changed:
        _write_json(reports_dir / "workflow.json", workflow)


def _assert_run_mode_allowed(year: int, month: int, mode: str) -> None:
    if mode == "preflight":
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
        data["status"] = "failed"
        if not data.get("finished_at"):
            data["finished_at"] = datetime.now().isoformat(timespec="seconds")
        if data.get("returncode") is None:
            data["returncode"] = -1
        _write_json(p, data)
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        year = _safe_int(params.get("year"))
        month = _safe_int(params.get("month"))
        if year is None or month is None:
            continue
        _append_audit_event(
            year=year,
            month=month,
            event_type="run",
            action=str(params.get("mode") or "unknown"),
            status="failed",
            actor=data.get("actor"),
            mode=str(params.get("mode") or ""),
            run_id=str(data.get("run_id") or ""),
            details={"reason": "process_ended_without_final_status", "returncode": data.get("returncode")},
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
    valid_modes = {"preflight", "amazon_download", "rakuten_download", "amazon_print", "rakuten_print", "mf_reconcile"}
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

    if mode == "preflight":
        _mark_preflight_started(year, month)
        cmd += ["--preflight", "--mfcloud-accounts-url", DEFAULT_MFCLOUD_ACCOUNTS_URL]
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
        cmd += ["--skip-amazon", "--skip-rakuten"]
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

from __future__ import annotations

import os
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


def _preflight_global_path() -> Path:
    return _artifact_root() / "_preflight.json"


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
        return re.search(rf"\\b{pid_int}\\b", out) is not None
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
    mfcloud_url = str(payload.get("mfcloud_url") or "").strip()
    if mode == "mf_reconcile" and not mfcloud_url:
        raise HTTPException(status_code=400, detail="MF Cloud expense list URL is required.")

    rakuten_enabled = bool(payload.get("rakuten_enabled"))
    notes = str(payload.get("notes") or "").strip()
    rakuten_orders_url = str(payload.get("rakuten_orders_url") or DEFAULT_RAKUTEN_URL)

    runs_root = _runs_root()
    runs_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
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
        cmd += ["--skip-mfcloud", "--skip-rakuten", "--skip-reconcile"]
        if mode == "amazon_print":
            cmd += ["--print-list", "--print-sources", "amazon"]
    elif mode in {"rakuten_download", "rakuten_print"}:
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

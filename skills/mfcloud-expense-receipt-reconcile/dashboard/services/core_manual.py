from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from fastapi import HTTPException

from .core_shared import SKILL_ROOT, _artifact_root, _ax_home, _read_json

DEFAULT_MFCLOUD_TRANSACTIONS_URL = "https://expense.moneyforward.com/transactions"


def _manual_month_root_for_ym(year: int, month: int) -> Path:
    return _artifact_root() / f"{year:04d}-{month:02d}"


def _manual_inbox_dir_for_ym(year: int, month: int, *, create: bool = True) -> Path:
    path = _manual_month_root_for_ym(year, month) / "manual" / "inbox"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _mf_bulk_upload_inbox_dir_for_ym(year: int, month: int, *, create: bool = True) -> Path:
    path = _manual_month_root_for_ym(year, month) / "mf_bulk_upload" / "inbox"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_mfcloud_storage_state_for_ym(year: int, month: int) -> Path:
    output_root = _manual_month_root_for_ym(year, month)
    run_config_path = output_root / "run_config.resolved.json"
    run_config = _read_json(run_config_path)
    if isinstance(run_config, dict):
        sessions = run_config.get("sessions")
        if isinstance(sessions, dict):
            raw = str(sessions.get("mfcloud_storage_state") or "").strip()
            if raw:
                candidate = Path(raw).expanduser()
                return candidate
    return _ax_home() / "sessions" / "mfcloud-expense.storage.json"


def _import_manual_receipts_for_ym(year: int, month: int) -> dict[str, Any]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12.")

    output_root = _manual_month_root_for_ym(year, month)
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        from scripts.manual_receipt_import import import_manual_receipts_for_month
    except Exception as exc:  # pragma: no cover - import failure should be rare
        raise HTTPException(status_code=500, detail=f"manual import module load failed: {exc}") from exc

    try:
        result = import_manual_receipts_for_month(output_root, year, month)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"manual receipt import failed: {exc}") from exc

    return {
        "status": "ok",
        "ym": result.get("ym"),
        "found_pdfs": int(result.get("found_pdfs") or 0),
        "imported": int(result.get("imported") or 0),
        "imported_missing_amount": int(result.get("imported_missing_amount") or 0),
        "skipped_duplicates": int(result.get("skipped_duplicates") or 0),
        "failed": int(result.get("failed") or 0),
        "inbox_dir": str(result.get("inbox_dir") or ""),
        "pdfs_dir": str(result.get("pdfs_dir") or ""),
        "orders_jsonl": str(result.get("orders_jsonl") or ""),
        "errors_jsonl": str(result.get("errors_jsonl") or ""),
        "report_json": str(result.get("report_json") or ""),
    }


def _run_mf_bulk_upload_for_ym(
    year: int,
    month: int,
    *,
    auth_handoff: bool = True,
    headed: bool = True,
    slow_mo_ms: int = 0,
    transactions_url: str = DEFAULT_MFCLOUD_TRANSACTIONS_URL,
) -> dict[str, Any]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12.")

    output_root = _manual_month_root_for_ym(year, month)
    output_root.mkdir(parents=True, exist_ok=True)
    inbox_dir = _mf_bulk_upload_inbox_dir_for_ym(year, month, create=True)
    reports_dir = output_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = output_root / "debug" / "mf_bulk_upload"
    debug_dir.mkdir(parents=True, exist_ok=True)

    script = SKILL_ROOT / "scripts" / "mfcloud_bulk_upload.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail=f"mfcloud bulk upload script not found: {script}")

    storage_state = _resolve_mfcloud_storage_state_for_ym(year, month)
    if not storage_state.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "MF Cloud storage state was not found. "
                f"Expected: {storage_state}. Run preflight login first."
            ),
        )

    out_json = reports_dir / "mf_bulk_upload_result.json"
    cmd = [
        sys.executable,
        str(script),
        "--year",
        str(year),
        "--month",
        str(month),
        "--storage-state",
        str(storage_state),
        "--transactions-url",
        str(transactions_url),
        "--inbox-dir",
        str(inbox_dir),
        "--out-json",
        str(out_json),
        "--debug-dir",
        str(debug_dir),
        "--slow-mo-ms",
        str(max(0, int(slow_mo_ms))),
    ]
    if auth_handoff:
        cmd.append("--auth-handoff")
    if headed:
        cmd.append("--headed")
    else:
        cmd.append("--headless")

    res = subprocess.run(cmd, cwd=str(SKILL_ROOT), capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=(
                "mfcloud_bulk_upload.py failed:\n"
                f"cmd: {cmd}\n"
                f"exit: {res.returncode}\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            ),
        )

    payload: dict[str, Any] | None = None
    for line in reversed((res.stdout or "").splitlines()):
        text = str(line).strip()
        if not text.startswith("{") or not text.endswith("}"):
            continue
        try:
            maybe = json.loads(text)
        except Exception:
            continue
        if isinstance(maybe, dict):
            payload = maybe
            break

    if not payload:
        raise HTTPException(
            status_code=500,
            detail=(
                "mfcloud_bulk_upload.py returned no JSON payload.\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            ),
        )

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return {
        "status": "ok",
        "ym": f"{year:04d}-{month:02d}",
        "transactions_url": str(transactions_url),
        "inbox_dir": str(inbox_dir),
        "result_json": str(out_json),
        "files_found": int(data.get("files_found") or 0) if isinstance(data, dict) else 0,
        "submitted_count": int(data.get("submitted_count") or 0) if isinstance(data, dict) else 0,
        "queued_count": int(data.get("queued_count") or 0) if isinstance(data, dict) else 0,
        "read_count": int(data.get("read_count") or 0) if isinstance(data, dict) else 0,
        "archived_dir": str(data.get("archived_dir") or "") if isinstance(data, dict) else "",
    }

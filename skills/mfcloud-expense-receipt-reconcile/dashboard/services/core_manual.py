from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from fastapi import HTTPException

from .core_shared import SKILL_ROOT, _artifact_root, _ax_home, _read_json

DEFAULT_MFCLOUD_TRANSACTIONS_URL = "https://expense.moneyforward.com/transactions"
DEFAULT_MFCLOUD_TRANSACTIONS_IMPORT_URL = "https://expense.moneyforward.com/import_transactions/new"
PROVIDER_KEYS: tuple[str, ...] = ("aquavoice", "claude", "chatgpt", "gamma")
PROVIDER_LABELS: dict[str, str] = {
    "aquavoice": "Aqua Voice",
    "claude": "Claude",
    "chatgpt": "ChatGPT",
    "gamma": "Gamma",
}
PROVIDER_STORAGE_STATE_NAMES: dict[str, str] = {
    "aquavoice": "aquavoice",
    "claude": "claude",
    "chatgpt": "chatgpt",
    "gamma": "gamma",
}
ALLOWED_RECEIPT_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}
MANUAL_SOURCE_DIR_ENV = "AX_MANUAL_RECEIPT_SOURCE_DIR"
MANUAL_SOURCE_MODE_ENV = "AX_MANUAL_RECEIPT_SOURCE_MODE"
MANUAL_SOURCE_DRY_RUN_ENV = "AX_MANUAL_RECEIPT_SOURCE_DRY_RUN"
MANUAL_SOURCE_DEFAULT_MODE = "copy"
MANUAL_SOURCE_DEFAULT_DIR = r"G:\マイドライブ\_ax\gaspdf"


def _manual_month_root_for_ym(year: int, month: int) -> Path:
    return _artifact_root() / f"{year:04d}-{month:02d}"


def _normalize_provider(provider: str) -> str:
    name = str(provider or "").strip().lower()
    if name not in PROVIDER_KEYS:
        raise HTTPException(status_code=400, detail="Invalid provider.")
    return name


def _manual_inbox_dir_for_ym(year: int, month: int, *, create: bool = True) -> Path:
    path = _manual_month_root_for_ym(year, month) / "manual" / "inbox"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _provider_inbox_dir_for_ym(year: int, month: int, provider: str, *, create: bool = True) -> Path:
    name = _normalize_provider(provider)
    path = _manual_inbox_dir_for_ym(year, month, create=create) / name
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _provider_inbox_dirs_for_ym(year: int, month: int, *, create: bool = True) -> dict[str, Path]:
    return {
        provider: _provider_inbox_dir_for_ym(year, month, provider, create=create)
        for provider in PROVIDER_KEYS
    }


def _iter_receipt_files(root_dir: Path) -> list[Path]:
    if not root_dir.exists():
        return []
    out: list[Path] = []
    for path in sorted(root_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_RECEIPT_SUFFIXES:
            continue
        try:
            rel = path.relative_to(root_dir)
        except Exception:
            rel = path
        if any(str(part).startswith("_") for part in rel.parts):
            continue
        out.append(path)
    return out


def _derive_skipped_bucket_dir(moved_to: str) -> Path | None:
    raw = str(moved_to or "").strip()
    if not raw:
        return None
    moved = Path(raw).expanduser()
    parent = moved.parent
    if not str(parent):
        return None
    parts = list(parent.parts)
    lowered = [str(part).lower() for part in parts]
    if "_skipped" in lowered:
        idx = lowered.index("_skipped")
        if idx + 1 < len(parts):
            return Path(*parts[: idx + 2])
    return parent


def _extract_skipped_dirs_and_files(rows: Any) -> tuple[list[str], list[str]]:
    if not isinstance(rows, list):
        return [], []
    dirs: list[str] = []
    files: list[str] = []
    seen_dirs: set[str] = set()
    seen_files: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        moved_to = str(row.get("moved_to") or "").strip()
        skipped_dir = _derive_skipped_bucket_dir(moved_to) if moved_to else None
        if skipped_dir is not None:
            skipped_dir_text = str(skipped_dir)
            if skipped_dir_text and skipped_dir_text not in seen_dirs:
                seen_dirs.add(skipped_dir_text)
                dirs.append(skipped_dir_text)
        file_name = str(row.get("file") or "").strip()
        if not file_name and moved_to:
            file_name = Path(moved_to).name
        if file_name and file_name not in seen_files:
            seen_files.add(file_name)
            files.append(file_name)
    return dirs, files


def _manual_source_dir(raw: str | Path | None = None) -> Path | None:
    if raw is not None:
        normalized = str(raw).strip()
        if not normalized:
            return None
        return Path(normalized).expanduser()

    raw = str(os.environ.get(MANUAL_SOURCE_DIR_ENV, "")).strip()
    if raw:
        return Path(raw).expanduser()

    if not MANUAL_SOURCE_DEFAULT_DIR:
        return None
    path = Path(MANUAL_SOURCE_DEFAULT_DIR).expanduser()
    if path.exists() and path.is_dir():
        return path
    return None


def _manual_source_mode(raw: str | None = None) -> str:
    if raw is None:
        raw = str(os.environ.get(MANUAL_SOURCE_MODE_ENV, MANUAL_SOURCE_DEFAULT_MODE))
    raw = str(raw).strip().lower()
    if raw in {"copy", "move"}:
        return raw
    return MANUAL_SOURCE_DEFAULT_MODE


def _manual_source_dry_run(raw: bool | None = None) -> bool:
    if raw is not None:
        return bool(raw)
    raw = str(os.environ.get(MANUAL_SOURCE_DRY_RUN_ENV, "")).strip().lower()
    return raw in {"1", "true", "on", "yes"}


def _provider_step_attempted_for_ym(year: int, month: int) -> bool:
    month_root = _manual_month_root_for_ym(year, month)
    provider_import_report = month_root / "manual" / "reports" / "provider_import_last.json"

    import_payload = _read_json(provider_import_report)
    if isinstance(import_payload, dict):
        ingestion_channel = str(import_payload.get("ingestion_channel") or "").strip().lower()
        if ingestion_channel == "provider_inbox":
            return True
        provider_filter = import_payload.get("provider_filter")
        if isinstance(provider_filter, list):
            normalized_filter = {str(value or "").strip().lower() for value in provider_filter}
            if any(provider in normalized_filter for provider in PROVIDER_KEYS):
                return True
    return False


def _provider_inbox_status_for_ym(year: int, month: int) -> dict[str, Any]:
    statuses: dict[str, dict[str, Any]] = {}
    attempted = _provider_step_attempted_for_ym(year, month)
    shared_inbox_dir = _manual_inbox_dir_for_ym(year, month, create=True)
    pending_total = len(_iter_receipt_files(shared_inbox_dir))
    provider_pending_total = 0
    for provider in PROVIDER_KEYS:
        provider_dir = _provider_inbox_dir_for_ym(year, month, provider, create=False)
        pending_files = len(_iter_receipt_files(provider_dir))
        provider_pending_total += pending_files
        statuses[provider] = {
            "label": PROVIDER_LABELS.get(provider, provider),
            "path": str(provider_dir),
            "pending_files": pending_files,
        }
    shared_pending_files = max(0, pending_total - provider_pending_total)
    statuses["shared"] = {
        "label": "共通フォルダ",
        "path": str(shared_inbox_dir),
        "pending_files": shared_pending_files,
    }
    return {
        "step_done": attempted and pending_total == 0,
        "attempted": attempted,
        "pending_total": pending_total,
        "providers": statuses,
    }


def _mf_bulk_upload_inbox_dir_for_ym(year: int, month: int, *, create: bool = True) -> Path:
    path = _manual_month_root_for_ym(year, month) / "mf_bulk_upload" / "inbox"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _mf_csv_import_inbox_dir_for_ym(year: int, month: int, *, create: bool = True) -> Path:
    path = _manual_month_root_for_ym(year, month) / "mf_csv_import" / "inbox"
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


def _resolve_provider_storage_state_for_ym(year: int, month: int, provider: str) -> Path:
    name = _normalize_provider(provider)
    output_root = _manual_month_root_for_ym(year, month)
    run_config_path = output_root / "run_config.resolved.json"
    run_config = _read_json(run_config_path)
    session_key = f"{name}_storage_state"
    if isinstance(run_config, dict):
        sessions = run_config.get("sessions")
        if isinstance(sessions, dict):
            raw = str(sessions.get(session_key) or "").strip()
            if raw:
                return Path(raw).expanduser()

    session_name = PROVIDER_STORAGE_STATE_NAMES.get(name, name)
    return _ax_home() / "sessions" / f"{session_name}.storage.json"


def _import_manual_receipts_for_ym(
    year: int,
    month: int,
    source_dir: str | Path | None = None,
    source_mode: str | None = None,
    source_dry_run: bool | None = None,
) -> dict[str, Any]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12.")

    output_root = _manual_month_root_for_ym(year, month)
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        from scripts.manual_receipt_import import import_manual_receipts_for_month
    except Exception as exc:  # pragma: no cover - import failure should be rare
        raise HTTPException(status_code=500, detail=f"manual import module load failed: {exc}") from exc

    try:
        result = import_manual_receipts_for_month(
            output_root,
            year,
            month,
            ingestion_channel="manual_inbox",
            source_dir=_manual_source_dir(source_dir),
            source_mode=_manual_source_mode(source_mode),
            source_dry_run=_manual_source_dry_run(source_dry_run),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"manual receipt import failed: {exc}") from exc

    return {
        "status": "ok",
        "ym": result.get("ym"),
        "source_import": result.get("source_import") if isinstance(result.get("source_import"), dict) else {},
        "found_pdfs": int(result.get("found_pdfs") or 0),
        "found_files": int(result.get("found_files") or result.get("found_pdfs") or 0),
        "imported": int(result.get("imported") or 0),
        "imported_missing_amount": int(result.get("imported_missing_amount") or 0),
        "skipped_duplicates": int(result.get("skipped_duplicates") or 0),
        "failed": int(result.get("failed") or 0),
        "provider_counts": result.get("provider_counts") if isinstance(result.get("provider_counts"), dict) else {},
        "inbox_dir": str(result.get("inbox_dir") or ""),
        "pdfs_dir": str(result.get("pdfs_dir") or ""),
        "orders_jsonl": str(result.get("orders_jsonl") or ""),
        "errors_jsonl": str(result.get("errors_jsonl") or ""),
        "report_json": str(result.get("report_json") or ""),
        "provider_report_json": str(result.get("provider_report_json") or ""),
    }


def _import_provider_receipts_for_ym(year: int, month: int) -> dict[str, Any]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12.")

    output_root = _manual_month_root_for_ym(year, month)
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        from scripts.manual_receipt_import import import_manual_receipts_for_month
    except Exception as exc:  # pragma: no cover - import failure should be rare
        raise HTTPException(status_code=500, detail=f"provider import module load failed: {exc}") from exc

    try:
        result = import_manual_receipts_for_month(
            output_root,
            year,
            month,
            ingestion_channel="provider_inbox",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"provider receipt import failed: {exc}") from exc

    provider_counts = result.get("provider_counts") if isinstance(result.get("provider_counts"), dict) else {}
    providers_result: dict[str, dict[str, int]] = {}
    for provider in PROVIDER_KEYS:
        stats = provider_counts.get(provider) if isinstance(provider_counts.get(provider), dict) else {}
        providers_result[provider] = {
            "found": int(stats.get("found") or 0),
            "imported": int(stats.get("imported") or 0),
            "imported_missing_amount": int(stats.get("imported_missing_amount") or 0),
            "skipped_duplicates": int(stats.get("skipped_duplicates") or 0),
            "failed": int(stats.get("failed") or 0),
        }
    shared_stats = provider_counts.get("manual") if isinstance(provider_counts.get("manual"), dict) else {}
    providers_result["shared"] = {
        "found": int(shared_stats.get("found") or 0),
        "imported": int(shared_stats.get("imported") or 0),
        "imported_missing_amount": int(shared_stats.get("imported_missing_amount") or 0),
        "skipped_duplicates": int(shared_stats.get("skipped_duplicates") or 0),
        "failed": int(shared_stats.get("failed") or 0),
    }

    skipped_duplicates = int(result.get("skipped_duplicates") or 0)
    failed = int(result.get("failed") or 0)
    skipped_dirs, skipped_files = _extract_skipped_dirs_and_files(result.get("skipped_rows"))
    manual_action_required = skipped_duplicates > 0 or failed > 0
    if skipped_duplicates > 0 and failed > 0:
        manual_action_reason = "skipped_and_failed"
    elif skipped_duplicates > 0:
        manual_action_reason = "skipped"
    elif failed > 0:
        manual_action_reason = "failed"
    else:
        manual_action_reason = ""

    return {
        "status": "ok",
        "ym": result.get("ym"),
        "found_files": int(result.get("found_files") or result.get("found_pdfs") or 0),
        "imported": int(result.get("imported") or 0),
        "imported_missing_amount": int(result.get("imported_missing_amount") or 0),
        "skipped_duplicates": skipped_duplicates,
        "failed": failed,
        "providers": providers_result,
        "inbox_dir": str(result.get("inbox_dir") or ""),
        "pdfs_dir": str(result.get("pdfs_dir") or ""),
        "orders_jsonl": str(result.get("orders_jsonl") or ""),
        "errors_jsonl": str(result.get("errors_jsonl") or ""),
        "report_json": str(result.get("report_json") or ""),
        "provider_report_json": str(result.get("provider_report_json") or ""),
        "manual_action_required": manual_action_required,
        "manual_action_reason": manual_action_reason,
        "unattached_count": skipped_duplicates + failed,
        "skipped_dir": skipped_dirs[0] if skipped_dirs else "",
        "skipped_dirs": skipped_dirs,
        "skipped_files": skipped_files,
    }


def _run_provider_download_for_ym(
    year: int,
    month: int,
    *,
    auth_handoff: bool = True,
    headed: bool = True,
    slow_mo_ms: int = 0,
) -> dict[str, Any]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12.")

    output_root = _manual_month_root_for_ym(year, month)
    output_root.mkdir(parents=True, exist_ok=True)
    reports_dir = output_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    script = SKILL_ROOT / "scripts" / "provider_download_orchestrator.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail=f"provider download orchestrator not found: {script}")

    out_json = reports_dir / "provider_download_result.json"
    cmd = [
        sys.executable,
        str(script),
        "--year",
        str(year),
        "--month",
        str(month),
        "--output-root",
        str(output_root),
        "--out-json",
        str(out_json),
        "--slow-mo-ms",
        str(max(0, int(slow_mo_ms))),
    ]

    for provider in PROVIDER_KEYS:
        storage_state = _resolve_provider_storage_state_for_ym(year, month, provider)
        cmd += [f"--{provider}-storage-state", str(storage_state)]

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
                "provider_download_orchestrator.py failed:\n"
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
                "provider_download_orchestrator.py returned no JSON payload.\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            ),
        )

    status = str(payload.get("status") or "ok").strip() or "ok"
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    providers = data.get("providers") if isinstance(data.get("providers"), dict) else {}

    return {
        "status": status,
        "ym": f"{year:04d}-{month:02d}",
        "output_root": str(output_root),
        "result_json": str(data.get("result_json") or out_json),
        "downloaded_total": int(data.get("downloaded_total") or 0) if isinstance(data, dict) else 0,
        "imported": int(data.get("imported") or 0) if isinstance(data, dict) else 0,
        "failed_providers": data.get("failed_providers") if isinstance(data.get("failed_providers"), list) else [],
        "providers": providers,
        "import_result": data.get("import_result") if isinstance(data.get("import_result"), dict) else {},
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


def _run_mf_csv_import_for_ym(
    year: int,
    month: int,
    *,
    auth_handoff: bool = True,
    headed: bool = True,
    slow_mo_ms: int = 0,
    import_url: str = DEFAULT_MFCLOUD_TRANSACTIONS_IMPORT_URL,
) -> dict[str, Any]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12.")

    output_root = _manual_month_root_for_ym(year, month)
    output_root.mkdir(parents=True, exist_ok=True)
    inbox_dir = _mf_csv_import_inbox_dir_for_ym(year, month, create=True)
    reports_dir = output_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = output_root / "debug" / "mf_csv_import"
    debug_dir.mkdir(parents=True, exist_ok=True)

    script = SKILL_ROOT / "scripts" / "mfcloud_csv_import.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail=f"mfcloud csv import script not found: {script}")

    storage_state = _resolve_mfcloud_storage_state_for_ym(year, month)
    if not storage_state.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "MF Cloud storage state was not found. "
                f"Expected: {storage_state}. Run preflight login first."
            ),
        )

    out_json = reports_dir / "mf_csv_import_result.json"
    cmd = [
        sys.executable,
        str(script),
        "--year",
        str(year),
        "--month",
        str(month),
        "--storage-state",
        str(storage_state),
        "--import-url",
        str(import_url),
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
                "mfcloud_csv_import.py failed:\n"
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
                "mfcloud_csv_import.py returned no JSON payload.\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            ),
        )

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return {
        "status": "ok",
        "ym": f"{year:04d}-{month:02d}",
        "import_url": str(import_url),
        "inbox_dir": str(inbox_dir),
        "result_json": str(out_json),
        "files_found": int(data.get("files_found") or 0) if isinstance(data, dict) else 0,
        "submitted_count": int(data.get("submitted_count") or 0) if isinstance(data, dict) else 0,
        "queued_count": int(data.get("queued_count") or 0) if isinstance(data, dict) else 0,
        "archived_dir": str(data.get("archived_dir") or "") if isinstance(data, dict) else "",
    }

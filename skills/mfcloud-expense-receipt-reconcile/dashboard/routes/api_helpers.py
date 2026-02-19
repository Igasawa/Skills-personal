from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pypdf import PdfReader, PdfWriter

from services import core
from services import core_scheduler
from services import core_shared


def _provider_source_status_for_ym(year: int, month: int) -> dict[str, Any]:
    source_status = core._manual_source_dir_status(year=year, month=month)
    path = str(source_status.get("path") or "").strip()
    configured = bool(source_status.get("configured"))
    exists = bool(source_status.get("exists"))
    scan_summary = source_status.get("scan_summary") if isinstance(source_status.get("scan_summary"), dict) else {}
    return {
        "path": path,
        "configured": configured,
        "exists": exists,
        "pending_files": int(source_status.get("pending_files") or 0),
        "scan_summary": scan_summary,
    }



WORKSPACE_MAX_LINKS = 100
WORKSPACE_MAX_PINNED_LINKS = 6
WORKSPACE_MAX_LABEL_CHARS = 80
WORKSPACE_MAX_PROMPT_ENTRIES = 200
WORKSPACE_MAX_PROMPT_CHARS = 50000
WORKSPACE_MAX_NOTE_ENTRIES = 400
WORKSPACE_MAX_NOTE_CHARS = 4000
WORKSPACE_MAX_PROFILE_ENTRIES = 400
WORKSPACE_MAX_PROFILE_OWNER_CHARS = 80
WORKSPACE_MAX_PROFILE_AGENT_CHARS = 32
WORKSPACE_ALLOWED_PROFILE_AGENTS = {"codex", "chatgpt", "claude", "gemini", "other"}
WORKSPACE_DEFAULT_PROMPT_KEY = "mf_expense_reports"
WORKFLOW_TEMPLATE_MAX_ITEMS = 30
WORKFLOW_TEMPLATE_MAX_NAME_CHARS = 80
WORKFLOW_TEMPLATE_MAX_URL_CHARS = 2048
WORKFLOW_TEMPLATE_MAX_SOURCE_URLS = 10
WORKFLOW_TEMPLATE_MAX_STEPS = 30
WORKFLOW_TEMPLATE_MAX_STEP_TITLE_CHARS = 80
WORKFLOW_TEMPLATE_MAX_STEP_ACTION_CHARS = 48
WORKFLOW_TEMPLATE_MAX_STEP_TIMER_MINUTES = 7 * 24 * 60
WORKFLOW_TEMPLATE_MIN_STEP_TIMER_MINUTES = 1
WORKFLOW_TEMPLATE_DEFAULT_STEP_TIMER_MINUTES = 5
WORKFLOW_TEMPLATE_MAX_STEP_EXECUTION_LOG_ITEMS = 20
WORKFLOW_TEMPLATE_MAX_STEP_EXECUTION_LOG_MESSAGE_CHARS = 200
WORKFLOW_TEMPLATE_STEP_DEFAULT_ACTION = "preflight"
WORKFLOW_TEMPLATE_REQUIRED_STEP_ACTIONS = (
    "preflight",
    "mf_reconcile",
)
WORKFLOW_TEMPLATE_REQUIRED_STEP_TITLES = {
    "preflight": "手順0 準備（ログイン確認・MF連携更新）",
    "mf_reconcile": "手順5 MF突合・下書き作成",
}
WORKFLOW_TEMPLATE_FALLBACK_ACTION_ORDER = (
    "preflight",
    "amazon_download",
    "amazon_print",
    "rakuten_download",
    "rakuten_print",
    "provider_ingest",
    "mf_bulk_upload_task",
    "mf_reconcile",
    "month_close",
    "preflight_mf",
)
# Canonical source for workflow template step action validation/persistence.
# Keep in sync with frontend action options (`static/js/index.js`/`static/js/scheduler.js`);
# the API side is the single source of truth for accepted action identifiers.
WORKFLOW_TEMPLATE_ALLOWED_STEP_ACTIONS = (
    "preflight",
    "preflight_mf",
    "amazon_download",
    "rakuten_download",
    "amazon_print",
    "rakuten_print",
    "provider_ingest",
    "mf_bulk_upload_task",
    "mf_reconcile",
    "month_close",
)
WORKFLOW_TEMPLATE_MAX_NOTES_CHARS = 4000
WORKFLOW_TEMPLATE_MAX_SUBHEADING_CHARS = 120
WORKFLOW_TEMPLATE_MAX_SEARCH_CHARS = 200
WORKFLOW_PAGE_MAX_ITEMS = 60
WORKFLOW_PAGE_MAX_NAME_CHARS = 80
WORKFLOW_PAGE_MAX_SUBHEADING_CHARS = 120
WORKFLOW_PAGE_MAX_STEP_VERSIONS = 30
WORKFLOW_TEMPLATE_MODES = {"new", "edit", "copy"}
WORKFLOW_TEMPLATE_SORT_OPTIONS = {
    "updated_desc",
    "updated_asc",
    "created_desc",
    "created_asc",
    "name_asc",
    "name_desc",
    "year_desc",
    "year_asc",
}
WORKFLOW_TEMPLATE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
WORKFLOW_PAGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ERROR_INCIDENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
GAS_WEBHOOK_TOKEN_ENV = "AX_PROVIDER_IMPORT_WEBHOOK_TOKEN"
GAS_WEBHOOK_TOKEN_HEADER = "x-provider-import-token"


def _actor_from_request(request: Request) -> dict[str, str]:
    ip = request.client.host if request.client else ""
    ua = str(request.headers.get("user-agent") or "").strip()
    return {
        "channel": "dashboard",
        "id": "local_user",
        "ip": ip,
        "user_agent": ua[:300],
    }


def _try_year_month(payload: dict[str, Any]) -> tuple[int, int] | None:
    try:
        year = int(payload.get("year"))
        month = int(payload.get("month"))
    except Exception:
        return None
    if month < 1 or month > 12:
        return None
    return year, month


def _error_reports_root() -> Path:
    return core.SKILL_ROOT / "reports"


def _review_kil_script_path() -> Path:
    candidates = [
        core.SKILL_ROOT / "scripts" / "review_kil_brain.py",
        core.SKILL_ROOT.parent.parent / "scripts" / "review_kil_brain.py",
        Path.cwd() / "scripts" / "review_kil_brain.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise HTTPException(status_code=500, detail="review_kil_brain.py not found.")


def _safe_incident_id(incident_id: str) -> str:
    value = str(incident_id or "").strip()
    if not value or not ERROR_INCIDENT_ID_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail="Invalid incident id.")
    return value


def _to_non_negative_int(value: Any, *, default: int = 0) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed >= 0 else 0


def _normalize_provider_filter(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return result
    for value in values:
        provider = str(value or "").strip().lower()
        if not provider:
            continue
        if provider in core.PROVIDER_KEYS and provider not in seen:
            result.append(provider)
            seen.add(provider)
    return result


def _normalize_provider_counts(values: Any) -> dict[str, dict[str, int]]:
    raw = values if isinstance(values, dict) else {}
    normalized: dict[str, dict[str, int]] = {}
    for provider in (*core.PROVIDER_KEYS, "manual"):
        row = raw.get(provider) if isinstance(raw.get(provider), dict) else {}
        if not isinstance(row, dict):
            row = {}
        normalized[provider] = {
            "found": _to_non_negative_int(row.get("found"), default=0),
            "imported": _to_non_negative_int(row.get("imported"), default=0),
            "imported_missing_amount": _to_non_negative_int(row.get("imported_missing_amount"), default=0),
            "skipped_duplicates": _to_non_negative_int(row.get("skipped_duplicates"), default=0),
            "failed": _to_non_negative_int(row.get("failed"), default=0),
        }
    return normalized


def _normalize_provider_import_result(payload: Any, year: int, month: int) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

    year_month = f"{year:04d}-{month:02d}"
    found_files = _to_non_negative_int(payload.get("found_files"), default=0)
    found_pdfs = _to_non_negative_int(payload.get("found_pdfs"), default=found_files)
    imported = _to_non_negative_int(payload.get("imported"), default=0)
    imported_missing_amount = _to_non_negative_int(payload.get("imported_missing_amount"), default=0)
    skipped_duplicates = _to_non_negative_int(payload.get("skipped_duplicates"), default=0)
    failed = _to_non_negative_int(payload.get("failed"), default=0)
    provider_filter = _normalize_provider_filter(payload.get("provider_filter"))

    manual_action_required = bool(payload.get("manual_action_required"))
    if not manual_action_required and (skipped_duplicates > 0 or failed > 0):
        manual_action_required = True
    manual_action_reason = str(payload.get("manual_action_reason") or "").strip()
    if not manual_action_reason and manual_action_required:
        if failed > 0 and skipped_duplicates > 0:
            manual_action_reason = "skipped_and_failed"
        elif failed > 0:
            manual_action_reason = "failed"
        else:
            manual_action_reason = "skipped"

    status = str(payload.get("status") or "").strip().lower()
    if status in {"", "running", "pending", "unknown"}:
        if manual_action_required:
            status = "warning"
        else:
            status = "ok"
    if status not in {"ok", "success", "warning", "failed", "error"}:
        status = "success"

    source_import = payload.get("source_import") if isinstance(payload.get("source_import"), dict) else {}
    ingestion_channel = str(payload.get("ingestion_channel") or "provider_inbox").strip().lower()
    report_dir = core._artifact_root() / year_month / "manual" / "reports"
    report_json = str(payload.get("report_json") or "").strip() or str(report_dir / "manual_import_last.json")
    provider_report_json = (
        str(payload.get("provider_report_json") or "").strip()
        or str(report_dir / "provider_import_last.json")
    )

    return {
        "ym": year_month,
        "attempted": bool(payload.get("attempted", True)),
        "status": status,
        "found_files": found_files,
        "found_pdfs": found_pdfs,
        "imported": imported,
        "imported_missing_amount": imported_missing_amount,
        "skipped_duplicates": skipped_duplicates,
        "failed": failed,
        "manual_action_required": manual_action_required,
        "manual_action_reason": manual_action_reason,
        "provider_filter": provider_filter,
        "ingestion_channel": ingestion_channel,
        "provider_counts": _normalize_provider_counts(payload.get("provider_counts")),
        "updated_at": str(payload.get("updated_at") or "").strip() or None,
        "source_import": source_import,
        "report_json": report_json,
        "provider_report_json": provider_report_json,
        "skipped_rows": payload.get("skipped_rows") if isinstance(payload.get("skipped_rows"), list) else [],
        "failed_rows": payload.get("failed_rows") if isinstance(payload.get("failed_rows"), list) else [],
        "imported_rows": payload.get("imported_rows") if isinstance(payload.get("imported_rows"), list) else [],
        "report_path": str(report_dir / "provider_import_last.json"),
    }


def _resolve_provider_import_webhook_token(request: Request, token: str | None) -> str | None:
    provided = str(token or "").strip()
    if not provided:
        provided = str(request.headers.get(GAS_WEBHOOK_TOKEN_HEADER) or "").strip()
    if not provided:
        auth = str(request.headers.get("authorization") or request.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
    return provided or None


def _validate_provider_import_webhook_token(request: Request, token: str | None = None) -> None:
    expected = str(os.environ.get(GAS_WEBHOOK_TOKEN_ENV) or "").strip()
    if not expected:
        return
    provided = _resolve_provider_import_webhook_token(request, token)
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid provider import webhook token.")


def _parse_ym(value: Any) -> tuple[int, int] | None:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})$", text)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        return None
    return year, month


def _extract_incident_year_month(payload: Any) -> tuple[int, int] | None:
    if not isinstance(payload, dict):
        return None
    for candidate in (payload.get("incident"), payload):
        if not isinstance(candidate, dict):
            continue
        ym = _parse_ym(candidate.get("ym"))
        if ym:
            return ym
        try:
            year = int(candidate.get("year"))
            month = int(candidate.get("month"))
        except Exception:
            continue
        if 1 <= month <= 12:
            return year, month
    return None


def _run_error_tool(script_name: str, args: list[str], *, timeout_seconds: int = 120) -> dict[str, Any]:
    script_path = core.SKILL_ROOT / "scripts" / script_name
    if not script_path.exists():
        raise HTTPException(status_code=500, detail=f"Error tool missing: {script_name}")
    cmd = [sys.executable, str(script_path), "--root", str(_error_reports_root()), *args]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(core.SKILL_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1, int(timeout_seconds)),
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Error tool timeout: {script_name} ({exc.timeout}s)",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error tool execution failed: {exc}") from exc

    stdout = str(res.stdout or "").strip()
    stderr = str(res.stderr or "").strip()
    if res.returncode != 0:
        detail = stderr or stdout or f"exit={res.returncode}"
        raise HTTPException(status_code=500, detail=f"{script_name} failed: {detail}")
    try:
        payload = json.loads(stdout or "{}")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{script_name} produced invalid JSON output.",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"{script_name} output must be a JSON object.")
    return payload


def _open_directory(path: Path) -> subprocess.CompletedProcess[str]:
    if sys.platform.startswith("win"):
        cmd = ["explorer", str(path)]
    elif sys.platform == "darwin":
        cmd = ["open", str(path)]
    else:
        cmd = ["xdg-open", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # Windows explorer occasionally returns non-zero even when the folder
    # actually opened (no stdout/stderr, existing target).
    if (
        sys.platform.startswith("win")
        and result.returncode != 0
        and path.exists()
        and not str(result.stdout or "").strip()
        and not str(result.stderr or "").strip()
    ):
        return subprocess.CompletedProcess(
            args=result.args,
            returncode=0,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result


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


def _resolve_provider_skipped_dir_for_ym(year: int, month: int) -> Path | None:
    ym = f"{year:04d}-{month:02d}"
    root = core._artifact_root() / ym
    report_path = root / "manual" / "reports" / "provider_import_last.json"
    report = core._read_json(report_path)

    if isinstance(report, dict):
        skipped_rows = report.get("skipped_rows")
        if isinstance(skipped_rows, list):
            dirs: list[Path] = []
            seen: set[str] = set()
            for row in skipped_rows:
                if not isinstance(row, dict):
                    continue
                candidate = _derive_skipped_bucket_dir(str(row.get("moved_to") or ""))
                if candidate is None:
                    continue
                key = str(candidate)
                if not key or key in seen:
                    continue
                seen.add(key)
                dirs.append(candidate)
            for candidate in dirs:
                if candidate.exists() and candidate.is_dir():
                    return candidate
            if dirs:
                return dirs[0]

    skipped_root = root / "manual" / "inbox" / "_skipped"
    if not skipped_root.exists() or not skipped_root.is_dir():
        return None
    run_dirs = sorted(
        [path for path in skipped_root.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if run_dirs:
        return run_dirs[0]
    return None


def _workspace_state_path() -> Path:
    return core._artifact_root() / "_workspace" / "workspace_state.json"


def _workspace_default_state() -> dict[str, Any]:
    return {
        "links": [],
        "pinned_links": [],
        "prompts": {},
        "link_notes": {},
        "link_profiles": {},
        "active_prompt_key": WORKSPACE_DEFAULT_PROMPT_KEY,
        "revision": 0,
        "updated_at": None,
    }


def _normalize_workspace_label(value: Any) -> str:
    return " ".join(str(value or "").strip().split())[:WORKSPACE_MAX_LABEL_CHARS]


def _normalize_workspace_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return parsed.geturl()


def _sanitize_workspace_links(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, dict):
            continue
        url = _normalize_workspace_url(row.get("url"))
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        label = _normalize_workspace_label(row.get("label"))
        if not label:
            label = urlparse(url).netloc or url
        out.append({"label": label, "url": url})
        if len(out) >= WORKSPACE_MAX_LINKS:
            break
    return out


def _sanitize_workspace_pinned_links(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, dict):
            continue
        url = _normalize_workspace_url(row.get("url"))
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        label = _normalize_workspace_label(row.get("label"))
        if not label:
            label = urlparse(url).netloc or url
        out.append({"label": label, "url": url})
        if len(out) >= WORKSPACE_MAX_PINNED_LINKS:
            break
    return out


def _normalize_workspace_link_pools(
    links: Any,
    pinned_links: Any,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    safe_pinned = _sanitize_workspace_pinned_links(pinned_links)
    pinned_keys = {str(row.get("url") or "").lower() for row in safe_pinned}
    safe_links = [
        row
        for row in _sanitize_workspace_links(links)
        if str(row.get("url") or "").lower() not in pinned_keys
    ]
    return safe_links, safe_pinned


def _is_valid_prompt_key(key: Any) -> bool:
    text = str(key or "").strip()
    if not text:
        return False
    if text == WORKSPACE_DEFAULT_PROMPT_KEY:
        return True
    return text.startswith("custom:")


def _sanitize_workspace_prompts(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for key, raw in value.items():
        prompt_key = str(key or "").strip()
        if not _is_valid_prompt_key(prompt_key):
            continue
        text = str(raw or "")
        if len(text) > WORKSPACE_MAX_PROMPT_CHARS:
            text = text[:WORKSPACE_MAX_PROMPT_CHARS]
        out[prompt_key] = text
        if len(out) >= WORKSPACE_MAX_PROMPT_ENTRIES:
            break
    return out


def _sanitize_workspace_link_notes(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for key, raw in value.items():
        note_key = str(key or "").strip()
        if not _is_valid_prompt_key(note_key):
            continue
        text = str(raw or "")
        if len(text) > WORKSPACE_MAX_NOTE_CHARS:
            text = text[:WORKSPACE_MAX_NOTE_CHARS]
        out[note_key] = text
        if len(out) >= WORKSPACE_MAX_NOTE_ENTRIES:
            break
    return out


def _sanitize_workspace_profile_owner(value: Any) -> str:
    return " ".join(str(value or "").strip().split())[:WORKSPACE_MAX_PROFILE_OWNER_CHARS]


def _sanitize_workspace_profile_agent(value: Any) -> str:
    text = str(value or "").strip().lower()[:WORKSPACE_MAX_PROFILE_AGENT_CHARS]
    if not text:
        return ""
    if text in WORKSPACE_ALLOWED_PROFILE_AGENTS:
        return text
    return ""


def _sanitize_workspace_profile_reviewed_on(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return ""
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return ""
    return text


def _sanitize_workspace_link_profiles(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, raw in value.items():
        profile_key = str(key or "").strip()
        if not _is_valid_prompt_key(profile_key):
            continue
        row = raw if isinstance(raw, dict) else {}
        owner = _sanitize_workspace_profile_owner(row.get("owner"))
        agent = _sanitize_workspace_profile_agent(row.get("agent"))
        reviewed_on = _sanitize_workspace_profile_reviewed_on(row.get("reviewed_on"))
        if not owner and not agent and not reviewed_on:
            continue
        out[profile_key] = {
            "owner": owner,
            "agent": agent,
            "reviewed_on": reviewed_on,
        }
        if len(out) >= WORKSPACE_MAX_PROFILE_ENTRIES:
            break
    return out


def _sanitize_workspace_active_prompt_key(value: Any) -> str:
    key = str(value or "").strip()
    if _is_valid_prompt_key(key):
        return key
    return WORKSPACE_DEFAULT_PROMPT_KEY


def _normalize_workspace_state(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _workspace_default_state()
    links, pinned_links = _normalize_workspace_link_pools(
        payload.get("links"),
        payload.get("pinned_links"),
    )
    prompts = _sanitize_workspace_prompts(payload.get("prompts"))
    link_notes = _sanitize_workspace_link_notes(payload.get("link_notes"))
    link_profiles = _sanitize_workspace_link_profiles(payload.get("link_profiles"))
    active_prompt_key = _sanitize_workspace_active_prompt_key(payload.get("active_prompt_key"))
    revision = core._safe_non_negative_int(payload.get("revision"), default=0)
    updated_at = str(payload.get("updated_at") or "").strip() or None
    return {
        "links": links,
        "pinned_links": pinned_links,
        "prompts": prompts,
        "link_notes": link_notes,
        "link_profiles": link_profiles,
        "active_prompt_key": active_prompt_key,
        "revision": int(revision),
        "updated_at": updated_at,
    }


def _read_workspace_state() -> dict[str, Any]:
    state = _normalize_workspace_state(core._read_json(_workspace_state_path()))
    if not state.get("active_prompt_key"):
        state["active_prompt_key"] = WORKSPACE_DEFAULT_PROMPT_KEY
    state["revision"] = core._safe_non_negative_int(state.get("revision"), default=0)
    return state


def _write_workspace_state(state: dict[str, Any], *, revision: int | None = None) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    sanitized = _normalize_workspace_state(state)
    if revision is None:
        current = _normalize_workspace_state(core._read_json(_workspace_state_path()))
        next_revision = core._safe_non_negative_int(current.get("revision"), default=0) + 1
    else:
        next_revision = core._safe_non_negative_int(revision, default=0)
    sanitized["revision"] = int(next_revision)
    sanitized["updated_at"] = now
    path = _workspace_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    core._write_json(path, sanitized)
    return sanitized


def _merge_workspace_links(
    client_links: list[dict[str, str]],
    server_links: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in [*client_links, *server_links]:
        if not isinstance(row, dict):
            continue
        url = _normalize_workspace_url(row.get("url"))
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        label = _normalize_workspace_label(row.get("label"))
        if not label:
            label = urlparse(url).netloc or url
        merged.append({"label": label, "url": url})
        if len(merged) >= WORKSPACE_MAX_LINKS:
            break
    return merged


def _merge_workspace_pinned_links(
    client_links: list[dict[str, str]],
    server_links: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in [*client_links, *server_links]:
        if not isinstance(row, dict):
            continue
        url = _normalize_workspace_url(row.get("url"))
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        label = _normalize_workspace_label(row.get("label"))
        if not label:
            label = urlparse(url).netloc or url
        merged.append({"label": label, "url": url})
        if len(merged) >= WORKSPACE_MAX_PINNED_LINKS:
            break
    return merged


def _merge_workspace_prompts(client_prompts: dict[str, str], server_prompts: dict[str, str]) -> dict[str, str]:
    merged = dict(server_prompts)
    merged.update(client_prompts)
    return _sanitize_workspace_prompts(merged)


def _merge_workspace_link_notes(client_notes: dict[str, str], server_notes: dict[str, str]) -> dict[str, str]:
    merged = dict(server_notes)
    merged.update(client_notes)
    return _sanitize_workspace_link_notes(merged)


def _merge_workspace_link_profiles(
    client_profiles: dict[str, dict[str, str]],
    server_profiles: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    merged = dict(server_profiles)
    merged.update(client_profiles)
    return _sanitize_workspace_link_profiles(merged)


def _extract_print_file_paths(manifest: dict[str, Any] | None) -> list[str]:
    if not isinstance(manifest, dict):
        return []
    rows = manifest.get("files")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _write_manual_open_print_script(path: Path, files: list[str]) -> None:
    lines = [
        "$ErrorActionPreference = 'Continue'",
        "$files = @(",
    ]
    lines += [f'  "{p}"' for p in files]
    lines += [
        ")",
        "$opened = 0",
        "$failed = 0",
        "$missing = 0",
        "foreach ($f in $files) {",
        "  if (-not (Test-Path $f)) {",
        "    Write-Warning (\"missing: \" + $f)",
        "    $missing += 1",
        "    continue",
        "  }",
        "  try {",
        "    Start-Process -FilePath $f -ErrorAction Stop",
        "    $opened += 1",
        "  } catch {",
        "    Write-Warning (\"open_failed: \" + $f + \" :: \" + $_.Exception.Message)",
        "    $failed += 1",
        "  }",
        "  Start-Sleep -Milliseconds 300",
        "}",
        "Write-Output (\"print_summary opened=\" + $opened + \" failed=\" + $failed + \" missing=\" + $missing + \" total=\" + $files.Count)",
        "if ($failed -gt 0) {",
        "  exit 1",
        "}",
        "exit 0",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _safe_print_source(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized not in {"amazon", "rakuten"}:
        raise HTTPException(status_code=400, detail="source must be amazon or rakuten.")
    return normalized


def _source_manifest_path(reports_dir: Path, source: str) -> Path:
    return reports_dir / f"print_manifest.{source}.json"


def _source_list_path(reports_dir: Path, source: str) -> Path:
    return reports_dir / f"print_list.{source}.txt"


def _open_file(path: Path) -> subprocess.CompletedProcess[str]:
    if sys.platform.startswith("win"):
        cmd = ["explorer", str(path)]
    elif sys.platform == "darwin":
        cmd = ["open", str(path)]
    else:
        cmd = ["xdg-open", str(path)]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _desktop_shortcut_root() -> Path:
    override = str(os.environ.get("AX_DASHBOARD_SHORTCUT_DIR") or "").strip()
    if override:
        root = Path(override).expanduser()
    else:
        if sys.platform.startswith("win"):
            candidates: list[Path] = []
            onedrive = str(os.environ.get("OneDrive") or "").strip()
            if onedrive:
                candidates.append(Path(onedrive).expanduser() / "Desktop")
            userprofile = str(os.environ.get("USERPROFILE") or "").strip()
            if userprofile:
                candidates.append(Path(userprofile).expanduser() / "Desktop")
            home_desktop = Path.home() / "Desktop"
            if all(path != home_desktop for path in candidates):
                candidates.append(home_desktop)
            root = next((path for path in candidates if path.exists()), candidates[0] if candidates else home_desktop)
        else:
            root = Path.home() / "Desktop"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_folder_shortcut(target: Path, shortcut_name: str) -> Path | None:
    if not sys.platform.startswith("win"):
        return None
    clean_name = str(shortcut_name or "").strip()
    if not clean_name:
        return None
    shortcut_path = _desktop_shortcut_root() / f"{clean_name}.url"
    content = (
        "[InternetShortcut]\n"
        f"URL={target.resolve().as_uri()}\n"
        "IconFile=explorer.exe\n"
        "IconIndex=0\n"
    )
    shortcut_path.write_text(content, encoding="utf-8")
    return shortcut_path


def _merge_pdfs(input_paths: list[Path], merged_path: Path) -> tuple[int, int]:
    writer = PdfWriter()
    merged_file_count = 0
    merged_page_count = 0
    for pdf_path in input_paths:
        reader = PdfReader(str(pdf_path))
        pages = list(reader.pages)
        if not pages:
            continue
        for page in pages:
            writer.add_page(page)
        merged_file_count += 1
        merged_page_count += len(pages)
    if merged_page_count <= 0:
        raise HTTPException(status_code=500, detail="No valid PDF pages were found for merge.")
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    with merged_path.open("wb") as handle:
        writer.write(handle)
    return merged_file_count, merged_page_count


def _open_receipts_folder_for_ym(ym: str, actor: dict[str, str]) -> JSONResponse:
    ym = core._safe_ym(ym)
    year, month = core._split_ym(ym)
    root = core._artifact_root() / ym
    amazon_pdfs = root / "amazon" / "pdfs"
    rakuten_pdfs = root / "rakuten" / "pdfs"
    root.mkdir(parents=True, exist_ok=True)
    if amazon_pdfs.exists() and rakuten_pdfs.exists():
        target = root
    elif amazon_pdfs.exists():
        target = amazon_pdfs
    elif rakuten_pdfs.exists():
        target = rakuten_pdfs
    else:
        # Fallback: open the month root even if receipts are not generated yet.
        target = root

    res = _open_directory(target)
    if res.returncode != 0:
        detail = (
            "Open folder failed:\n"
            f"path: {target}\n"
            f"exit: {res.returncode}\n"
            f"stdout:\n{res.stdout}\n"
            f"stderr:\n{res.stderr}\n"
        )
        core._append_audit_event(
            year=year,
            month=month,
            event_type="source_action",
            action="open_receipts_folder",
            status="failed",
            actor=actor,
            details={"reason": detail, "path": str(target)},
        )
        raise HTTPException(status_code=500, detail=detail)

    core._append_audit_event(
        year=year,
        month=month,
        event_type="source_action",
        action="open_receipts_folder",
        status="success",
        actor=actor,
        details={"path": str(target)},
    )
    return JSONResponse({"status": "ok", "path": str(target)})


__all__ = [name for name in globals() if not name.startswith("__")]



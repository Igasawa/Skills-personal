#!/usr/bin/env python3
"""Common helpers for error incident automation."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
REPORTS_ROOT_DEFAULT = SKILL_ROOT / "reports"

INBOX_DIR_NAME = "error_inbox"
ARCHIVE_DIR_NAME = "error_archive"
PLANS_DIR_NAME = "error_plans"
RUNS_DIR_NAME = "error_runs"

STATUS_VALUES = {"new", "planned", "running", "resolved", "escalated"}
ARCHIVE_RESULTS = {"resolved", "escalated"}
SAFE_INCIDENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
QUERY_SECRET_RE = re.compile(
    r"([?&](?:token|api[_-]?key|access_token|refresh_token|session|sig|signature|key)=)[^&\s]+",
    re.IGNORECASE,
)
BEARER_RE = re.compile(r"(?im)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/\-]+")
COOKIE_RE = re.compile(r"(?im)(cookie\s*:\s*).+$")
GENERIC_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|session[_-]?id|password)\b"
    r"(\s*[:=]\s*|\"\s*:\s*|'\s*:\s*)"
    r"([^\s\"'&,]+)"
)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_reports_root(raw_root: str | None) -> Path:
    text = str(raw_root or "").strip()
    if text:
        return Path(text).expanduser()
    return REPORTS_ROOT_DEFAULT


def normalize_incident_id(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("incident_id is required.")
    if not SAFE_INCIDENT_ID_RE.fullmatch(text):
        raise ValueError("incident_id must use only letters, digits, ., _, -")
    return text


def build_incident_id(run_id: str | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = str(run_id or "").strip()
    if suffix:
        suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", suffix).strip("._-")
    if not suffix:
        suffix = "manual"
    return f"incident_{stamp}_{suffix[:48]}"


def ensure_error_dirs(reports_root: Path) -> dict[str, Path]:
    inbox = reports_root / INBOX_DIR_NAME
    archive_root = reports_root / ARCHIVE_DIR_NAME
    archive_resolved = archive_root / "resolved"
    archive_escalated = archive_root / "escalated"
    plans = reports_root / PLANS_DIR_NAME
    runs = reports_root / RUNS_DIR_NAME
    for path in (inbox, archive_resolved, archive_escalated, plans, runs):
        path.mkdir(parents=True, exist_ok=True)
    return {
        "reports_root": reports_root,
        "inbox": inbox,
        "archive_root": archive_root,
        "archive_resolved": archive_resolved,
        "archive_escalated": archive_escalated,
        "plans": plans,
        "runs": runs,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text), encoding="utf-8")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def redact_text(text: str) -> str:
    value = str(text or "")
    value = QUERY_SECRET_RE.sub(r"\1[REDACTED]", value)
    value = BEARER_RE.sub(r"\1[REDACTED]", value)
    value = COOKIE_RE.sub(r"\1[REDACTED]", value)
    value = GENERIC_SECRET_RE.sub(r"\1\2[REDACTED]", value)
    value = EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    return value


def redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): redact_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def tail_text(path: Path, max_bytes: int = 16000) -> str:
    if not path.exists():
        return ""
    raw = path.read_bytes()
    limit = max(0, int(max_bytes))
    if limit and len(raw) > limit:
        raw = raw[-limit:]
    return redact_text(raw.decode("utf-8", errors="ignore"))


def tail_lines(path: Path, max_lines: int = 200) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    limit = max(0, int(max_lines))
    if limit:
        lines = lines[-limit:]
    out = "\n".join(lines)
    if out:
        out += "\n"
    return redact_text(out)


def read_status(incident_dir: Path) -> str:
    status_path = incident_dir / "status.txt"
    if not status_path.exists():
        return "new"
    status = status_path.read_text(encoding="utf-8", errors="ignore").strip().lower()
    if status in STATUS_VALUES:
        return status
    return "new"


def write_status(incident_dir: Path, status: str) -> None:
    normalized = str(status or "").strip().lower()
    if normalized not in STATUS_VALUES:
        raise ValueError(f"Invalid status: {status!r}")
    write_text(incident_dir / "status.txt", normalized + "\n")


def incident_updated_at_iso(incident_dir: Path) -> str:
    latest = incident_dir.stat().st_mtime
    for path in incident_dir.rglob("*"):
        try:
            latest = max(latest, path.stat().st_mtime)
        except Exception:
            continue
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat(timespec="seconds")


def list_inbox_incidents(reports_root: Path) -> list[dict[str, Any]]:
    dirs = ensure_error_dirs(reports_root)
    rows: list[dict[str, Any]] = []
    try:
        children = list(dirs["inbox"].iterdir())
    except Exception:
        return rows
    for child in children:
        try:
            is_dir = child.is_dir()
        except Exception:
            continue
        if not is_dir:
            continue
        payload = read_json(child / "incident.json")
        payload = payload if isinstance(payload, dict) else {}
        try:
            updated_at = str(payload.get("updated_at") or "").strip() or incident_updated_at_iso(child)
        except Exception:
            updated_at = str(payload.get("updated_at") or "").strip()
        row = {
            "incident_id": child.name,
            "status": read_status(child),
            "step": str(payload.get("step") or "").strip(),
            "failure_class": str(payload.get("failure_class") or "").strip(),
            "run_id": str(payload.get("run_id") or "").strip(),
            "ym": str(payload.get("ym") or "").strip(),
            "message": str(payload.get("message") or "").strip(),
            "updated_at": updated_at,
            "path": str(child),
        }
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return rows

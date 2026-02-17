#!/usr/bin/env python3
"""Capture an error incident into the fixed inbox folder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from common import artifact_root, read_json as read_common_json, runs_root  # noqa: E402
from error_common import (  # noqa: E402
    STATUS_VALUES,
    build_incident_id,
    ensure_error_dirs,
    normalize_incident_id,
    now_utc_iso,
    read_json,
    redact_json,
    redact_text,
    resolve_reports_root,
    tail_lines,
    tail_text,
    write_json,
    write_status,
    write_text,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture an incident under reports/error_inbox")
    parser.add_argument("--incident-id", default="", help="Incident id. Auto-generated when omitted.")
    parser.add_argument("--run-id", default="", help="Run id linked to this incident")
    parser.add_argument("--year", type=int, default=None, help="Year for month-scoped artifacts")
    parser.add_argument("--month", type=int, default=None, help="Month for month-scoped artifacts")
    parser.add_argument("--step", default="", help="Step or mode where failure happened")
    parser.add_argument("--failure-class", default="unknown", help="Failure class label")
    parser.add_argument("--message", default="", help="Failure summary message")
    parser.add_argument(
        "--status",
        default="new",
        choices=sorted(STATUS_VALUES),
        help="Initial incident status",
    )
    parser.add_argument("--log-path", default="", help="Path to raw execution log for tail extraction")
    parser.add_argument("--audit-path", default="", help="Path to audit log jsonl for tail extraction")
    parser.add_argument("--context-path", default="", help="Path to context json file")
    parser.add_argument("--context-json", default="", help="Inline context json string")
    parser.add_argument("--max-log-bytes", type=int, default=16000, help="Tail size for log capture")
    parser.add_argument("--max-audit-lines", type=int, default=200, help="Tail line count for audit capture")
    parser.add_argument("--root", default="", help="Reports root override")
    parser.add_argument("--force", action="store_true", help="Overwrite existing incident folder")
    return parser.parse_args()


def _safe_ym(year: int | None, month: int | None) -> str:
    if year is None or month is None:
        return ""
    if month < 1 or month > 12:
        return ""
    return f"{year:04d}-{month:02d}"


def _default_log_path(run_id: str) -> Path | None:
    run_text = str(run_id or "").strip()
    if not run_text:
        return None
    meta_path = runs_root() / f"{run_text}.json"
    meta = read_common_json(meta_path)
    if isinstance(meta, dict):
        raw = str(meta.get("log_path") or "").strip()
        if raw:
            candidate = Path(raw).expanduser()
            if candidate.exists():
                return candidate
    fallback = runs_root() / f"{run_text}.log"
    if fallback.exists():
        return fallback
    return None


def _default_audit_path(year: int | None, month: int | None) -> Path | None:
    ym = _safe_ym(year, month)
    if not ym:
        return None
    candidate = artifact_root() / ym / "reports" / "audit_log.jsonl"
    if candidate.exists():
        return candidate
    return None


def _load_context(context_path: str, context_json: str) -> dict[str, Any]:
    context: dict[str, Any] = {}
    path_text = str(context_path or "").strip()
    if path_text:
        payload = read_common_json(Path(path_text).expanduser())
        if isinstance(payload, dict):
            context.update(payload)
    inline_text = str(context_json or "").strip()
    if inline_text:
        try:
            payload = json.loads(inline_text)
            if isinstance(payload, dict):
                context.update(payload)
            else:
                context["inline_context"] = payload
        except Exception:
            context["inline_context_parse_error"] = "invalid_json"
    return context


def _error_signature(failure_class: str, step: str, message: str) -> str:
    parts = [failure_class.strip(), step.strip(), " ".join(message.strip().split())[:180]]
    joined = " | ".join(part for part in parts if part)
    return redact_text(joined)


def main() -> int:
    args = parse_args()
    reports_root = resolve_reports_root(args.root)
    dirs = ensure_error_dirs(reports_root)

    incident_id = normalize_incident_id(args.incident_id) if args.incident_id else build_incident_id(args.run_id)
    incident_dir = dirs["inbox"] / incident_id
    if incident_dir.exists() and not args.force:
        raise SystemExit(f"incident already exists: {incident_dir}")

    incident_dir.mkdir(parents=True, exist_ok=True)

    existing = read_json(incident_dir / "incident.json")
    existing = existing if isinstance(existing, dict) else {}

    log_path = Path(args.log_path).expanduser() if str(args.log_path).strip() else _default_log_path(args.run_id)
    audit_path = (
        Path(args.audit_path).expanduser()
        if str(args.audit_path).strip()
        else _default_audit_path(args.year, args.month)
    )

    log_tail = tail_text(log_path, max_bytes=args.max_log_bytes) if log_path else ""
    audit_tail = tail_lines(audit_path, max_lines=args.max_audit_lines) if audit_path else ""

    message = str(args.message or "").strip() or "failure captured"
    failure_class = str(args.failure_class or "").strip() or "unknown"
    step = str(args.step or "").strip()
    now = now_utc_iso()
    ym = _safe_ym(args.year, args.month)

    context_payload = _load_context(args.context_path, args.context_json)
    context_payload["capture"] = {
        "captured_at": now,
        "script": "error_capture.py",
        "run_id": str(args.run_id or "").strip(),
        "year": args.year,
        "month": args.month,
        "step": step,
        "failure_class": failure_class,
    }
    context_payload = redact_json(context_payload)

    incident_payload: dict[str, Any] = dict(existing)
    incident_payload.update(
        {
            "incident_id": incident_id,
            "status": args.status,
            "created_at": str(existing.get("created_at") or now),
            "updated_at": now,
            "run_id": str(args.run_id or existing.get("run_id") or "").strip(),
            "year": args.year,
            "month": args.month,
            "ym": ym,
            "step": step,
            "failure_class": failure_class,
            "message": redact_text(message),
            "error_signature": _error_signature(failure_class, step, message),
            "evidence": {
                "log_tail_file": "log_tail.txt",
                "audit_tail_file": "audit_tail.jsonl",
                "context_file": "context.json",
            },
            "source_paths": {
                "log_path": str(log_path) if log_path else "",
                "audit_path": str(audit_path) if audit_path else "",
                "context_path": str(Path(args.context_path).expanduser()) if str(args.context_path).strip() else "",
            },
        }
    )

    write_status(incident_dir, args.status)
    write_text(incident_dir / "log_tail.txt", log_tail)
    write_text(incident_dir / "audit_tail.jsonl", audit_tail)
    write_json(incident_dir / "context.json", context_payload)
    write_json(incident_dir / "incident.json", incident_payload)

    result = {
        "status": "ok",
        "incident_id": incident_id,
        "incident_dir": str(incident_dir),
        "reports_root": str(dirs["reports_root"]),
        "created_at": incident_payload.get("created_at"),
        "updated_at": incident_payload.get("updated_at"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


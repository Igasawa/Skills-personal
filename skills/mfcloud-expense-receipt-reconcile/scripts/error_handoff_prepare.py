#!/usr/bin/env python3
"""Prepare a handoff package for Antigravity execution."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from error_common import (
    ensure_error_dirs,
    normalize_incident_id,
    now_utc_iso,
    read_json,
    read_status,
    resolve_reports_root,
    write_json,
    write_status,
    write_text,
)

QUEUE_DIR_ENV = "AX_ANTIGRAVITY_HANDOFF_DIR"
ALLOWED_UNAPPROVED_STATUSES = {"plan_proposed", "planned"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Antigravity handoff payload for one incident")
    parser.add_argument("--incident-id", required=True, help="Incident id in error_inbox")
    parser.add_argument("--root", default="", help="Reports root override")
    parser.add_argument("--queue-dir", default="", help="Optional queue directory for external pickup")
    parser.add_argument(
        "--allow-unapproved",
        action="store_true",
        help="Allow handoff when incident is not approved yet",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing queue payload file")
    return parser.parse_args()


def _resolve_queue_dir(raw: str) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        text = str(os.environ.get(QUEUE_DIR_ENV) or "").strip()
    if not text:
        return None
    return Path(text).expanduser()


def _build_handoff_markdown(payload: dict[str, Any]) -> str:
    incident = payload.get("incident") if isinstance(payload.get("incident"), dict) else {}
    plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
    card_summary = plan.get("card_summary") if isinstance(plan.get("card_summary"), dict) else {}
    lines = [
        f"# Antigravity Handoff: {payload.get('incident_id')}",
        "",
        "## Incident",
        f"- Status: {incident.get('status') or '-'}",
        f"- Step: {incident.get('step') or '-'}",
        f"- Failure class: {incident.get('failure_class') or '-'}",
        f"- Message: {incident.get('message') or '-'}",
        "",
        "## Plan Summary",
        f"- Plan: {card_summary.get('plan') or plan.get('summary') or '-'}",
        f"- First step: {card_summary.get('first_step') or '-'}",
        f"- ETA: {card_summary.get('eta_minutes') if card_summary else '-'} minutes",
        f"- Risk: {card_summary.get('risk') or plan.get('risk_summary') or '-'}",
        f"- Approval: {card_summary.get('approval') or '-'}",
        "",
        "## Execution",
        "- Owner: antigravity",
        "- Action: implement approved steps in order and report back status",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    reports_root = resolve_reports_root(args.root)
    dirs = ensure_error_dirs(reports_root)
    incident_id = normalize_incident_id(args.incident_id)

    incident_dir = dirs["inbox"] / incident_id
    if not incident_dir.exists():
        raise SystemExit(f"incident not found in inbox: {incident_dir}")

    incident = read_json(incident_dir / "incident.json")
    if not isinstance(incident, dict):
        raise SystemExit(f"incident payload missing: {incident_dir / 'incident.json'}")

    incident_status = read_status(incident_dir)
    if incident_status != "approved" and not args.allow_unapproved:
        allowed = ", ".join(sorted(ALLOWED_UNAPPROVED_STATUSES))
        raise SystemExit(
            f"incident is not approved (status={incident_status}); approve first or use --allow-unapproved ({allowed})"
        )

    plan_path_text = str(incident.get("plan_path") or "").strip()
    plan_path = Path(plan_path_text).expanduser() if plan_path_text else dirs["plans"] / incident_id / "plan.json"
    if not plan_path.exists():
        plan_path = dirs["plans"] / incident_id / "plan.json"
    plan = read_json(plan_path)
    if not isinstance(plan, dict):
        raise SystemExit(f"plan missing: {plan_path}")

    now = now_utc_iso()
    handoff_dir = dirs["handoffs"] / incident_id
    handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff_json_path = handoff_dir / "handoff.json"
    handoff_md_path = handoff_dir / "handoff.md"

    handoff_payload: dict[str, Any] = {
        "status": "ok",
        "incident_id": incident_id,
        "prepared_at": now,
        "handoff_status": "handed_off",
        "executor": "antigravity",
        "incident": {
            "incident_id": incident_id,
            "status": incident_status,
            "step": str(incident.get("step") or ""),
            "failure_class": str(incident.get("failure_class") or ""),
            "message": str(incident.get("message") or ""),
            "ym": str(incident.get("ym") or ""),
            "run_id": str(incident.get("run_id") or ""),
        },
        "plan": plan,
        "paths": {
            "incident_dir": str(incident_dir),
            "plan_json": str(plan_path),
            "handoff_json": str(handoff_json_path),
            "handoff_md": str(handoff_md_path),
        },
    }
    write_json(handoff_json_path, handoff_payload)
    markdown = _build_handoff_markdown(handoff_payload)
    write_text(handoff_md_path, markdown + ("\n" if not markdown.endswith("\n") else ""))

    queue_payload_path = None
    queue_dir = _resolve_queue_dir(args.queue_dir)
    if queue_dir is not None:
        queue_dir.mkdir(parents=True, exist_ok=True)
        queue_payload_path = queue_dir / f"{incident_id}.json"
        if queue_payload_path.exists() and not args.force:
            raise SystemExit(f"queue payload already exists: {queue_payload_path}")
        write_json(queue_payload_path, handoff_payload)

    incident["status"] = "handed_off"
    incident["updated_at"] = now
    incident["handoff_at"] = now
    incident["handoff_path"] = str(handoff_json_path)
    incident["handoff_executor"] = "antigravity"
    incident["execution_owner"] = "antigravity"
    if queue_payload_path is not None:
        incident["handoff_queue_path"] = str(queue_payload_path)
    write_json(incident_dir / "incident.json", incident)
    write_status(incident_dir, "handed_off")

    output = {
        "status": "ok",
        "incident_id": incident_id,
        "handoff_status": "handed_off",
        "handoff_json": str(handoff_json_path),
        "handoff_md": str(handoff_md_path),
        "queue_payload": str(queue_payload_path) if queue_payload_path is not None else "",
        "year": int(incident.get("year")) if isinstance(incident.get("year"), int) else None,
        "month": int(incident.get("month")) if isinstance(incident.get("month"), int) else None,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


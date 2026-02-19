#!/usr/bin/env python3
"""Show incident queue status for error automation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from error_common import ensure_error_dirs, list_inbox_incidents, normalize_incident_id, resolve_reports_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show incident queue status")
    parser.add_argument("--root", default="", help="Reports root override")
    parser.add_argument("--incident-id", default="", help="Show one incident in detail")
    parser.add_argument("--json", action="store_true", help="Print json")
    return parser.parse_args()


def _count_child_dirs(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for child in path.iterdir() if child.is_dir())


def _read_incident_payload(path: Path) -> dict:
    incident_json = path / "incident.json"
    if not incident_json.exists():
        return {}
    try:
        payload = json.loads(incident_json.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _status_for_single_incident(dirs: dict[str, Path], incident_id: str) -> dict:
    target = dirs["inbox"] / incident_id
    if not target.exists():
        target = dirs["archive_resolved"] / incident_id
    if not target.exists():
        target = dirs["archive_escalated"] / incident_id
    if not target.exists():
        raise FileNotFoundError(f"incident not found: {incident_id}")
    payload = _read_incident_payload(target)
    planner = payload.get("planner") if isinstance(payload.get("planner"), dict) else {}
    return {
        "incident_id": incident_id,
        "path": str(target),
        "status": str(payload.get("status") or "").strip(),
        "plan_state": str(payload.get("plan_state") or "").strip(),
        "failure_class": str(payload.get("failure_class") or "").strip(),
        "step": str(payload.get("step") or "").strip(),
        "ym": str(payload.get("ym") or "").strip(),
        "run_id": str(payload.get("run_id") or "").strip(),
        "updated_at": str(payload.get("updated_at") or "").strip(),
        "message": str(payload.get("message") or "").strip(),
        "plan_path": str(payload.get("plan_path") or "").strip(),
        "planned_at": str(payload.get("planned_at") or "").strip(),
        "approved_at": str(payload.get("approved_at") or "").strip(),
        "handoff_at": str(payload.get("handoff_at") or "").strip(),
        "handoff_path": str(payload.get("handoff_path") or "").strip(),
        "handoff_queue_path": str(payload.get("handoff_queue_path") or "").strip(),
        "execution_owner": str(payload.get("execution_owner") or "").strip(),
        "approval_required": bool(payload.get("approval_required")),
        "planner_mode": str(planner.get("mode") or "").strip(),
    }


def main() -> int:
    args = parse_args()
    reports_root = resolve_reports_root(args.root)
    dirs = ensure_error_dirs(reports_root)
    incidents = list_inbox_incidents(reports_root)

    result = {
        "status": "ok",
        "reports_root": str(reports_root),
        "inbox_count": len(incidents),
        "archive_resolved_count": _count_child_dirs(dirs["archive_resolved"]),
        "archive_escalated_count": _count_child_dirs(dirs["archive_escalated"]),
        "incidents": incidents,
    }

    if args.incident_id:
        incident_id = normalize_incident_id(args.incident_id)
        result["incident"] = _status_for_single_incident(dirs, incident_id)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"reports_root: {result['reports_root']}")
    print(f"unresolved_inbox: {result['inbox_count']}")
    print(
        f"archive: resolved={result['archive_resolved_count']} escalated={result['archive_escalated_count']}"
    )
    if result["incidents"]:
        for row in result["incidents"]:
            print(
                f"- {row['incident_id']} "
                f"[{row['status']}] "
                f"class={row['failure_class'] or '-'} "
                f"step={row['step'] or '-'} "
                f"ym={row['ym'] or '-'} "
                f"updated={row['updated_at'] or '-'}"
            )
    else:
        print("- no unresolved incidents")

    if "incident" in result:
        inc = result["incident"]
        print("")
        print(f"incident_detail: {inc['incident_id']}")
        print(f"  path: {inc['path']}")
        print(f"  status: {inc['status'] or '-'}")
        print(f"  failure_class: {inc['failure_class'] or '-'}")
        print(f"  step: {inc['step'] or '-'}")
        print(f"  ym: {inc['ym'] or '-'}")
        print(f"  run_id: {inc['run_id'] or '-'}")
        print(f"  updated_at: {inc['updated_at'] or '-'}")
        print(f"  message: {inc['message'] or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

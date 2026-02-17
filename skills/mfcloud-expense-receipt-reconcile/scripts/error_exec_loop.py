#!/usr/bin/env python3
"""Execute remediation verification loops for one incident."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from error_common import (
    ensure_error_dirs,
    normalize_incident_id,
    now_utc_iso,
    read_json,
    resolve_reports_root,
    write_json,
    write_status,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent

DISALLOWED_SNIPPETS = (
    "git reset --hard",
    "git checkout --",
    "rm -rf /",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute remediation loop")
    parser.add_argument("--incident-id", required=True, help="Incident id in error_inbox")
    parser.add_argument("--root", default="", help="Reports root override")
    parser.add_argument("--max-loops", type=int, default=8, help="Max loop count")
    parser.add_argument("--max-runtime-minutes", type=int, default=45, help="Max runtime")
    parser.add_argument("--same-error-limit", type=int, default=3, help="Repeat signature limit")
    parser.add_argument(
        "--single-iteration",
        action="store_true",
        help="Run one verification iteration only (do not auto-loop)",
    )
    parser.add_argument("--archive-on-success", action="store_true", help="Archive as resolved when checks pass")
    parser.add_argument("--archive-on-escalate", action="store_true", help="Archive as escalated on limit hit")
    return parser.parse_args()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _run_command(cmd: str, timeout_seconds: int = 900) -> dict[str, Any]:
    command_text = str(cmd or "").strip()
    if not command_text:
        return {"command": command_text, "returncode": 1, "stdout": "", "stderr": "empty command"}
    lowered = command_text.lower()
    for bad in DISALLOWED_SNIPPETS:
        if bad in lowered:
            return {
                "command": command_text,
                "returncode": 1,
                "stdout": "",
                "stderr": f"blocked command pattern: {bad}",
            }
    try:
        result = subprocess.run(
            command_text,
            cwd=str(SKILL_ROOT),
            shell=True,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
        return {
            "command": command_text,
            "returncode": int(result.returncode),
            "stdout": str(result.stdout or "")[-4000:],
            "stderr": str(result.stderr or "")[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command_text,
            "returncode": 124,
            "stdout": str(exc.stdout or "")[-4000:],
            "stderr": (str(exc.stderr or "") + "\ncommand timeout")[-4000:],
        }
    except Exception as exc:
        return {"command": command_text, "returncode": 1, "stdout": "", "stderr": f"exception: {exc}"}


def _coerce_returncode(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 1


def _archive_incident(root: Path, incident_id: str, result: str, reason: str) -> dict[str, Any]:
    script = SCRIPT_DIR / "error_archive.py"
    cmd = [
        sys.executable,
        str(script),
        "--root",
        str(root),
        "--incident-id",
        incident_id,
        "--result",
        result,
        "--reason",
        reason,
    ]
    proc = subprocess.run(cmd, cwd=str(SKILL_ROOT), capture_output=True, text=True, check=False)
    payload: dict[str, Any] = {
        "returncode": proc.returncode,
        "stdout": str(proc.stdout or ""),
        "stderr": str(proc.stderr or ""),
    }
    if proc.returncode == 0:
        try:
            parsed = json.loads(str(proc.stdout or "{}"))
            if isinstance(parsed, dict):
                payload.update(parsed)
        except Exception:
            pass
    return payload


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

    plan_path = Path(str(incident.get("plan_path") or "")).expanduser()
    if not plan_path.exists():
        plan_path = dirs["plans"] / incident_id / "plan.json"
    plan = read_json(plan_path)
    if not isinstance(plan, dict):
        raise SystemExit(f"plan missing: {plan_path}")

    verification_commands = plan.get("verification_commands") if isinstance(plan.get("verification_commands"), list) else []
    verification_commands = [str(cmd).strip() for cmd in verification_commands if str(cmd).strip()]
    if not verification_commands:
        raise SystemExit("plan has no verification_commands")

    incident["status"] = "running"
    incident["updated_at"] = now_utc_iso()
    incident.setdefault("execution_requested_at", incident["updated_at"])
    incident["execution_policy"] = {
        "max_loops": int(args.max_loops),
        "max_runtime_minutes": int(args.max_runtime_minutes),
        "same_error_limit": int(args.same_error_limit),
    }
    write_json(incident_dir / "incident.json", incident)
    write_status(incident_dir, "running")

    run_dir = dirs["runs"] / incident_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "loop_state.json"
    state = read_json(state_path)
    if not isinstance(state, dict):
        state = {
            "incident_id": incident_id,
            "started_at": now_utc_iso(),
            "loops_used": 0,
            "last_signature": "",
            "same_error_repeats": 0,
            "signature_counts": {},
        }

    max_loops = max(1, int(args.max_loops))
    max_runtime_seconds = max(60, int(args.max_runtime_minutes) * 60)
    same_error_limit = max(1, int(args.same_error_limit))
    start_dt = _utc_now()
    if state.get("started_at"):
        try:
            start_dt = datetime.fromisoformat(str(state["started_at"]))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        except Exception:
            start_dt = _utc_now()

    loop_results: list[dict[str, Any]] = []
    final_status = "running"
    archive_payload: dict[str, Any] = {}

    while True:
        current_loops = int(state.get("loops_used") or 0)
        if current_loops >= max_loops:
            final_status = "escalated"
            break
        runtime_seconds = int((_utc_now() - start_dt).total_seconds())
        if runtime_seconds >= max_runtime_seconds:
            final_status = "escalated"
            break

        iteration = current_loops + 1
        attempt_started = now_utc_iso()
        command_results = [_run_command(cmd) for cmd in verification_commands]
        passed = all(_coerce_returncode(item.get("returncode")) == 0 for item in command_results)
        if passed:
            signature = ""
        else:
            first_failed = next(
                (item for item in command_results if _coerce_returncode(item.get("returncode")) != 0),
                {},
            )
            signature = (
                f"{first_failed.get('command', '')}::rc={_coerce_returncode(first_failed.get('returncode'))}"[:300]
            )

        signature_counts = Counter(state.get("signature_counts") if isinstance(state.get("signature_counts"), dict) else {})
        if signature:
            signature_counts[signature] += 1
        same_repeats = 0
        if signature and signature == str(state.get("last_signature") or ""):
            same_repeats = int(state.get("same_error_repeats") or 0) + 1
        elif signature:
            same_repeats = 1

        attempt = {
            "incident_id": incident_id,
            "iteration": iteration,
            "started_at": attempt_started,
            "finished_at": now_utc_iso(),
            "verification_commands": verification_commands,
            "command_results": command_results,
            "verification_passed": passed,
            "error_signature": signature,
            "same_error_repeats": same_repeats,
            "runtime_seconds": int((_utc_now() - start_dt).total_seconds()),
        }
        attempt_path = run_dir / f"attempt_{iteration:02d}.json"
        write_json(attempt_path, attempt)
        loop_results.append({"iteration": iteration, "path": str(attempt_path), "verification_passed": passed})

        state["loops_used"] = iteration
        state["last_signature"] = signature
        state["same_error_repeats"] = same_repeats
        state["signature_counts"] = dict(signature_counts)
        state["updated_at"] = now_utc_iso()
        write_json(state_path, state)

        if passed:
            final_status = "resolved"
            break
        if same_repeats >= same_error_limit:
            final_status = "escalated"
            break
        if args.single_iteration:
            final_status = "running"
            break

        # In autonomous mode, the caller can modify code between loops.
        time.sleep(0.2)

    runtime_minutes = round(((_utc_now() - start_dt).total_seconds()) / 60.0, 2)

    if final_status == "resolved":
        incident["status"] = "resolved" if not args.archive_on_success else "running"
        incident["updated_at"] = now_utc_iso()
        write_json(incident_dir / "incident.json", incident)
        write_status(incident_dir, "resolved" if not args.archive_on_success else "running")
        if args.archive_on_success:
            archive_payload = _archive_incident(
                root=reports_root,
                incident_id=incident_id,
                result="resolved",
                reason="verification passed in loop",
            )
            if int(archive_payload.get("returncode") or 1) != 0 and incident_dir.exists():
                final_status = "running"
                incident["status"] = "running"
                incident["updated_at"] = now_utc_iso()
                write_json(incident_dir / "incident.json", incident)
                write_status(incident_dir, "running")
    elif final_status == "escalated":
        incident["status"] = "escalated" if not args.archive_on_escalate else "running"
        incident["updated_at"] = now_utc_iso()
        write_json(incident_dir / "incident.json", incident)
        write_status(incident_dir, "escalated" if not args.archive_on_escalate else "running")
        if args.archive_on_escalate:
            archive_payload = _archive_incident(
                root=reports_root,
                incident_id=incident_id,
                result="escalated",
                reason="loop limit reached or repeated error",
            )
            if int(archive_payload.get("returncode") or 1) != 0 and incident_dir.exists():
                final_status = "running"
                incident["status"] = "running"
                incident["updated_at"] = now_utc_iso()
                write_json(incident_dir / "incident.json", incident)
                write_status(incident_dir, "running")

    result_payload = {
        "status": "ok",
        "incident_id": incident_id,
        "final_status": final_status,
        "loops_used": int(state.get("loops_used") or 0),
        "runtime_minutes": runtime_minutes,
        "same_error_repeats": int(state.get("same_error_repeats") or 0),
        "loop_results": loop_results,
        "state_path": str(state_path),
        "run_dir": str(run_dir),
        "archive": archive_payload,
    }
    write_json(run_dir / "run_result.json", result_payload)
    print(json.dumps(result_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

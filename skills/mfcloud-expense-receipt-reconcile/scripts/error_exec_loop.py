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
DEFAULT_COMMIT_MESSAGE_TEMPLATE = "chore(error): resolve {incident_id} by pdca loop"
ALLOWED_COMMIT_SCOPES = {"incident", "plan", "run"}
DEFAULT_COMMIT_SCOPE = "incident"

DISALLOWED_SNIPPETS = (
    "git reset --hard",
    "git checkout --",
    "rm -rf /",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute remediation loop")
    parser.add_argument("--incident-id", required=True, help="Incident id in error_inbox")
    parser.add_argument("--root", default="", help="Reports root override")
    parser.add_argument("--max-loops", type=int, default=8, help="Max loop count")
    parser.add_argument("--max-runtime-minutes", type=int, default=45, help="Max runtime")
    parser.add_argument("--same-error-limit", type=int, default=3, help="Repeat signature limit")
    parser.add_argument(
        "--auto-replan-on-no-progress",
        action="store_true",
        default=True,
        help="Replan when no-progress repeats hit no-progress limit",
    )
    parser.add_argument(
        "--no-auto-replan-on-no-progress",
        action="store_false",
        dest="auto_replan_on_no_progress",
        help="Disable auto replan on repeated identical failure signature",
    )
    parser.add_argument("--no-progress-limit", type=int, default=2, help="Consecutive no-progress limit")
    parser.add_argument(
        "--single-iteration",
        action="store_true",
        help="Run one verification iteration only (do not auto-loop)",
    )
    parser.add_argument(
        "--commit-on-resolve",
        action="store_true",
        default=True,
        help="Create commit when resolved",
    )
    parser.add_argument(
        "--no-commit-on-resolve",
        action="store_false",
        dest="commit_on_resolve",
        help="Disable auto commit on resolve",
    )
    parser.add_argument(
        "--push-on-resolve",
        action="store_true",
        default=True,
        help="Push after commit when resolved",
    )
    parser.add_argument(
        "--no-push-on-resolve",
        action="store_false",
        dest="push_on_resolve",
        help="Disable auto push after resolved commit",
    )
    parser.add_argument("--commit-message-template", default="", help="Commit message template")
    parser.add_argument("--commit-remote", default="origin", help="Git remote for push")
    parser.add_argument("--commit-branch", default="", help="Git branch for push")
    parser.add_argument("--commit-scope", default=DEFAULT_COMMIT_SCOPE, help="incident|plan|run")
    parser.add_argument("--archive-on-success", action="store_true", help="Archive as resolved when checks pass")
    parser.add_argument("--archive-on-escalate", action="store_true", help="Archive as escalated on limit hit")
    return parser.parse_args(argv)


def _safe_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _safe_int(value: object, *, default: int, minimum: int = 1) -> int:
    try:
        candidate = int(value)
    except Exception:
        return default
    if candidate < minimum:
        return minimum
    return candidate


def _safe_str(value: object, *, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


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


def _run_subprocess_command(cmd: list[str], *, cwd: Path | None = None, timeout_seconds: int = 900) -> dict[str, Any]:
    if not cmd:
        return {"command": "", "returncode": 1, "stdout": "", "stderr": "empty command"}
    command_text = " ".join(str(item) for item in cmd).strip()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd or SKILL_ROOT),
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


def _run_git_command(args: list[str], *, timeout_seconds: int = 900) -> dict[str, Any]:
    return _run_subprocess_command(["git", *args], cwd=SKILL_ROOT, timeout_seconds=timeout_seconds)


def _coerce_returncode(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 1


def _read_json_output(result: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(str(result.get("stdout") or "{}"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _git_current_branch(reports_root: Path) -> str:
    payload = _run_git_command(["branch", "--show-current"], timeout_seconds=10)
    if int(payload.get("returncode") or 1) != 0:
        return "HEAD"
    branch = str(payload.get("stdout") or "").strip()
    if branch:
        return branch
    payload = _run_git_command(["name-rev", "--name-only", "HEAD"], timeout_seconds=10)
    if int(payload.get("returncode") or 1) != 0:
        return "HEAD"
    value = str(payload.get("stdout") or "").strip()
    if value:
        return value
    return "HEAD"


def _git_head_sha() -> str | None:
    payload = _run_git_command(["rev-parse", "HEAD"], timeout_seconds=10)
    if int(payload.get("returncode") or 1) != 0:
        return None
    return str(payload.get("stdout") or "").strip().splitlines()[:1][0] if str(payload.get("stdout") or "").strip() else None


def _resolve_commit_scope(scope: str, *, reports_root: Path, incident_id: str, incident_dir: Path, plan_path: Path, run_dir: Path) -> list[str]:
    normalized = _safe_str(scope, default=DEFAULT_COMMIT_SCOPE)
    if normalized not in ALLOWED_COMMIT_SCOPES:
        normalized = DEFAULT_COMMIT_SCOPE

    if normalized == "plan":
        return [str(plan_path.parent)]
    if normalized == "run":
        return [str(run_dir)]

    archived_incident = reports_root / "error_archive" / "resolved" / incident_id
    if archived_incident.exists():
        return [str(archived_incident)]
    return [str(incident_dir)]


def _render_commit_message(template: str, incident_id: str) -> str:
    template_text = _safe_str(template, default=DEFAULT_COMMIT_MESSAGE_TEMPLATE)
    try:
        return template_text.format(incident_id=incident_id, scope="").strip()
    except Exception:
        return template_text


def _run_plan_generation(reports_root: Path, incident_id: str, *, force: bool = False) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "error_plan_generate.py"),
        "--root",
        str(reports_root),
        "--incident-id",
        incident_id,
    ]
    if force:
        cmd.append("--force")
    result = _run_subprocess_command(cmd, cwd=SKILL_ROOT, timeout_seconds=120)
    payload: dict[str, Any] = {"status": "error" if int(result.get("returncode") or 1) != 0 else "ok"}
    payload.update(_read_json_output(result))
    payload.setdefault("returncode", result.get("returncode"))
    payload.setdefault("stdout", result.get("stdout"))
    payload.setdefault("stderr", result.get("stderr"))
    return payload


def _run_commit_if_resolved(
    args: argparse.Namespace,
    *,
    reports_root: Path,
    incident_id: str,
    incident_dir: Path,
    plan_path: Path,
    run_dir: Path,
    final_status: str,
) -> dict[str, Any]:
    requested = bool(_safe_bool(args.commit_on_resolve, default=True))
    payload: dict[str, Any] = {
        "requested": requested,
        "enabled": bool(requested and final_status == "resolved"),
        "ran": False,
        "skipped": False,
        "remote": _safe_str(args.commit_remote, default="origin"),
        "branch": _safe_str(args.commit_branch, default=""),
        "scope": _safe_str(args.commit_scope, default=DEFAULT_COMMIT_SCOPE),
        "commit_sha": None,
        "commit_message": None,
        "push": {
            "requested": bool(_safe_bool(args.push_on_resolve, default=True)),
            "ran": False,
            "success": False,
            "error": None,
        },
        "error": None,
    }

    if not payload["requested"] or final_status != "resolved":
        return payload

    if not payload["branch"]:
        payload["branch"] = _git_current_branch(reports_root)

    scope = _safe_str(args.commit_scope, default=DEFAULT_COMMIT_SCOPE)
    if scope not in ALLOWED_COMMIT_SCOPES:
        scope = DEFAULT_COMMIT_SCOPE
        payload["scope"] = scope

    scope_paths = _resolve_commit_scope(
        scope,
        reports_root=reports_root,
        incident_id=incident_id,
        incident_dir=incident_dir,
        plan_path=plan_path,
        run_dir=run_dir,
    )
    if not scope_paths:
        payload["skipped"] = True
        return payload

    status = _run_git_command(["status", "--short", "--", *scope_paths], timeout_seconds=60)
    if int(status.get("returncode") or 1) != 0:
        payload["error"] = f"git status failed: {_safe_str(status.get('stderr') or status.get('stdout'), default='unknown')}"
        return payload
    if not str(status.get("stdout") or "").strip():
        payload["skipped"] = True
        return payload

    add_result = _run_git_command(["add", "--", *scope_paths], timeout_seconds=120)
    if int(add_result.get("returncode") or 1) != 0:
        payload["error"] = f"git add failed: {_safe_str(add_result.get('stderr') or add_result.get('stdout'), default='unknown')}"
        return payload

    commit_message = _render_commit_message(
        _safe_str(args.commit_message_template, default=DEFAULT_COMMIT_MESSAGE_TEMPLATE),
        incident_id=incident_id,
    )
    commit_result = _run_git_command(["commit", "-m", commit_message], timeout_seconds=120)
    if int(commit_result.get("returncode") or 1) != 0:
        message = _safe_str(commit_result.get("stderr") or commit_result.get("stdout"), default="").lower()
        if "nothing to commit" in message:
            payload["skipped"] = True
            return payload
        payload["error"] = f"git commit failed: {_safe_str(commit_result.get('stderr') or commit_result.get('stdout'), default='unknown')}"
        return payload

    payload["ran"] = True
    payload["commit_message"] = commit_message
    payload["commit_sha"] = _git_head_sha()

    if not payload["push"]["requested"]:
        return payload

    push_result = _run_git_command(["push", payload["remote"], payload["branch"]], timeout_seconds=120)
    payload["push"]["ran"] = True
    if int(push_result.get("returncode") or 1) != 0:
        error = _safe_str(push_result.get("stderr") or push_result.get("stdout"), default="unknown")
        payload["push"]["error"] = error
        payload["error"] = error
        return payload
    payload["push"]["success"] = True
    return payload


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


def _loop_signature_from_results(command_results: list[dict[str, Any]]) -> str:
    if not command_results:
        return ""
    if all(_coerce_returncode(item.get("returncode")) == 0 for item in command_results):
        return ""
    first_failed = next(
        (item for item in command_results if _coerce_returncode(item.get("returncode")) != 0),
        {},
    )
    return f"{first_failed.get('command', '')}::rc={_coerce_returncode(first_failed.get('returncode'))}"[:300]


def execute_error_loop(args: argparse.Namespace) -> dict[str, Any]:
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

    same_error_limit = _safe_int(args.same_error_limit, default=3, minimum=1)
    no_progress_limit = _safe_int(args.no_progress_limit, default=2, minimum=1)
    auto_replan_on_no_progress = bool(_safe_bool(args.auto_replan_on_no_progress, default=True))
    commit_on_resolve = bool(_safe_bool(args.commit_on_resolve, default=True))

    incident["status"] = "running"
    incident["updated_at"] = now_utc_iso()
    incident.setdefault("execution_requested_at", incident["updated_at"])
    incident.setdefault("execution_policy", {})
    incident["execution_policy"] = {
        "max_loops": int(args.max_loops),
        "max_runtime_minutes": int(args.max_runtime_minutes),
        "same_error_limit": same_error_limit,
        "no_progress_limit": no_progress_limit,
        "auto_replan_on_no_progress": auto_replan_on_no_progress,
        "commit_on_resolve": commit_on_resolve,
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
            "no_progress_streak": 0,
            "signature_counts": {},
        }

    max_loops = max(1, int(args.max_loops))
    max_runtime_seconds = max(60, int(args.max_runtime_minutes) * 60)
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
    replan_payload: dict[str, Any] = {
        "requested": bool(auto_replan_on_no_progress),
        "reason": "",
        "iteration": 0,
        "plan_json": None,
    }
    commit_payload: dict[str, Any] = {
        "requested": bool(commit_on_resolve),
        "enabled": False,
        "ran": False,
        "skipped": False,
        "remote": _safe_str(args.commit_remote, default="origin"),
        "branch": _safe_str(args.commit_branch, default=""),
        "scope": _safe_str(args.commit_scope, default=DEFAULT_COMMIT_SCOPE),
        "commit_sha": None,
        "commit_message": None,
        "push": {
            "requested": bool(_safe_bool(args.push_on_resolve, default=True)),
            "ran": False,
            "success": False,
            "error": None,
        },
        "error": None,
    }

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
        signature = _loop_signature_from_results(command_results)

        signature_counts = Counter(state.get("signature_counts") if isinstance(state.get("signature_counts"), dict) else {})
        if signature:
            signature_counts[signature] += 1

        if signature and signature == str(state.get("last_signature") or ""):
            same_repeats = int(state.get("same_error_repeats") or 0) + 1
            no_progress_streak = int(state.get("no_progress_streak") or 0) + 1
        elif signature:
            same_repeats = 1
            no_progress_streak = 1
        else:
            same_repeats = 0
            no_progress_streak = 0

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
            "no_progress_streak": no_progress_streak,
            "runtime_seconds": int((_utc_now() - start_dt).total_seconds()),
        }
        attempt_path = run_dir / f"attempt_{iteration:02d}.json"
        write_json(attempt_path, attempt)
        loop_results.append({"iteration": iteration, "path": str(attempt_path), "verification_passed": passed})

        state["loops_used"] = iteration
        state["last_signature"] = signature
        state["same_error_repeats"] = same_repeats
        state["no_progress_streak"] = no_progress_streak
        state["signature_counts"] = dict(signature_counts)
        state["updated_at"] = now_utc_iso()
        write_json(state_path, state)

        if passed:
            final_status = "resolved"
            break
        if auto_replan_on_no_progress and no_progress_streak >= no_progress_limit:
            final_status = "replan_requested"
            replan_payload = _build_replan_payload(
                enabled=True,
                iteration=iteration,
                reason=f"no actionable progress for {no_progress_streak} consecutive loops",
                plan_json=None,
            )
            incident["status"] = "plan_proposed"
            incident["updated_at"] = now_utc_iso()
            write_json(incident_dir / "incident.json", incident)
            write_status(incident_dir, "plan_proposed")
            plan_result = _run_plan_generation(reports_root, incident_id, force=True)
            replan_payload["plan_json"] = plan_result
            plan_status = str(plan_result.get("status") or "").strip().lower()
            if plan_status != "ok":
                message = _safe_str(plan_result.get("stderr") or plan_result.get("stdout"), default="unknown")
                replan_payload["reason"] = _safe_str(replan_payload["reason"], default="") + f"; replanning failed: {message}"
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

    commit_payload = _run_commit_if_resolved(
        args,
        reports_root=reports_root,
        incident_id=incident_id,
        incident_dir=incident_dir,
        plan_path=plan_path,
        run_dir=run_dir,
        final_status=final_status,
    )
    commit_payload["requested"] = bool(_safe_bool(args.commit_on_resolve, default=True))
    if final_status != "resolved":
        commit_payload["enabled"] = False

    if final_status == "replan_requested":
        replan_payload["requested"] = bool(auto_replan_on_no_progress)

    result_payload = {
        "status": "ok",
        "incident_id": incident_id,
        "final_status": final_status,
        "loops_used": int(state.get("loops_used") or 0),
        "runtime_minutes": runtime_minutes,
        "same_error_repeats": int(state.get("same_error_repeats") or 0),
        "no_progress_streak": int(state.get("no_progress_streak") or 0),
        "loop_results": loop_results,
        "state_path": str(state_path),
        "run_dir": str(run_dir),
        "archive": archive_payload,
        "replan": replan_payload,
        "commit": commit_payload,
    }
    write_json(run_dir / "run_result.json", result_payload)
    return result_payload


def _build_replan_payload(
    *,
    enabled: bool,
    iteration: int | None,
    reason: str | None,
    plan_json: Any,
) -> dict[str, Any]:
    return {
        "requested": bool(enabled),
        "reason": _safe_str(reason, default=""),
        "iteration": int(iteration or 0),
        "plan_json": plan_json,
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def main() -> int:
    args = parse_args()
    payload = execute_error_loop(args)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

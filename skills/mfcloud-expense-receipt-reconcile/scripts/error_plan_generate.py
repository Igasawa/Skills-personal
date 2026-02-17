#!/usr/bin/env python3
"""Generate a remediation plan from an incident bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from error_common import (
    ensure_error_dirs,
    normalize_incident_id,
    now_utc_iso,
    read_json,
    read_text,
    redact_text,
    resolve_reports_root,
    write_json,
    write_status,
    write_text,
)


TARGET_HINTS = {
    "preflight": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/run.py",
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core.py",
    ],
    "preflight_mf": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core.py",
        "skills/mfcloud-expense-receipt-reconcile/scripts/mfcloud_extract.mjs",
    ],
    "amazon_download": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/amazon_download.mjs",
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core_pipeline.py",
    ],
    "rakuten_download": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/rakuten_download.mjs",
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core_pipeline.py",
    ],
    "amazon_print": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/collect_print.py",
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core_pipeline.py",
    ],
    "rakuten_print": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/collect_print.py",
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core_pipeline.py",
    ],
    "mf_reconcile": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/reconcile.py",
        "skills/mfcloud-expense-receipt-reconcile/scripts/mfcloud_extract.mjs",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate error remediation plan")
    parser.add_argument("--incident-id", required=True, help="Incident id in error_inbox")
    parser.add_argument("--root", default="", help="Reports root override")
    parser.add_argument("--force", action="store_true", help="Overwrite existing plan files")
    return parser.parse_args()


def _default_verification_commands(step: str, year: int | None, month: int | None) -> list[str]:
    step_value = str(step or "").strip()
    commands: list[str] = []
    if step_value in {"amazon_download", "rakuten_download", "amazon_print", "rakuten_print"}:
        commands.append("python -m pytest -q tests/test_run_core_pipeline.py")
    elif step_value == "mf_reconcile":
        commands.append("python -m pytest -q tests/test_reconcile.py")
    else:
        commands.append("python -m pytest -q tests/test_run_smoke.py")

    if year is not None and month is not None:
        commands.append(
            f"python scripts/run.py --year {year} --month {month} --dry-run --skip-rakuten --skip-mfcloud"
        )
    return commands


def _build_hypotheses(failure_class: str, step: str, message: str, log_excerpt: str) -> list[dict[str, str]]:
    low_message = " ".join((message + " " + log_excerpt).lower().split())
    items: list[dict[str, str]] = []
    if "timeout" in low_message or "network" in low_message:
        items.append(
            {
                "id": "H1",
                "confidence": "medium",
                "reason": "Network instability or timeout likely interrupted browser/script flow.",
            }
        )
    if "selector" in low_message or "not found" in low_message:
        items.append(
            {
                "id": "H2",
                "confidence": "medium",
                "reason": "UI selector drift likely broke element lookup during automation.",
            }
        )
    if str(failure_class).strip() == "run_failed" and not items:
        items.append(
            {
                "id": "H1",
                "confidence": "low",
                "reason": "Run failed without clear class-specific signal; inspect logs and replay mode.",
            }
        )
    if not items:
        items.append(
            {
                "id": "H1",
                "confidence": "low",
                "reason": "Insufficient evidence for direct cause; start with reproducible dry-run.",
            }
        )
    return items


def _build_actions(
    *,
    step: str,
    failure_class: str,
    verification_commands: list[str],
) -> list[dict[str, Any]]:
    step_text = str(step or "").strip()
    target_paths = TARGET_HINTS.get(step_text, [])
    actions: list[dict[str, Any]] = [
        {
            "id": "A1",
            "title": "Confirm reproduction path and isolate failure boundary",
            "priority": "P0",
            "risk": "low",
            "target_paths": target_paths,
            "verification": verification_commands[:1],
        },
        {
            "id": "A2",
            "title": "Apply minimal fix in the most likely target files",
            "priority": "P0",
            "risk": "medium",
            "target_paths": target_paths,
            "verification": verification_commands[:1],
        },
        {
            "id": "A3",
            "title": "Run verification suite and confirm non-regression",
            "priority": "P1",
            "risk": "low",
            "target_paths": [],
            "verification": verification_commands,
        },
    ]
    if str(failure_class).strip() == "auth_expired":
        actions.insert(
            1,
            {
                "id": "A1b",
                "title": "Refresh auth/session prerequisites",
                "priority": "P0",
                "risk": "low",
                "target_paths": [
                    "skills/mfcloud-expense-receipt-reconcile/scripts/run.py",
                    "skills/mfcloud-expense-receipt-reconcile/scripts/run_core.py",
                ],
                "verification": verification_commands[:1],
            },
        )
    return actions


def _build_plan_markdown(plan: dict[str, Any], incident: dict[str, Any]) -> str:
    hypotheses = plan.get("root_cause_hypotheses") if isinstance(plan.get("root_cause_hypotheses"), list) else []
    actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
    verification = plan.get("verification_commands") if isinstance(plan.get("verification_commands"), list) else []
    done = plan.get("done_criteria") if isinstance(plan.get("done_criteria"), list) else []
    lines: list[str] = [
        f"# Incident Plan: {plan.get('incident_id')}",
        "",
        "## Summary",
        f"- Failure class: {incident.get('failure_class') or '-'}",
        f"- Step: {incident.get('step') or '-'}",
        f"- Error signature: {incident.get('error_signature') or '-'}",
        f"- Message: {incident.get('message') or '-'}",
        "",
        "## Root Cause Hypotheses",
    ]
    for item in hypotheses:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('id')}: {item.get('reason')} (confidence: {item.get('confidence')})"
        )
    lines += ["", "## Action Plan"]
    for item in actions:
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('id')} [{item.get('priority')}] {item.get('title')}")
        targets = item.get("target_paths") if isinstance(item.get("target_paths"), list) else []
        if targets:
            lines.append("  - target paths:")
            for path in targets:
                lines.append(f"    - {path}")
        checks = item.get("verification") if isinstance(item.get("verification"), list) else []
        if checks:
            lines.append("  - verification:")
            for cmd in checks:
                lines.append(f"    - `{cmd}`")
    lines += ["", "## Verification Commands"]
    for cmd in verification:
        lines.append(f"- `{cmd}`")
    lines += ["", "## Done Criteria"]
    for row in done:
        lines.append(f"- {row}")
    lines += ["", "## Rollback", f"- {plan.get('rollback') or 'Revert modified files and rerun verification.'}", ""]
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

    plan_dir = dirs["plans"] / incident_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_json_path = plan_dir / "plan.json"
    plan_md_path = plan_dir / "plan.md"
    if (plan_json_path.exists() or plan_md_path.exists()) and not args.force:
        raise SystemExit("plan already exists; use --force to overwrite")

    year = incident.get("year")
    month = incident.get("month")
    year_value = int(year) if isinstance(year, int) else None
    month_value = int(month) if isinstance(month, int) else None
    step = str(incident.get("step") or "").strip()
    failure_class = str(incident.get("failure_class") or "unknown").strip()
    message = redact_text(str(incident.get("message") or "").strip())
    log_excerpt = read_text(incident_dir / "log_tail.txt")[:1500]

    verification_commands = _default_verification_commands(step, year_value, month_value)
    hypotheses = _build_hypotheses(failure_class, step, message, log_excerpt)
    actions = _build_actions(
        step=step,
        failure_class=failure_class,
        verification_commands=verification_commands,
    )

    plan_payload: dict[str, Any] = {
        "incident_id": incident_id,
        "generated_at": now_utc_iso(),
        "summary": f"Remediation plan for {failure_class or 'unknown'} failure in {step or 'unknown step'}",
        "root_cause_hypotheses": hypotheses,
        "actions": actions,
        "verification_commands": verification_commands,
        "done_criteria": [
            "Target error no longer reproduces in the same mode.",
            "Verification commands pass with no regression on critical path.",
        ],
        "rollback": "Revert the modified files and re-run baseline verification.",
        "policy": {
            "max_loops": 8,
            "max_runtime_minutes": 45,
            "same_error_limit": 3,
            "scope": "skills/mfcloud-expense-receipt-reconcile/**",
        },
        "source_incident_path": str(incident_dir),
    }

    plan_markdown = _build_plan_markdown(plan_payload, incident)
    write_json(plan_json_path, plan_payload)
    write_text(plan_md_path, plan_markdown + ("\n" if not plan_markdown.endswith("\n") else ""))

    incident["status"] = "planned"
    incident["plan_path"] = str(plan_json_path)
    incident["planned_at"] = now_utc_iso()
    incident["updated_at"] = incident["planned_at"]
    write_json(incident_dir / "incident.json", incident)
    write_status(incident_dir, "planned")

    print(
        json.dumps(
            {
                "status": "ok",
                "incident_id": incident_id,
                "plan_json": str(plan_json_path),
                "plan_md": str(plan_md_path),
                "year": year_value,
                "month": month_value,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


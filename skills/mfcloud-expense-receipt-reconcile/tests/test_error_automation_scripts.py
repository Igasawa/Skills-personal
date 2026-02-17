from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _run_json(cmd: list[str]) -> dict:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def test_error_capture_and_plan_generation(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    incident_id = "incident_test_case_001"

    capture = _run_json(
        [
            sys.executable,
            str(SCRIPT_DIR / "error_capture.py"),
            "--root",
            str(root),
            "--incident-id",
            incident_id,
            "--failure-class",
            "transient",
            "--step",
            "amazon_download",
            "--message",
            "timeout while fetching receipt",
            "--run-id",
            "run_001",
        ]
    )
    assert capture.get("status") == "ok"

    plan = _run_json(
        [
            sys.executable,
            str(SCRIPT_DIR / "error_plan_generate.py"),
            "--root",
            str(root),
            "--incident-id",
            incident_id,
        ]
    )
    assert plan.get("status") == "ok"
    assert Path(str(plan.get("plan_json") or "")).exists()

    incident_payload = json.loads((root / "error_inbox" / incident_id / "incident.json").read_text(encoding="utf-8"))
    assert incident_payload.get("status") == "planned"


def test_error_exec_loop_resolves_and_archives(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    incident_id = "incident_test_case_002"
    incident_dir = root / "error_inbox" / incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)
    (incident_dir / "status.txt").write_text("planned\n", encoding="utf-8")
    (incident_dir / "incident.json").write_text(
        json.dumps(
            {
                "incident_id": incident_id,
                "status": "planned",
                "step": "amazon_download",
                "failure_class": "run_failed",
                "message": "test",
                "created_at": "2026-02-17T00:00:00+00:00",
                "updated_at": "2026-02-17T00:00:00+00:00",
                "plan_path": str(root / "error_plans" / incident_id / "plan.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    plan_dir = root / "error_plans" / incident_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    verification_cmd = "echo ok"
    (plan_dir / "plan.json").write_text(
        json.dumps(
            {
                "incident_id": incident_id,
                "generated_at": "2026-02-17T00:00:00+00:00",
                "summary": "test plan",
                "root_cause_hypotheses": [],
                "actions": [{"id": "A1", "title": "verify", "priority": "P0", "risk": "low"}],
                "verification_commands": [verification_cmd],
                "done_criteria": ["verification command passes"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_json(
        [
            sys.executable,
            str(SCRIPT_DIR / "error_exec_loop.py"),
            "--root",
            str(root),
            "--incident-id",
            incident_id,
            "--archive-on-success",
        ]
    )
    assert result.get("status") == "ok"
    assert result.get("final_status") == "resolved"

    assert not (root / "error_inbox" / incident_id).exists()
    assert (root / "error_archive" / "resolved" / incident_id / "incident.json").exists()

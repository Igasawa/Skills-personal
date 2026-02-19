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
    assert Path(str(plan.get("plan_md") or "")).exists()

    plan_payload = json.loads((root / "error_plans" / incident_id / "plan.json").read_text(encoding="utf-8"))
    plan_markdown = (root / "error_plans" / incident_id / "plan.md").read_text(encoding="utf-8")
    evidence = plan_payload.get("evidence")
    evidence_quality = plan_payload.get("evidence_quality")
    hypotheses = plan_payload.get("root_cause_hypotheses")
    mapping = plan_payload.get("hypothesis_evidence_map")
    cause_analysis = plan_payload.get("cause_analysis")
    assert isinstance(evidence, list)
    assert evidence
    assert isinstance(evidence_quality, dict)
    assert "score" in evidence_quality
    assert "has_failure_signal" in evidence_quality
    assert isinstance(hypotheses, list)
    assert hypotheses
    assert isinstance(mapping, list)
    assert mapping
    assert isinstance(cause_analysis, list)
    assert cause_analysis
    assert "## Evidence Quality" in plan_markdown
    assert "## Cause Analysis" in plan_markdown
    for row in hypotheses:
        assert isinstance(row, dict)
        ids = row.get("evidence_ids")
        assert isinstance(ids, list)
        assert ids

    incident_payload = json.loads((root / "error_inbox" / incident_id / "incident.json").read_text(encoding="utf-8"))
    assert incident_payload.get("status") == "plan_proposed"


def test_error_plan_generation_filters_weak_evidence_signals(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    incident_id = "incident_test_case_weak_evidence"
    incident_dir = root / "error_inbox" / incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)

    (incident_dir / "status.txt").write_text("unresolved\n", encoding="utf-8")
    (incident_dir / "incident.json").write_text(
        json.dumps(
            {
                "incident_id": incident_id,
                "status": "unresolved",
                "step": "amazon_download",
                "failure_class": "run_failed",
                "message": "Run failed: mode=amazon_download reason=process_ended_without_final_status returncode=-1",
                "error_signature": "run_failed | amazon_download | Run failed: mode=amazon_download reason=process_ended_without_final_status returncode=-1",
                "created_at": "2026-02-19T00:00:00+00:00",
                "updated_at": "2026-02-19T00:00:00+00:00",
                "year": 2026,
                "month": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (incident_dir / "context.json").write_text(
        json.dumps(
            {
                "source": "dashboard_run_capture",
                "reason": "process_ended_without_final_status",
                "inferred_from": None,
                "mode": "amazon_download",
                "returncode": -1,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (incident_dir / "log_tail.txt").write_text("[run] Amazon download start\n", encoding="utf-8")

    result = _run_json(
        [
            sys.executable,
            str(SCRIPT_DIR / "error_plan_generate.py"),
            "--root",
            str(root),
            "--incident-id",
            incident_id,
        ]
    )
    assert result.get("status") == "ok"

    plan_payload = json.loads((root / "error_plans" / incident_id / "plan.json").read_text(encoding="utf-8"))
    evidence = plan_payload.get("evidence")
    assert isinstance(evidence, list)
    assert evidence

    paths = [str(row.get("path") or "") for row in evidence if isinstance(row, dict)]
    assert "context.json:inferred_from" not in paths
    signature_rows = [
        row
        for row in evidence
        if isinstance(row, dict) and str(row.get("path") or "") == "incident.json:error_signature"
    ]
    assert signature_rows
    assert all(
        "mode=amazon_download reason=process_ended_without_final_status" not in str(row.get("excerpt") or "")
        for row in signature_rows
    )

    log_rows = [row for row in evidence if isinstance(row, dict) and str(row.get("source") or "") == "log_tail"]
    assert log_rows
    assert all(str(row.get("kind") or "") == "log_context" for row in log_rows)

    reason_row = next(
        row
        for row in evidence
        if isinstance(row, dict) and str(row.get("path") or "") == "context.json:reason"
    )
    reason_id = str(reason_row.get("id") or "")
    hypotheses = plan_payload.get("root_cause_hypotheses")
    assert isinstance(hypotheses, list)
    assert hypotheses
    first_ids = hypotheses[0].get("evidence_ids") if isinstance(hypotheses[0], dict) else []
    assert isinstance(first_ids, list)
    assert reason_id in first_ids

    unknowns = plan_payload.get("unknowns")
    assert isinstance(unknowns, list)
    assert any("log_tail" in str(row) for row in unknowns)

    evidence_quality = plan_payload.get("evidence_quality")
    assert isinstance(evidence_quality, dict)
    assert evidence_quality.get("has_failure_signal") is True
    assert int(evidence_quality.get("strong_signal_count") or 0) >= 1
    assert float(evidence_quality.get("score") or 0) <= 0.60

    assert float(plan_payload.get("confidence_score") or 0) <= 0.60
    hypotheses = plan_payload.get("root_cause_hypotheses")
    assert isinstance(hypotheses, list)
    assert len(hypotheses) >= 2

    cause_analysis = plan_payload.get("cause_analysis")
    assert isinstance(cause_analysis, list)
    assert len(cause_analysis) >= 2


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


def test_error_handoff_prepare_creates_handoff_payload(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    incident_id = "incident_test_case_003"
    incident_dir = root / "error_inbox" / incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)
    (incident_dir / "status.txt").write_text("approved\n", encoding="utf-8")
    (incident_dir / "incident.json").write_text(
        json.dumps(
            {
                "incident_id": incident_id,
                "status": "approved",
                "step": "amazon_download",
                "failure_class": "run_failed",
                "message": "test",
                "year": 2026,
                "month": 1,
                "ym": "2026-01",
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
    (plan_dir / "plan.json").write_text(
        json.dumps(
            {
                "incident_id": incident_id,
                "generated_at": "2026-02-17T00:00:00+00:00",
                "summary": "test plan",
                "card_summary": {
                    "plan": "test plan",
                    "first_step": "verify",
                    "eta_minutes": 20,
                    "risk": "low",
                    "approval": "required",
                },
                "root_cause_hypotheses": [],
                "actions": [{"id": "A1", "title": "verify", "priority": "P0", "risk": "low"}],
                "verification_commands": ["echo ok"],
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
            str(SCRIPT_DIR / "error_handoff_prepare.py"),
            "--root",
            str(root),
            "--incident-id",
            incident_id,
        ]
    )
    assert result.get("status") == "ok"
    assert result.get("handoff_status") == "handed_off"
    assert Path(str(result.get("handoff_json") or "")).exists()

    updated_incident = json.loads((incident_dir / "incident.json").read_text(encoding="utf-8"))
    assert updated_incident.get("status") == "handed_off"
    assert (incident_dir / "status.txt").read_text(encoding="utf-8").strip() == "handed_off"

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from dashboard.services import core_runs


def test_capture_failed_run_incident_sets_incident_id(monkeypatch, tmp_path: Path) -> None:
    skill_root = tmp_path / "skill"
    scripts_dir = skill_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "error_capture.py").write_text("# placeholder\n", encoding="utf-8")

    meta_path = tmp_path / "run_meta.json"
    meta = {
        "run_id": "run_test_001",
        "status": "failed",
        "returncode": 1,
        "actor": {"channel": "test", "id": "tester"},
        "params": {"year": 2026, "month": 1, "mode": "amazon_download"},
    }

    def _fake_run(cmd, cwd, capture_output, text, check, timeout):  # noqa: ANN001
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=json.dumps({"status": "ok", "incident_id": "incident_unit_001"}),
            stderr="",
        )

    monkeypatch.setattr(core_runs, "SKILL_ROOT", skill_root)
    monkeypatch.setattr(core_runs.subprocess, "run", _fake_run)

    core_runs._capture_failed_run_incident(
        meta_path=meta_path,
        meta=meta,
        reason="unit_test",
        inferred_from="test",
    )

    saved = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved.get("error_incident_id") == "incident_unit_001"
    assert saved.get("error_capture_attempted_at")


def test_capture_failed_run_incident_skips_pytest_artifact_noise(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    skill_root = tmp_path / "skill"
    scripts_dir = skill_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "error_capture.py").write_text("# placeholder\n", encoding="utf-8")

    meta_path = tmp_path / "run_meta.json"
    meta = {
        "run_id": "run_test_002",
        "status": "failed",
        "returncode": -1,
        "actor": {"channel": "test", "id": "tester"},
        "log_path": "C:/Users/test/AppData/Local/Temp/pytest-of-user/pytest-1/test_case/run.log",
        "params": {"year": 2026, "month": 1, "mode": "amazon_download"},
    }

    def _unexpected_run(*args, **kwargs):  # noqa: ANN001, ANN002
        raise AssertionError("error_capture.py must not run for pytest artifact noise")

    monkeypatch.setattr(core_runs, "SKILL_ROOT", skill_root)
    monkeypatch.setattr(core_runs.subprocess, "run", _unexpected_run)

    core_runs._capture_failed_run_incident(
        meta_path=meta_path,
        meta=meta,
        reason="process_ended_without_final_status",
        inferred_from="test",
    )

    saved = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved.get("error_incident_id") in ("", None)
    assert saved.get("error_capture_attempted_at")
    assert saved.get("error_capture_skipped_reason") == "test_artifact_run"

    audit_path = (
        tmp_path
        / "artifacts"
        / "mfcloud-expense-receipt-reconcile"
        / "2026-01"
        / "reports"
        / "audit_log.jsonl"
    )
    lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    event = json.loads(lines[-1])
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    assert event.get("event_type") == "error_incident"
    assert event.get("action") == "capture"
    assert event.get("status") == "skipped"
    assert details.get("suppression_reason") == "test_artifact_run"


def test_capture_failed_run_incident_skips_auth_required_noise(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    skill_root = tmp_path / "skill"
    scripts_dir = skill_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "error_capture.py").write_text("# placeholder\n", encoding="utf-8")

    log_path = Path.cwd() / ".pytest_cache" / "auth_required_capture_test.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "[AUTH_REQUIRED] Rakuten order list\nAUTH_REQUIRED: Rakuten order list (still on login page)\n",
        encoding="utf-8",
    )

    meta_path = tmp_path / "run_meta.json"
    meta = {
        "run_id": "run_test_003",
        "status": "failed",
        "returncode": 1,
        "actor": {"channel": "test", "id": "tester"},
        "log_path": str(log_path),
        "params": {"year": 2026, "month": 1, "mode": "rakuten_download"},
    }

    def _unexpected_run(*args, **kwargs):  # noqa: ANN001, ANN002
        raise AssertionError("error_capture.py must not run for AUTH_REQUIRED noise")

    monkeypatch.setattr(core_runs, "SKILL_ROOT", skill_root)
    monkeypatch.setattr(core_runs.subprocess, "run", _unexpected_run)

    core_runs._capture_failed_run_incident(
        meta_path=meta_path,
        meta=meta,
        reason="worker_exit",
        inferred_from="test",
    )

    saved = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved.get("error_incident_id") in ("", None)
    assert saved.get("error_capture_attempted_at")
    assert saved.get("error_capture_skipped_reason") == "auth_required"

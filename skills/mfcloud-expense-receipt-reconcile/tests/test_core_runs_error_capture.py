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


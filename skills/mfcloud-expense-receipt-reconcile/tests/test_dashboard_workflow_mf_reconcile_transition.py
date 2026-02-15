from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
import pytest

from services import core
from dashboard.services import core_runs


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_workflow_gate_keeps_mf_reconcile_until_both_printed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    root = core._artifact_root()
    (root / ym).mkdir(parents=True, exist_ok=True)
    reports_dir = root / ym / "reports"

    _touch(root / ym / "amazon" / "orders.jsonl")
    _touch(root / ym / "rakuten" / "orders.jsonl")
    core._write_json(
        reports_dir / "preflight.json",
        {"status": "success", "year": 2026, "month": 1},
    )
    core._write_json(
        reports_dir / "workflow.json",
        {
            "amazon": {"confirmed_at": "2026-02-01T00:00:00", "printed_at": "2026-02-01T00:01:00"},
            "rakuten": {"confirmed_at": "2026-02-01T00:02:00"},
        },
    )

    state = core._workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "rakuten_decide_print"
    assert "mf_reconcile" not in state["allowed_run_modes"]
    with pytest.raises(HTTPException):
        core._assert_run_mode_allowed(2026, 1, "mf_reconcile")


def test_infer_run_exit_code_parses_embedded_json_fragment(tmp_path: Path) -> None:
    log_path = tmp_path / "run.log"
    log_path.write_text(
        "INFO: start\n"
        "TRACE: preflight done {\"status\":\"running\"}\n"
        "TRACE: completion summary: {'status': 'success', 'code': 0}\n"
        "INFO: done [{\"status\":\"success\", \"value\": 1}] tail\n",
        encoding="utf-8",
    )

    code, source = core_runs._infer_run_exit_code_from_log(log_path)
    assert code == 0
    assert source in {"line_json", "json_scan"}

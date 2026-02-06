from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from dashboard.services.core_runs import (
    _append_audit_event,
    _assert_run_mode_allowed,
    _assert_source_action_allowed,
    _workflow_state_for_ym,
)


def _artifact_root(ax_home: Path) -> Path:
    return ax_home / "artifacts" / "mfcloud-expense-receipt-reconcile"


def _reports_dir(ax_home: Path, ym: str) -> Path:
    return _artifact_root(ax_home) / ym / "reports"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_workflow_state_next_step_progression(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"

    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "preflight"
    assert state["allowed_run_modes"] == ["preflight"]

    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "amazon_download"

    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "amazon_decide_print"

    _write_json(
        _reports_dir(tmp_path, ym) / "workflow.json",
        {"amazon": {"confirmed_at": "2026-02-01T00:00:00", "printed_at": "2026-02-01T00:01:00"}},
    )
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "rakuten_download"

    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "rakuten_decide_print"

    _write_json(
        _reports_dir(tmp_path, ym) / "workflow.json",
        {
            "amazon": {"confirmed_at": "2026-02-01T00:00:00", "printed_at": "2026-02-01T00:01:00"},
            "rakuten": {"confirmed_at": "2026-02-01T00:02:00", "printed_at": "2026-02-01T00:03:00"},
        },
    )
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "mf_reconcile"

    _write_json(_reports_dir(tmp_path, ym) / "missing_evidence_candidates.json", {"rows": [], "counts": {}})
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "done"
    assert state["allowed_run_modes"] == []


def test_assert_run_mode_allowed_rejects_skip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})

    with pytest.raises(HTTPException) as exc:
        _assert_run_mode_allowed(2026, 1, "mf_reconcile")
    assert exc.value.status_code == 409
    assert "Workflow order violation" in str(exc.value.detail)


def test_assert_source_action_allowed_enforces_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")

    # Amazon confirmation is allowed after Amazon download.
    _assert_source_action_allowed(2026, 1, "amazon", "confirm")

    # Rakuten actions are blocked until Amazon confirm+print is done.
    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")
    with pytest.raises(HTTPException) as exc:
        _assert_source_action_allowed(2026, 1, "rakuten", "confirm")
    assert exc.value.status_code == 409
    assert "amazon decide/print must be completed" in str(exc.value.detail)


def test_append_audit_event_writes_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    _append_audit_event(
        year=2026,
        month=1,
        event_type="run",
        action="preflight",
        status="started",
        actor={"channel": "dashboard", "id": "tester"},
        mode="preflight",
        run_id="run_20260206_120000",
        details={"sample": True},
    )
    log_path = _reports_dir(tmp_path, "2026-01") / "audit_log.jsonl"
    assert log_path.exists()
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event_type"] == "run"
    assert entry["action"] == "preflight"
    assert entry["status"] == "started"
    assert entry["actor"]["id"] == "tester"

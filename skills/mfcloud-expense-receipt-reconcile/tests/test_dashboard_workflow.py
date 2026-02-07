from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

import dashboard.services.core_runs as core_runs
from dashboard.services.core_runs import (
    _append_audit_event,
    _assert_run_mode_allowed,
    _assert_source_action_allowed,
    _pid_alive,
    _safe_run_id,
    _start_run,
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
    assert state["next_step"] == "amazon_or_rakuten_download"
    assert state["allowed_run_modes"] == ["preflight", "amazon_download", "rakuten_download"]

    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "amazon_decide_print"
    assert state["allowed_run_modes"] == ["preflight", "amazon_download", "rakuten_download", "amazon_print"]

    _write_json(
        _reports_dir(tmp_path, ym) / "workflow.json",
        {"amazon": {"confirmed_at": "2026-02-01T00:00:00", "printed_at": "2026-02-01T00:01:00"}},
    )
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "mf_reconcile"
    assert state["allowed_run_modes"] == ["preflight", "amazon_download", "rakuten_download", "amazon_print", "mf_reconcile"]

    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "mf_reconcile"
    assert state["allowed_run_modes"] == [
        "preflight",
        "amazon_download",
        "rakuten_download",
        "amazon_print",
        "rakuten_print",
        "mf_reconcile",
    ]

    _write_json(
        _reports_dir(tmp_path, ym) / "workflow.json",
        {
            "amazon": {"confirmed_at": "2026-02-01T00:00:00", "printed_at": "2026-02-01T00:01:00"},
            "rakuten": {"confirmed_at": "2026-02-01T00:02:00", "printed_at": "2026-02-01T00:03:00"},
        },
    )
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "mf_reconcile"
    assert state["allowed_run_modes"] == [
        "preflight",
        "amazon_download",
        "rakuten_download",
        "amazon_print",
        "rakuten_print",
        "mf_reconcile",
    ]

    _write_json(_reports_dir(tmp_path, ym) / "missing_evidence_candidates.json", {"rows": [], "counts": {}})
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "done"
    assert state["allowed_run_modes"] == [
        "preflight",
        "amazon_download",
        "rakuten_download",
        "amazon_print",
        "rakuten_print",
        "mf_reconcile",
    ]


def test_assert_run_mode_allowed_rejects_skip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})

    with pytest.raises(HTTPException) as exc:
        _assert_run_mode_allowed(2026, 1, "mf_reconcile")
    assert exc.value.status_code == 409
    assert "Workflow order violation" in str(exc.value.detail)


def test_assert_run_mode_allowed_accepts_preflight_anytime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")

    # Preflight can be re-run regardless of current next_step.
    _assert_run_mode_allowed(2026, 1, "preflight")


def test_assert_run_mode_allowed_accepts_amazon_redownload_after_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")
    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")
    _write_json(
        _reports_dir(tmp_path, ym) / "workflow.json",
        {
            "amazon": {"confirmed_at": "2026-02-01T00:00:00", "printed_at": "2026-02-01T00:01:00"},
            "rakuten": {"confirmed_at": "2026-02-01T00:02:00", "printed_at": "2026-02-01T00:03:00"},
        },
    )
    _write_json(_reports_dir(tmp_path, ym) / "missing_evidence_candidates.json", {"rows": [], "counts": {}})

    _assert_run_mode_allowed(2026, 1, "amazon_download")


def test_assert_run_mode_allowed_accepts_mf_reconcile_after_only_rakuten_print_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")
    _write_json(
        _reports_dir(tmp_path, ym) / "workflow.json",
        {"rakuten": {"confirmed_at": "2026-02-01T00:02:00", "printed_at": "2026-02-01T00:03:00"}},
    )

    _assert_run_mode_allowed(2026, 1, "mf_reconcile")


def test_workflow_state_next_step_uses_rakuten_branch_when_only_rakuten_downloaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")

    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "rakuten_decide_print"
    assert "rakuten_print" in state["allowed_run_modes"]
    assert "amazon_download" in state["allowed_run_modes"]
    assert "mf_reconcile" not in state["allowed_run_modes"]


def test_assert_source_action_allowed_enforces_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")

    # Amazon confirmation is allowed after Amazon download.
    _assert_source_action_allowed(2026, 1, "amazon", "confirm")

    # Rakuten confirmation is allowed independently after Rakuten download.
    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")
    _assert_source_action_allowed(2026, 1, "rakuten", "confirm")

    # Print still requires confirmation for each source.
    with pytest.raises(HTTPException) as exc:
        _assert_source_action_allowed(2026, 1, "rakuten", "print")
    assert exc.value.status_code == 409
    assert "rakuten confirmation is required before rakuten print" in str(exc.value.detail)


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


def test_pid_alive_windows_tasklist_positive_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_runs.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        core_runs.subprocess,
        "check_output",
        lambda *args, **kwargs: (
            "Image Name                     PID Session Name        Session#    Mem Usage\n"
            "========================= ======== ================ =========== ============\n"
            "python.exe                   15408 Console                    1      4,168 K\n"
        ),
    )
    assert _pid_alive(15408) is True


def test_pid_alive_windows_tasklist_negative_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_runs.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        core_runs.subprocess,
        "check_output",
        lambda *args, **kwargs: "INFO: No tasks are running which match the specified criteria.\n",
    )
    assert _pid_alive(15408) is False


def test_safe_run_id_accepts_legacy_and_microsecond_ids() -> None:
    assert _safe_run_id("run_20260207_050353") == "run_20260207_050353"
    assert _safe_run_id("run_20260207_050353_123456") == "run_20260207_050353_123456"


def test_start_run_amazon_download_resets_only_amazon_workflow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")
    _write_json(
        _reports_dir(tmp_path, ym) / "workflow.json",
        {
            "amazon": {"confirmed_at": "2026-02-01T00:00:00", "printed_at": "2026-02-01T00:01:00"},
            "rakuten": {"confirmed_at": "2026-02-01T00:02:00", "printed_at": "2026-02-01T00:03:00"},
        },
    )

    class _PopenDummy:
        pid = 12345

    monkeypatch.setattr("dashboard.services.core_runs.subprocess.Popen", lambda *args, **kwargs: _PopenDummy())

    def _no_thread(*args, **kwargs):
        class _DummyThread:
            def start(self) -> None:
                return None

        return _DummyThread()

    monkeypatch.setattr("dashboard.services.core_runs.threading.Thread", _no_thread)

    result = _start_run(
        {
            "year": 2026,
            "month": 1,
            "mode": "amazon_download",
            "mfcloud_url": "https://expense.example/list",
            "auth_handoff": False,
            "auto_receipt_name": True,
        }
    )
    assert result["status"] == "running"

    workflow = json.loads((_reports_dir(tmp_path, ym) / "workflow.json").read_text(encoding="utf-8"))
    assert "amazon" not in workflow
    assert "rakuten" in workflow

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
    assert state["next_step"] == "rakuten_download"
    assert state["allowed_run_modes"] == ["preflight", "amazon_download", "rakuten_download", "amazon_print"]

    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")
    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "rakuten_decide_print"
    assert state["allowed_run_modes"] == [
        "preflight",
        "amazon_download",
        "rakuten_download",
        "amazon_print",
        "rakuten_print",
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


def test_assert_run_mode_allowed_rejects_mf_reconcile_until_both_sources_downloaded(
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

    with pytest.raises(HTTPException) as exc:
        _assert_run_mode_allowed(2026, 1, "mf_reconcile")
    assert exc.value.status_code == 409
    assert "Workflow order violation" in str(exc.value.detail)


def test_assert_run_mode_allowed_rejects_mf_reconcile_when_other_source_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")
    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")
    _write_json(
        _reports_dir(tmp_path, ym) / "workflow.json",
        {"amazon": {"confirmed_at": "2026-02-01T00:00:00", "printed_at": "2026-02-01T00:01:00"}},
    )

    with pytest.raises(HTTPException) as exc:
        _assert_run_mode_allowed(2026, 1, "mf_reconcile")
    assert exc.value.status_code == 409
    assert "Workflow order violation" in str(exc.value.detail)


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


def test_workflow_state_treats_failed_download_as_not_completed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")
    _write_json(_reports_dir(tmp_path, ym) / "workflow.json", {"rakuten": {"download_status": "failed"}})

    state = _workflow_state_for_ym(2026, 1)
    assert state["rakuten"]["downloaded"] is False
    assert state["next_step"] == "amazon_or_rakuten_download"
    assert "rakuten_print" not in state["allowed_run_modes"]


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


def test_run_worker_records_download_failure_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    reports_dir = _reports_dir(tmp_path, ym)
    _write_json(
        reports_dir / "workflow.json",
        {"rakuten": {"confirmed_at": "2026-02-08T14:00:00", "printed_at": "2026-02-08T14:01:00"}},
    )

    meta_path = _artifact_root(tmp_path) / "_runs" / "run_20260208_141843_228745.json"
    _write_json(
        meta_path,
        {
            "run_id": "run_20260208_141843_228745",
            "status": "running",
            "params": {"year": 2026, "month": 1, "mode": "rakuten_download"},
        },
    )

    class _ProcessDummy:
        def wait(self) -> int:
            return 1

    core_runs._run_worker(_ProcessDummy(), meta_path)

    workflow = json.loads((reports_dir / "workflow.json").read_text(encoding="utf-8"))
    rakuten = workflow.get("rakuten") or {}
    assert rakuten.get("download_status") == "failed"
    assert "downloaded_at" not in rakuten
    assert "confirmed_at" not in rakuten
    assert "printed_at" not in rakuten


def test_reconcile_running_jobs_infers_success_from_log_when_worker_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    runs_dir = _artifact_root(tmp_path) / "_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = "run_20260208_143200_606051"
    log_path = runs_dir / f"{run_id}.log"
    log_path.write_text(
        '[run] Rakuten download done\n{\n  "status": "success",\n  "data": {"output_root": "dummy"}\n}\n',
        encoding="utf-8",
    )
    meta_path = runs_dir / f"{run_id}.json"
    _write_json(
        meta_path,
        {
            "run_id": run_id,
            "status": "running",
            "pid": 31592,
            "actor": {"channel": "dashboard", "id": "tester"},
            "log_path": str(log_path),
            "params": {"year": 2026, "month": 1, "mode": "rakuten_download"},
        },
    )

    monkeypatch.setattr(core_runs, "_pid_alive", lambda pid: False)
    core_runs._reconcile_running_jobs()

    reconciled = json.loads(meta_path.read_text(encoding="utf-8"))
    assert reconciled["status"] == "success"
    assert reconciled["returncode"] == 0
    assert reconciled.get("finished_at")

    workflow = json.loads((_reports_dir(tmp_path, ym) / "workflow.json").read_text(encoding="utf-8"))
    rakuten = workflow.get("rakuten") or {}
    assert rakuten.get("download_status") == "success"
    assert rakuten.get("downloaded_at")

    audit_path = _reports_dir(tmp_path, ym) / "audit_log.jsonl"
    entries = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    last = entries[-1]
    assert last["run_id"] == run_id
    assert last["status"] == "success"
    details = last.get("details") or {}
    assert details.get("reason") == "process_ended_reconciled_from_log"
    assert details.get("inferred_from") == "final_json"


def test_reconcile_running_jobs_marks_failed_when_status_not_inferable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    runs_dir = _artifact_root(tmp_path) / "_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = "run_20260208_094248_545973"
    log_path = runs_dir / f"{run_id}.log"
    log_path.write_text("[run] Amazon download start\n", encoding="utf-8")
    meta_path = runs_dir / f"{run_id}.json"
    _write_json(
        meta_path,
        {
            "run_id": run_id,
            "status": "running",
            "pid": 12345,
            "actor": {"channel": "dashboard", "id": "tester"},
            "log_path": str(log_path),
            "params": {"year": 2026, "month": 1, "mode": "amazon_download"},
        },
    )

    monkeypatch.setattr(core_runs, "_pid_alive", lambda pid: False)
    core_runs._reconcile_running_jobs()

    reconciled = json.loads(meta_path.read_text(encoding="utf-8"))
    assert reconciled["status"] == "failed"
    assert reconciled["returncode"] == -1
    assert reconciled.get("finished_at")

    workflow = json.loads((_reports_dir(tmp_path, ym) / "workflow.json").read_text(encoding="utf-8"))
    amazon = workflow.get("amazon") or {}
    assert amazon.get("download_status") == "failed"
    assert "downloaded_at" not in amazon

    audit_path = _reports_dir(tmp_path, ym) / "audit_log.jsonl"
    entries = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    last = entries[-1]
    assert last["run_id"] == run_id
    assert last["status"] == "failed"
    details = last.get("details") or {}
    assert details.get("reason") == "process_ended_without_final_status"

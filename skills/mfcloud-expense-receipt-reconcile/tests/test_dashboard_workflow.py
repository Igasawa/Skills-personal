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


def test_workflow_state_keeps_mf_step_pending_when_draft_result_not_success(
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
    _write_json(_reports_dir(tmp_path, ym) / "mf_draft_create_result.json", {"status": "partial_success", "data": {}})

    state = _workflow_state_for_ym(2026, 1)
    assert state["mf"]["reconciled"] is True
    assert state["mf"]["drafted"] is False
    assert state["mf"]["step_done"] is False
    assert state["next_step"] == "mf_reconcile"


def test_workflow_state_includes_mf_summary_counts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    _write_json(
        _reports_dir(tmp_path, ym) / "missing_evidence_candidates.json",
        {"rows": [{"mf_expense_id": "MF-1"}], "counts": {"mf_missing_evidence": 4}},
    )
    _write_json(
        _reports_dir(tmp_path, ym) / "mf_draft_create_result.json",
        {"status": "partial_success", "data": {"targets_total": 3, "created": 2, "failed": 1}},
    )

    state = _workflow_state_for_ym(2026, 1)
    summary = state["mf"]["summary"]
    assert summary["missing_candidates"] == 4
    assert summary["targets_total"] == 3
    assert summary["created"] == 2
    assert summary["failed"] == 1
    assert summary["status"] == "partial_success"


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


def test_workflow_state_prioritizes_provider_ingest_when_provider_inbox_has_pending_files(
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
            "amazon": {"confirmed_at": "2026-02-08T10:00:00", "printed_at": "2026-02-08T10:10:00"},
            "rakuten": {"confirmed_at": "2026-02-08T10:20:00", "printed_at": "2026-02-08T10:30:00"},
        },
    )
    _touch(_artifact_root(tmp_path) / ym / "manual" / "inbox" / "chatgpt" / "invoice.pdf")

    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "provider_ingest"
    assert state["providers"]["pending_total"] == 1
    assert state["providers"]["providers"]["chatgpt"]["pending_files"] == 1
    assert "mf_reconcile" in state["allowed_run_modes"]


def test_workflow_state_prioritizes_provider_ingest_when_shared_inbox_has_pending_files(
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
            "amazon": {"confirmed_at": "2026-02-08T10:00:00", "printed_at": "2026-02-08T10:10:00"},
            "rakuten": {"confirmed_at": "2026-02-08T10:20:00", "printed_at": "2026-02-08T10:30:00"},
        },
    )
    _touch(_artifact_root(tmp_path) / ym / "manual" / "inbox" / "invoice_shared.pdf")

    state = _workflow_state_for_ym(2026, 1)
    assert state["next_step"] == "provider_ingest"
    assert state["providers"]["pending_total"] == 1
    assert state["providers"]["providers"]["shared"]["pending_files"] == 1
    assert "mf_reconcile" in state["allowed_run_modes"]


def test_workflow_state_provider_step_is_not_done_before_any_provider_ingest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))

    state = _workflow_state_for_ym(2026, 1)
    assert state["providers"]["pending_total"] == 0
    assert state["providers"]["attempted"] is False
    assert state["providers"]["step_done"] is False


def test_workflow_state_provider_step_done_after_provider_import_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    provider_report = _artifact_root(tmp_path) / "2026-01" / "manual" / "reports" / "provider_import_last.json"
    _write_json(
        provider_report,
        {
            "status": "ok",
            "ym": "2026-01",
            "ingestion_channel": "provider_inbox",
            "provider_filter": ["aquavoice", "claude", "chatgpt", "gamma"],
        },
    )

    state = _workflow_state_for_ym(2026, 1)
    assert state["providers"]["pending_total"] == 0
    assert state["providers"]["attempted"] is True
    assert state["providers"]["step_done"] is True


def test_workflow_state_provider_step_ignores_manual_import_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    provider_report = _artifact_root(tmp_path) / "2026-01" / "manual" / "reports" / "provider_import_last.json"
    _write_json(
        provider_report,
        {
            "status": "ok",
            "ym": "2026-01",
            "ingestion_channel": "manual_inbox",
            "provider_filter": [],
        },
    )

    state = _workflow_state_for_ym(2026, 1)
    assert state["providers"]["pending_total"] == 0
    assert state["providers"]["attempted"] is False
    assert state["providers"]["step_done"] is False


def test_workflow_state_provider_step_not_done_by_provider_download_report_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    provider_download_result = _reports_dir(tmp_path, "2026-01") / "provider_download_result.json"
    _write_json(provider_download_result, {"status": "ok", "ym": "2026-01"})

    state = _workflow_state_for_ym(2026, 1)
    assert state["providers"]["pending_total"] == 0


def test_workflow_state_tracks_mf_bulk_upload_step_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"

    state = _workflow_state_for_ym(2026, 1)
    assert state["mf_bulk_upload"]["attempted"] is False
    assert state["mf_bulk_upload"]["done"] is False
    assert state["mf_bulk_upload"]["submitted_count"] == 0

    _write_json(
        _reports_dir(tmp_path, ym) / "mf_bulk_upload_result.json",
        {
            "status": "ok",
            "data": {
                "files_found": 3,
                "read_count": 3,
                "queued_count": 2,
                "submitted_count": 2,
            },
        },
    )

    state = _workflow_state_for_ym(2026, 1)
    assert state["mf_bulk_upload"]["attempted"] is True
    assert state["mf_bulk_upload"]["done"] is True
    assert state["mf_bulk_upload"]["status"] == "ok"
    assert state["mf_bulk_upload"]["files_found"] == 3
    assert state["mf_bulk_upload"]["read_count"] == 3
    assert state["mf_bulk_upload"]["queued_count"] == 2
    assert state["mf_bulk_upload"]["submitted_count"] == 2
    assert state["providers"]["attempted"] is False
    assert state["providers"]["step_done"] is False


def test_workflow_state_archive_state_defaults_to_not_created(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    state = _workflow_state_for_ym(2026, 1)
    assert state["archive"]["created"] is False
    assert state["archive"]["created_at"] is None
    assert state["archive"]["archived_to"] is None


def test_workflow_state_archive_state_reads_latest_manual_archive_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    audit_log = _reports_dir(tmp_path, ym) / "audit_log.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    audit_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": "2026-02-09T11:00:00",
                        "ym": ym,
                        "event_type": "archive",
                        "action": "manual_archive",
                        "status": "failed",
                        "details": {"reason": "test"},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "ts": "2026-02-09T11:03:42",
                        "ym": ym,
                        "event_type": "archive",
                        "action": "manual_archive",
                        "status": "success",
                        "details": {
                            "archived_to": "C:\\archive\\20260209_110342",
                            "include_pdfs": True,
                            "include_debug": False,
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    state = _workflow_state_for_ym(2026, 1)
    assert state["archive"]["created"] is True
    assert state["archive"]["created_at"] == "2026-02-09T11:03:42"
    assert state["archive"]["archived_to"] == "C:\\archive\\20260209_110342"
    assert state["archive"]["include_pdfs"] is True
    assert state["archive"]["include_debug"] is False


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


def test_start_run_mf_reconcile_sets_mf_draft_create_default_true(
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

    captured_cmd: list[str] = []

    class _PopenDummy:
        pid = 23456

    def _fake_popen(cmd, *args, **kwargs):  # noqa: ANN001, ANN002
        captured_cmd.extend([str(c) for c in cmd])
        return _PopenDummy()

    monkeypatch.setattr("dashboard.services.core_runs.subprocess.Popen", _fake_popen)

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
            "mode": "mf_reconcile",
            "mfcloud_url": "https://expense.example/outgo_input",
            "auth_handoff": False,
            "auto_receipt_name": True,
        }
    )
    assert result["status"] == "running"
    assert "--mf-draft-create" in captured_cmd


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

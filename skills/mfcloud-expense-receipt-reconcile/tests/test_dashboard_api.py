from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from dashboard.routes import api as api_routes
from dashboard.services import core_runs


def _artifact_root(ax_home: Path) -> Path:
    return ax_home / "artifacts" / "mfcloud-expense-receipt-reconcile"


def _reports_dir(ax_home: Path, ym: str) -> Path:
    return _artifact_root(ax_home) / ym / "reports"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _read_audit_entries(ax_home: Path, ym: str) -> list[dict[str, Any]]:
    path = _reports_dir(ax_home, ym) / "audit_log.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        out.append(json.loads(s))
    return out


def _create_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(api_routes.create_api_router())
    return TestClient(app)


def test_api_run_rejects_out_of_order_and_writes_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/runs",
        json={
            "year": 2026,
            "month": 1,
            "mode": "mf_reconcile",
            "mfcloud_url": "https://expense.example/list",
        },
    )
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "Workflow order violation" in detail

    entries = _read_audit_entries(tmp_path, "2026-01")
    assert entries
    last = entries[-1]
    assert last["event_type"] == "run"
    assert last["action"] == "mf_reconcile"
    assert last["status"] == "rejected"
    assert "Workflow order violation" in str((last.get("details") or {}).get("reason"))


def test_api_exclusion_rejects_without_preflight_and_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post("/api/exclusions/2026-01", json={"source": "amazon", "exclude": []})
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "preflight is required" in detail

    entries = _read_audit_entries(tmp_path, "2026-01")
    assert entries
    last = entries[-1]
    assert last["event_type"] == "source_action"
    assert last["action"] == "confirm"
    assert last["status"] == "rejected"
    assert last["source"] == "amazon"


def test_api_confirm_print_prepare_and_complete_success_write_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(reports / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")
    _touch(reports / "print_all.ps1", "Write-Host 'print'")
    _write_json(reports / "print_manifest.json", {"count": 2})
    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res_confirm = client.post(
        "/api/exclusions/2026-01",
        json={"source": "amazon", "exclude": [{"source": "amazon", "order_id": "A-1"}]},
    )
    assert res_confirm.status_code == 200
    assert res_confirm.json()["status"] == "ok"

    res_prepare = client.post("/api/print/2026-01/amazon")
    assert res_prepare.status_code == 200
    body_prepare = res_prepare.json()
    assert body_prepare["status"] == "ok"
    assert body_prepare["source"] == "amazon"
    assert body_prepare["count"] == 2
    assert body_prepare["print_script"].endswith("print_all.ps1")
    assert "powershell -NoProfile -ExecutionPolicy Bypass -File" in body_prepare["print_command"]
    assert calls
    assert any(any("collect_print.py" in part for part in call) for call in calls)
    assert any("--skip-shortcut-download" in call for call in calls)

    workflow = json.loads((reports / "workflow.json").read_text(encoding="utf-8"))
    assert (workflow.get("amazon") or {}).get("confirmed_at")
    assert (workflow.get("amazon") or {}).get("print_prepared_at")
    assert not (workflow.get("amazon") or {}).get("printed_at")

    res_complete = client.post("/api/print/2026-01/amazon/complete")
    assert res_complete.status_code == 200
    body_complete = res_complete.json()
    assert body_complete["status"] == "ok"
    assert body_complete["source"] == "amazon"
    assert body_complete["count"] == 2

    workflow = json.loads((reports / "workflow.json").read_text(encoding="utf-8"))
    assert (workflow.get("amazon") or {}).get("printed_at")

    entries = _read_audit_entries(tmp_path, "2026-01")
    actions = [(e.get("action"), e.get("status"), e.get("source")) for e in entries]
    assert ("confirm", "success", "amazon") in actions
    assert ("print_prepare", "success", "amazon") in actions
    assert ("print_complete", "success", "amazon") in actions


def test_api_print_prepare_resets_printed_at_and_runs_prepare_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(reports / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")
    _touch(reports / "print_all.ps1", "Write-Host 'print'")
    _write_json(
        reports / "workflow.json",
        {"amazon": {"confirmed_at": "2026-02-08T10:00:00", "printed_at": "2026-02-08T10:10:00"}},
    )

    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res_prepare = client.post("/api/print/2026-01/amazon")
    assert res_prepare.status_code == 200

    workflow = json.loads((reports / "workflow.json").read_text(encoding="utf-8"))
    assert (workflow.get("amazon") or {}).get("print_prepared_at")
    assert not (workflow.get("amazon") or {}).get("printed_at")

    assert len(calls) == 1
    assert any("collect_print.py" in part for part in calls[0])
    assert not any("print_all.ps1" in part for part in calls[0])


def test_api_rakuten_confirm_allowed_without_amazon_print(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")

    res_confirm = client.post(
        "/api/exclusions/2026-01",
        json={"source": "rakuten", "exclude": [{"source": "rakuten", "order_id": "R-1"}]},
    )
    assert res_confirm.status_code == 200
    assert res_confirm.json()["status"] == "ok"

    workflow = json.loads((_reports_dir(tmp_path, ym) / "workflow.json").read_text(encoding="utf-8"))
    assert (workflow.get("rakuten") or {}).get("confirmed_at")


def test_api_print_failure_writes_failed_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    _write_json(_reports_dir(tmp_path, ym) / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")

    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        call = [str(c) for c in cmd]
        calls.append(call)
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="OUT", stderr="ERR")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res_confirm = client.post(
        "/api/exclusions/2026-01",
        json={"source": "amazon", "exclude": [{"source": "amazon", "order_id": "A-1"}]},
    )
    assert res_confirm.status_code == 200

    res_print = client.post("/api/print/2026-01/amazon")
    assert res_print.status_code == 500
    assert "collect_print.py failed" in str(res_print.json().get("detail") or "")
    assert calls
    assert any(any("collect_print.py" in part for part in call) for call in calls)

    entries = _read_audit_entries(tmp_path, "2026-01")
    print_entries = [
        e for e in entries if e.get("event_type") == "source_action" and e.get("action") == "print_prepare"
    ]
    assert print_entries
    assert print_entries[-1].get("status") == "failed"
    assert print_entries[-1].get("source") == "amazon"
    assert "collect_print.py failed" in str((print_entries[-1].get("details") or {}).get("reason") or "")


def test_api_print_complete_rejects_without_prepare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(reports / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")
    _touch(reports / "print_all.ps1", "Write-Host 'print'")

    res_confirm = client.post(
        "/api/exclusions/2026-01",
        json={"source": "amazon", "exclude": [{"source": "amazon", "order_id": "A-1"}]},
    )
    assert res_confirm.status_code == 200

    res_complete = client.post("/api/print/2026-01/amazon/complete")
    assert res_complete.status_code == 409
    assert "Print preparation is required" in str(res_complete.json().get("detail") or "")

    entries = _read_audit_entries(tmp_path, "2026-01")
    complete_entries = [
        e for e in entries if e.get("event_type") == "source_action" and e.get("action") == "print_complete"
    ]
    assert complete_entries
    assert complete_entries[-1].get("status") == "rejected"
    assert complete_entries[-1].get("source") == "amazon"


def test_api_stop_run_writes_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_id = "run_20260206_120000"
    meta = {
        "run_id": run_id,
        "status": "running",
        "started_at": "2026-02-06T12:00:00",
        "pid": None,
        "params": {"year": 2026, "month": 1, "mode": "amazon_download"},
    }
    _write_json(_artifact_root(tmp_path) / "_runs" / f"{run_id}.json", meta)

    res = client.post(f"/api/runs/{run_id}/stop")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"

    entries = _read_audit_entries(tmp_path, "2026-01")
    assert entries
    last = entries[-1]
    assert last["event_type"] == "run"
    assert last["action"] == "stop"
    assert last["status"] == "success"
    assert last["run_id"] == run_id


def test_api_step_reset_download_clears_source_and_mf_reports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    root = _artifact_root(tmp_path) / ym
    reports_dir = _reports_dir(tmp_path, ym)

    _touch(root / "amazon" / "orders.jsonl", '{"order_id":"A-1"}\n')
    _touch(root / "amazon" / "pdfs" / "A-1.pdf", "%PDF-1.4\n")
    _touch(root / "rakuten" / "orders.jsonl", '{"order_id":"R-1"}\n')
    _write_json(
        reports_dir / "workflow.json",
        {
            "amazon": {"confirmed_at": "2026-02-01T00:00:00", "printed_at": "2026-02-01T00:01:00"},
            "rakuten": {"confirmed_at": "2026-02-01T00:02:00", "printed_at": "2026-02-01T00:03:00"},
        },
    )
    _touch(reports_dir / "missing_evidence_candidates.json", "{}")
    _touch(reports_dir / "missing_evidence_candidates.csv", "h1\n")
    _touch(reports_dir / "quality_gate.json", "{}")
    _touch(reports_dir / "monthly_thread.md", "# monthly\n")
    _touch(reports_dir / "print_manifest.json", "{}")
    _touch(reports_dir / "print_list.txt", "C:\\dummy.pdf\n")
    _touch(reports_dir / "print_all.ps1", "Write-Host 'print'\n")
    _write_json(
        reports_dir / "exclude_orders.json",
        {
            "ym": ym,
            "exclude": [
                {"source": "amazon", "order_id": "A-1"},
                {"source": "rakuten", "order_id": "R-1"},
            ],
            "updated_at": "2026-02-08T10:00:00",
        },
    )

    res = client.post("/api/steps/2026-01/reset/amazon_download")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["step"] == "amazon_download"
    assert body["source"] == "amazon"
    assert body["clear_download"] is True

    assert not (root / "amazon" / "orders.jsonl").exists()
    assert (root / "amazon" / "pdfs").exists()
    assert not any((root / "amazon" / "pdfs").iterdir())
    assert (root / "rakuten" / "orders.jsonl").exists()

    workflow = json.loads((reports_dir / "workflow.json").read_text(encoding="utf-8"))
    assert "amazon" not in workflow
    assert "rakuten" in workflow

    assert not (reports_dir / "missing_evidence_candidates.json").exists()
    assert not (reports_dir / "missing_evidence_candidates.csv").exists()
    assert not (reports_dir / "quality_gate.json").exists()
    assert not (reports_dir / "monthly_thread.md").exists()
    assert not (reports_dir / "print_manifest.json").exists()
    assert not (reports_dir / "print_list.txt").exists()
    assert not (reports_dir / "print_all.ps1").exists()
    exclusions = json.loads((reports_dir / "exclude_orders.json").read_text(encoding="utf-8"))
    assert exclusions["exclude"] == [{"source": "rakuten", "order_id": "R-1"}]

    entries = _read_audit_entries(tmp_path, ym)
    assert entries
    last = entries[-1]
    assert last["event_type"] == "step_reset"
    assert last["action"] == "amazon_download"
    assert last["status"] == "success"
    assert last["source"] == "amazon"


def test_api_step_reset_rejects_invalid_step(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post("/api/steps/2026-01/reset/unknown_step")
    assert res.status_code == 400
    assert "Invalid step id for reset." in str(res.json().get("detail"))


def test_api_step_reset_download_removes_exclusion_file_when_only_target_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    root = _artifact_root(tmp_path) / ym
    reports_dir = _reports_dir(tmp_path, ym)

    _touch(root / "amazon" / "orders.jsonl", '{"order_id":"A-1"}\n')
    _touch(root / "amazon" / "pdfs" / "A-1.pdf", "%PDF-1.4\n")
    _write_json(
        reports_dir / "exclude_orders.json",
        {
            "ym": ym,
            "exclude": [
                {"source": "amazon", "order_id": "A-1"},
                {"source": "amazon", "order_id": "A-2"},
            ],
            "updated_at": "2026-02-08T10:00:00",
        },
    )

    res = client.post("/api/steps/2026-01/reset/amazon_download")
    assert res.status_code == 200
    assert not (reports_dir / "exclude_orders.json").exists()


def test_api_archive_success_with_include_pdfs_and_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(
        reports / "workflow.json",
        {"amazon": {"confirmed_at": "2026-02-08T10:00:00", "printed_at": "2026-02-08T10:10:00"}},
    )
    _touch(reports / "quality_gate.json", "{}")

    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="Archived to: C:\\archive\\20260208_101530\n",
            stderr="",
        )

    monkeypatch.setattr(core_runs.subprocess, "run", _fake_run)

    res = client.post("/api/archive/2026-01")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["ym"] == "2026-01"
    assert body["archived_to"] == "C:\\archive\\20260208_101530"
    assert body["include_pdfs"] is True
    assert body["include_debug"] is False

    assert calls
    cmd = calls[0]
    assert any("archive_outputs.ps1" in part for part in cmd)
    assert "-IncludePdfs" in cmd
    assert "-IncludeDebug" not in cmd

    entries = _read_audit_entries(tmp_path, ym)
    archive_events = [e for e in entries if e.get("event_type") == "archive"]
    assert archive_events
    last = archive_events[-1]
    assert last["action"] == "manual_archive"
    assert last["status"] == "success"
    details = last.get("details") or {}
    assert details.get("archived_to") == "C:\\archive\\20260208_101530"
    assert details.get("include_pdfs") is True
    assert details.get("include_debug") is False


def test_api_archive_writes_excluded_pdfs_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    root = _artifact_root(tmp_path) / ym
    _write_json(
        reports / "workflow.json",
        {"amazon": {"confirmed_at": "2026-02-08T10:00:00", "printed_at": "2026-02-08T10:10:00"}},
    )
    pdf_path = root / "amazon" / "pdfs" / "AMZ-EXCLUDED.pdf"
    _touch(pdf_path, "%PDF-1.4\n")
    _touch(
        root / "amazon" / "orders.jsonl",
        json.dumps(
            {
                "order_id": "AMZ-EX-1",
                "order_date": "2026-01-25",
                "status": "ok",
                "include": False,
                "pdf_path": str(pdf_path),
            },
            ensure_ascii=False,
        )
        + "\n",
    )

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="Archived to: C:\\archive\\20260208_101530\n",
            stderr="",
        )

    monkeypatch.setattr(core_runs.subprocess, "run", _fake_run)

    res = client.post("/api/archive/2026-01")
    assert res.status_code == 200
    body = res.json()
    assert body["excluded_pdfs_count"] == 1

    manifest_path = Path(str(body["excluded_pdfs_manifest"]))
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["ym"] == "2026-01"
    assert payload["count"] == 1
    assert payload["rows"][0]["order_id"] == "AMZ-EX-1"
    assert payload["rows"][0]["pdf_name"] == "AMZ-EXCLUDED.pdf"


def test_api_archive_rejects_when_confirm_print_not_completed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    _touch(_reports_dir(tmp_path, ym) / "quality_gate.json", "{}")

    res = client.post("/api/archive/2026-01")
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "Workflow order violation" in detail

    entries = _read_audit_entries(tmp_path, ym)
    archive_events = [e for e in entries if e.get("event_type") == "archive"]
    assert archive_events
    last = archive_events[-1]
    assert last["action"] == "manual_archive"
    assert last["status"] == "rejected"
    assert "Workflow order violation" in str((last.get("details") or {}).get("reason"))


def test_api_archive_script_failure_returns_500(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(
        reports / "workflow.json",
        {"rakuten": {"confirmed_at": "2026-02-08T10:00:00", "printed_at": "2026-02-08T10:10:00"}},
    )
    _touch(reports / "quality_gate.json", "{}")

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="OUT", stderr="ERR")

    monkeypatch.setattr(core_runs.subprocess, "run", _fake_run)

    res = client.post("/api/archive/2026-01")
    assert res.status_code == 500
    detail = str(res.json().get("detail") or "")
    assert "archive_outputs.ps1 failed" in detail
    assert "stdout" in detail
    assert "stderr" in detail

    entries = _read_audit_entries(tmp_path, ym)
    archive_events = [e for e in entries if e.get("event_type") == "archive"]
    assert archive_events
    last = archive_events[-1]
    assert last["action"] == "manual_archive"
    assert last["status"] == "failed"

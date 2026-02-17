from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
import pytest

from dashboard.routes import api as api_routes
from dashboard.services import core_runs
from dashboard.services import core_scheduler
from services import core_scheduler as public_core_scheduler


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


def _touch_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


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
    _write_json(reports / "print_manifest.amazon.json", {"count": 2, "files": []})
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
    assert body_prepare["print_manifest"].endswith("print_manifest.amazon.json")
    assert body_prepare["print_list"].endswith("print_list.amazon.txt")
    assert body_prepare["print_command"] == "POST /api/print-run/2026-01/amazon"
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
    _write_json(reports / "print_manifest.amazon.json", {"count": 1, "files": []})
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


def test_api_print_run_by_source_merges_pdf_and_opens_manual_print(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(
        reports / "workflow.json",
        {"amazon": {"confirmed_at": "2026-02-08T10:00:00", "print_prepared_at": "2026-02-08T10:10:00"}},
    )
    existing_pdf = _artifact_root(tmp_path) / ym / "amazon" / "pdfs" / "A-1.pdf"
    _touch_pdf(existing_pdf)
    missing_pdf = _artifact_root(tmp_path) / ym / "amazon" / "pdfs" / "A-2.pdf"
    _write_json(
        reports / "print_manifest.amazon.json",
        {
            "count": 2,
            "source": "amazon",
            "files": [
                {"path": str(existing_pdf), "source": "amazon"},
                {"path": str(missing_pdf), "source": "amazon"},
            ],
        },
    )

    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/print-run/2026-01/amazon")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["source"] == "amazon"
    assert body["print_mode"] == "manual_open"
    assert body["count"] == 1
    assert body["missing_count"] == 1
    merged_pdf = Path(str(body["merged_pdf_path"]))
    assert merged_pdf.exists()
    assert merged_pdf.name == "print_merged_amazon.pdf"

    assert calls
    assert any("print_merged_amazon.pdf" in part for part in calls[0])

    entries = _read_audit_entries(tmp_path, ym)
    run_events = [e for e in entries if e.get("event_type") == "source_action" and e.get("action") == "print_run"]
    assert run_events
    last = run_events[-1]
    assert last.get("status") == "success"
    assert last.get("source") == "amazon"
    details = last.get("details") or {}
    assert details.get("mode") == "manual_open"
    assert details.get("missing_count") == 1
    assert str(details.get("merged_pdf_path") or "").endswith("print_merged_amazon.pdf")


def test_api_print_run_by_source_rejects_without_prepare(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    pdf_path = _artifact_root(tmp_path) / ym / "amazon" / "pdfs" / "A-1.pdf"
    _touch_pdf(pdf_path)
    _write_json(
        reports / "print_manifest.amazon.json",
        {"count": 1, "source": "amazon", "files": [{"path": str(pdf_path), "source": "amazon"}]},
    )

    res = client.post("/api/print-run/2026-01/amazon")
    assert res.status_code == 409
    assert "Print preparation is required" in str(res.json().get("detail") or "")

    entries = _read_audit_entries(tmp_path, ym)
    run_events = [e for e in entries if e.get("event_type") == "source_action" and e.get("action") == "print_run"]
    assert run_events
    assert run_events[-1].get("status") == "rejected"
    assert run_events[-1].get("source") == "amazon"


def test_api_print_run_by_source_rejects_when_manifest_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(
        reports / "workflow.json",
        {"rakuten": {"confirmed_at": "2026-02-08T10:00:00", "print_prepared_at": "2026-02-08T10:10:00"}},
    )

    res = client.post("/api/print-run/2026-01/rakuten")
    assert res.status_code == 404
    assert "print_manifest.rakuten.json not found" in str(res.json().get("detail") or "")

    entries = _read_audit_entries(tmp_path, ym)
    run_events = [e for e in entries if e.get("event_type") == "source_action" and e.get("action") == "print_run"]
    assert run_events
    assert run_events[-1].get("status") == "rejected"
    assert run_events[-1].get("source") == "rakuten"


def test_api_print_run_legacy_requires_explicit_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post("/api/print-run/2026-01")
    assert res.status_code == 400
    assert "Deprecated endpoint" in str(res.json().get("detail") or "")


def test_api_print_pdf_returns_manual_open_mode_without_direct_os_print(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    pdf_path = _artifact_root(tmp_path) / ym / "amazon" / "pdfs" / "AMZ-001.pdf"
    _touch(pdf_path, "%PDF-1.4\n")
    run_called = False

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal run_called
        run_called = True
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/print-pdf/2026-01/amazon/AMZ-001.pdf")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["file"] == "AMZ-001.pdf"
    assert body["pdf_url"] == f"/files/{ym}/pdf/amazon/AMZ-001.pdf"
    assert body["print_mode"] == "manual_open"
    assert run_called is False

    entries = _read_audit_entries(tmp_path, ym)
    print_events = [
        e for e in entries if e.get("event_type") == "source_action" and e.get("action") == "print_single_pdf"
    ]
    assert print_events
    last = print_events[-1]
    assert last.get("status") == "success"
    details = last.get("details") or {}
    assert details.get("file") == "AMZ-001.pdf"
    assert details.get("mode") == "manual_open"


def test_api_open_receipts_folder_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    root = _artifact_root(tmp_path) / ym
    _touch(root / "amazon" / "pdfs" / "A-1.pdf", "%PDF-1.4\n")
    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/2026-01/receipts")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    opened = Path(str(body["path"]))
    assert opened.exists()
    assert "amazon" in str(opened).lower()

    assert calls
    entries = _read_audit_entries(tmp_path, ym)
    folder_events = [
        e for e in entries if e.get("event_type") == "source_action" and e.get("action") == "open_receipts_folder"
    ]
    assert folder_events
    assert folder_events[-1].get("status") == "success"


def test_api_open_receipts_folder_creates_month_root_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/2026-01/receipts")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    opened = Path(str(body["path"]))
    assert opened.exists()
    assert opened.name == ym
    assert calls

    entries = _read_audit_entries(tmp_path, ym)
    folder_events = [
        e for e in entries if e.get("event_type") == "source_action" and e.get("action") == "open_receipts_folder"
    ]
    assert folder_events
    assert folder_events[-1].get("status") == "success"


def test_api_open_receipts_folder_alias_route_works(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    root = _artifact_root(tmp_path) / ym
    _touch(root / "rakuten" / "pdfs" / "R-1.pdf", "%PDF-1.4\n")

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/2026-01/receipt")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    opened = Path(str(body["path"]))
    assert opened.exists()


def test_api_open_receipts_folder_query_route_works(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    root = _artifact_root(tmp_path) / ym
    _touch(root / "amazon" / "pdfs" / "A-1.pdf", "%PDF-1.4\n")

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/receipts?ym=2026-01")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    opened = Path(str(body["path"]))
    assert opened.exists()


def test_api_open_receipts_folder_tolerates_windows_explorer_false_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    root = _artifact_root(tmp_path) / ym
    _touch(root / "amazon" / "pdfs" / "A-1.pdf", "%PDF-1.4\n")

    monkeypatch.setattr(api_routes.sys, "platform", "win32")

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/2026-01/receipts")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    opened = Path(str(body["path"]))
    assert opened.exists()


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
    _touch(reports_dir / "print_manifest.amazon.json", "{}")
    _touch(reports_dir / "print_manifest.rakuten.json", "{}")
    _touch(reports_dir / "print_list.txt", "C:\\dummy.pdf\n")
    _touch(reports_dir / "print_list.amazon.txt", "C:\\dummy-a.pdf\n")
    _touch(reports_dir / "print_list.rakuten.txt", "C:\\dummy-r.pdf\n")
    _touch(reports_dir / "print_all.ps1", "Write-Host 'print'\n")
    _touch(reports_dir / "print_merged_amazon.pdf", "%PDF-1.4\n")
    _touch(reports_dir / "print_merged_rakuten.pdf", "%PDF-1.4\n")
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
    assert not (reports_dir / "print_manifest.amazon.json").exists()
    assert not (reports_dir / "print_manifest.rakuten.json").exists()
    assert not (reports_dir / "print_list.txt").exists()
    assert not (reports_dir / "print_list.amazon.txt").exists()
    assert not (reports_dir / "print_list.rakuten.txt").exists()
    assert not (reports_dir / "print_all.ps1").exists()
    assert not (reports_dir / "print_merged_amazon.pdf").exists()
    assert not (reports_dir / "print_merged_rakuten.pdf").exists()
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


def test_api_steps_returns_mf_summary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(reports / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _touch(_artifact_root(tmp_path) / ym / "amazon" / "orders.jsonl")
    _touch(_artifact_root(tmp_path) / ym / "rakuten" / "orders.jsonl")
    _write_json(
        reports / "workflow.json",
        {
            "amazon": {"confirmed_at": "2026-02-08T10:00:00", "printed_at": "2026-02-08T10:10:00"},
            "rakuten": {"confirmed_at": "2026-02-08T10:20:00", "printed_at": "2026-02-08T10:30:00"},
        },
    )
    _write_json(reports / "missing_evidence_candidates.json", {"counts": {"mf_missing_evidence": 2}, "rows": []})
    _write_json(
        reports / "mf_draft_create_result.json",
        {"status": "partial_success", "data": {"targets_total": 2, "created": 1, "failed": 1}},
    )

    res = client.get("/api/steps/2026-01")
    assert res.status_code == 200
    body = res.json()
    summary = body["mf"]["summary"]
    assert summary["missing_candidates"] == 2
    assert summary["targets_total"] == 2
    assert summary["created"] == 1
    assert summary["failed"] == 1
    assert summary["status"] == "partial_success"


def test_api_steps_returns_archive_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(reports / "preflight.json", {"status": "success", "year": 2026, "month": 1})
    _write_json(
        reports / "workflow.json",
        {"amazon": {"confirmed_at": "2026-02-09T10:00:00", "printed_at": "2026-02-09T10:05:00"}},
    )
    (reports / "audit_log.jsonl").write_text(
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
                    "cleanup": False,
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    res = client.get("/api/steps/2026-01")
    assert res.status_code == 200
    body = res.json()
    assert body["archive"]["created"] is True
    assert body["archive"]["created_at"] == "2026-02-09T11:03:42"
    assert body["archive"]["archived_to"] == "C:\\archive\\20260209_110342"


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
            stdout=(
                "Archived to: C:\\archive\\20260208_101530\n"
                "Archive zip: C:\\archive\\20260208_101530\\full_snapshot.zip\n"
                "Archive manifest: C:\\archive\\20260208_101530\\manifest.json\n"
                "Archive checksums: C:\\archive\\20260208_101530\\checksums.sha256\n"
                "Cleanup report: \n"
                "Cleanup removed: 0\n"
            ),
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
    assert body["cleanup"] is False
    assert body["cleanup_report"] == ""
    assert body["cleanup_removed"] == 0
    assert body["archive_manifest"].endswith("manifest.json")
    assert body["archive_zip"].endswith("full_snapshot.zip")
    assert body["archive_checksums"].endswith("checksums.sha256")
    assert body["history_entry"]["action"] == "manual_archive"
    assert body["history_entry"]["archive_url"] == "/runs/2026-01/archived-receipts"

    assert calls
    cmd = calls[0]
    assert any("archive_outputs.ps1" in part for part in cmd)
    assert "-IncludePdfs" in cmd
    assert "-IncludeDebug" not in cmd
    assert "-NoCleanup" in cmd
    assert "-Cleanup" not in cmd

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
    assert details.get("cleanup") is False
    assert details.get("cleanup_removed") == 0
    assert str(details.get("cleanup_report") or "") == ""


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
            stdout=(
                "Archived to: C:\\archive\\20260208_101530\n"
                "Cleanup report: \n"
                "Cleanup removed: 0\n"
            ),
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


def test_api_month_close_runs_archive_with_cleanup_and_writes_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(
        reports / "workflow.json",
        {"rakuten": {"confirmed_at": "2026-02-08T10:00:00", "printed_at": "2026-02-08T10:10:00"}},
    )
    _write_json(
        reports / "month_close_checklist.json",
        {
            "ym": ym,
            "checklist": {
                "expense_submission": True,
                "document_printout": True,
                "mf_accounting_link": True,
            },
            "updated_at": "2026-02-08T09:59:59",
        },
    )
    _touch(reports / "quality_gate.json", "{}")

    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=(
                "Archived to: C:\\archive\\20260208_101530\n"
                "Cleanup report: C:\\work\\2026-01\\reports\\archive_cleanup_report.json\n"
                "Cleanup removed: 3\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(core_runs.subprocess, "run", _fake_run)

    res = client.post("/api/month-close/2026-01")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["cleanup"] is True
    assert body["cleanup_removed"] == 3
    assert body["history_entry"]["action"] == "month_close"
    assert body["history_entry"]["action_label"] == "月次クローズ"
    assert body["history_entry"]["archive_url"] == "/runs/2026-01/archived-receipts"

    assert calls
    cmd = calls[0]
    assert "-Cleanup" in cmd
    assert "-NoCleanup" not in cmd

    entries = _read_audit_entries(tmp_path, ym)
    archive_events = [e for e in entries if e.get("event_type") == "archive"]
    assert archive_events
    last = archive_events[-1]
    assert last["action"] == "month_close"
    assert last["status"] == "success"
    details = last.get("details") or {}
    assert details.get("cleanup") is True
    assert details.get("cleanup_removed") == 3


def test_api_month_close_rejects_when_checklist_is_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    reports = _reports_dir(tmp_path, ym)
    _write_json(
        reports / "workflow.json",
        {"amazon": {"confirmed_at": "2026-02-08T10:00:00", "printed_at": "2026-02-08T10:10:00"}},
    )
    _write_json(
        reports / "month_close_checklist.json",
        {
            "ym": ym,
            "checklist": {
                "expense_submission": False,
                "document_printout": True,
                "mf_accounting_link": False,
            },
            "updated_at": "2026-02-08T09:59:59",
        },
    )
    _touch(reports / "quality_gate.json", "{}")

    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core_runs.subprocess, "run", _fake_run)

    res = client.post("/api/month-close/2026-01")
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "Month close checklist is incomplete" in detail
    assert "expense_submission" in detail
    assert "mf_accounting_link" in detail
    assert not calls

    entries = _read_audit_entries(tmp_path, ym)
    archive_events = [e for e in entries if e.get("event_type") == "archive"]
    assert archive_events
    last = archive_events[-1]
    assert last["action"] == "month_close"
    assert last["status"] == "rejected"
    assert "Month close checklist is incomplete" in str((last.get("details") or {}).get("reason"))


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


def test_api_open_manual_inbox_creates_and_opens_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    shortcut_root = tmp_path / "desktop"
    monkeypatch.setenv("AX_DASHBOARD_SHORTCUT_DIR", str(shortcut_root))
    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/2026-01/manual-inbox")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["ym"] == ym
    opened = Path(str(body["path"]))
    assert opened.exists()
    assert opened.name == "inbox"
    assert opened.parent.name == "manual"
    shortcut_value = str(body.get("shortcut_path") or "")
    if sys.platform.startswith("win"):
        assert shortcut_value
        shortcut_path = Path(shortcut_value)
        assert shortcut_path.exists()
        assert shortcut_path.suffix.lower() == ".url"
        assert shortcut_path.parent == shortcut_root
    else:
        assert shortcut_value == ""

    assert calls
    entries = _read_audit_entries(tmp_path, ym)
    manual_events = [e for e in entries if e.get("event_type") == "manual" and e.get("action") == "open_inbox"]
    assert manual_events
    assert manual_events[-1].get("status") == "success"
    details = manual_events[-1].get("details") or {}
    if sys.platform.startswith("win"):
        assert str(details.get("shortcut_path") or "")


def test_api_open_manual_inbox_prefers_onedrive_desktop_for_shortcut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if not sys.platform.startswith("win"):
        pytest.skip("windows only")

    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    monkeypatch.delenv("AX_DASHBOARD_SHORTCUT_DIR", raising=False)
    onedrive_desktop = tmp_path / "onedrive" / "Desktop"
    userprofile_desktop = tmp_path / "userprofile" / "Desktop"
    onedrive_desktop.mkdir(parents=True, exist_ok=True)
    userprofile_desktop.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OneDrive", str(tmp_path / "onedrive"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "userprofile"))

    monkeypatch.setattr(
        api_routes.subprocess,
        "run",
        lambda cmd, *args, **kwargs: subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr=""),
    )

    res = client.post(f"/api/folders/{ym}/manual-inbox")
    assert res.status_code == 200
    body = res.json()
    shortcut_value = str(body.get("shortcut_path") or "")
    assert shortcut_value
    shortcut_path = Path(shortcut_value)
    assert shortcut_path.parent == onedrive_desktop


def test_api_manual_import_returns_counts_and_writes_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"

    def _fake_import(year: int, month: int) -> dict[str, Any]:
        assert (year, month) == (2026, 1)
        return {
            "status": "ok",
            "ym": ym,
            "found_pdfs": 3,
            "imported": 2,
            "imported_missing_amount": 1,
            "skipped_duplicates": 1,
            "failed": 0,
            "orders_jsonl": "C:\\tmp\\manual\\orders.jsonl",
        }

    monkeypatch.setattr(api_routes.core, "_import_manual_receipts_for_ym", _fake_import)

    res = client.post("/api/manual/2026-01/import")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["found_pdfs"] == 3
    assert body["imported"] == 2
    assert body["skipped_duplicates"] == 1

    entries = _read_audit_entries(tmp_path, ym)
    manual_events = [e for e in entries if e.get("event_type") == "manual" and e.get("action") == "import"]
    assert manual_events
    last = manual_events[-1]
    assert last.get("status") == "success"
    details = last.get("details") or {}
    assert details.get("found_pdfs") == 3
    assert details.get("imported") == 2
    assert details.get("skipped_duplicates") == 1


def test_api_manual_import_rejects_when_run_is_in_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    monkeypatch.setattr(api_routes.core, "_running_mode_for_ym", lambda y, m: "amazon_download")

    res = client.post("/api/manual/2026-01/import")
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "Another run is already in progress" in detail

    entries = _read_audit_entries(tmp_path, ym)
    manual_events = [e for e in entries if e.get("event_type") == "manual" and e.get("action") == "import"]
    assert manual_events
    assert manual_events[-1].get("status") == "rejected"


def test_api_open_mf_bulk_inbox_creates_and_opens_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    shortcut_root = tmp_path / "desktop"
    monkeypatch.setenv("AX_DASHBOARD_SHORTCUT_DIR", str(shortcut_root))
    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/2026-01/mf-bulk-inbox")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["ym"] == ym
    opened = Path(str(body["path"]))
    assert opened.exists()
    assert opened.name == "inbox"
    assert opened.parent.name == "mf_bulk_upload"
    shortcut_value = str(body.get("shortcut_path") or "")
    if sys.platform.startswith("win"):
        assert shortcut_value
        shortcut_path = Path(shortcut_value)
        assert shortcut_path.exists()
        assert shortcut_path.suffix.lower() == ".url"
        assert shortcut_path.parent == shortcut_root
    else:
        assert shortcut_value == ""

    assert calls
    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "mf_bulk_upload" and e.get("action") == "open_inbox"]
    assert events
    assert events[-1].get("status") == "success"
    details = events[-1].get("details") or {}
    if sys.platform.startswith("win"):
        assert str(details.get("shortcut_path") or "")


def test_api_mf_bulk_upload_returns_summary_and_writes_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"

    def _fake_run(year: int, month: int, **kwargs: Any) -> dict[str, Any]:
        assert (year, month) == (2026, 1)
        assert kwargs["auth_handoff"] is True
        assert kwargs["headed"] is True
        assert kwargs["transactions_url"] == api_routes.core.DEFAULT_MFCLOUD_TRANSACTIONS_URL
        return {
            "status": "ok",
            "ym": ym,
            "files_found": 4,
            "submitted_count": 3,
            "queued_count": 3,
            "read_count": 4,
            "result_json": "C:\\tmp\\mf_bulk_upload_result.json",
        }

    monkeypatch.setattr(api_routes.core, "_run_mf_bulk_upload_for_ym", _fake_run)

    res = client.post("/api/mf-bulk-upload/2026-01")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["files_found"] == 4
    assert body["submitted_count"] == 3
    assert body["queued_count"] == 3
    assert body["read_count"] == 4

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "mf_bulk_upload" and e.get("action") == "run"]
    assert events
    last = events[-1]
    assert last.get("status") == "success"
    details = last.get("details") or {}
    assert details.get("files_found") == 4
    assert details.get("submitted_count") == 3
    assert details.get("queued_count") == 3
    assert details.get("read_count") == 4


def test_api_mf_bulk_upload_rejects_when_run_is_in_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    monkeypatch.setattr(api_routes.core, "_running_mode_for_ym", lambda y, m: "preflight")

    res = client.post("/api/mf-bulk-upload/2026-01")
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "Another run is already in progress" in detail

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "mf_bulk_upload" and e.get("action") == "run"]
    assert events
    assert events[-1].get("status") == "rejected"


def test_api_open_mf_csv_inbox_creates_and_opens_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    shortcut_root = tmp_path / "desktop"
    monkeypatch.setenv("AX_DASHBOARD_SHORTCUT_DIR", str(shortcut_root))
    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/2026-01/mf-csv-inbox")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["ym"] == ym
    opened = Path(str(body["path"]))
    assert opened.exists()
    assert opened.name == "inbox"
    assert opened.parent.name == "mf_csv_import"
    shortcut_value = str(body.get("shortcut_path") or "")
    if sys.platform.startswith("win"):
        assert shortcut_value
        shortcut_path = Path(shortcut_value)
        assert shortcut_path.exists()
        assert shortcut_path.suffix.lower() == ".url"
        assert shortcut_path.parent == shortcut_root
    else:
        assert shortcut_value == ""

    assert calls
    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "mf_csv_import" and e.get("action") == "open_inbox"]
    assert events
    assert events[-1].get("status") == "success"
    details = events[-1].get("details") or {}
    if sys.platform.startswith("win"):
        assert str(details.get("shortcut_path") or "")


def test_api_mf_csv_import_returns_summary_and_writes_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"

    def _fake_run(year: int, month: int, **kwargs: Any) -> dict[str, Any]:
        assert (year, month) == (2026, 1)
        assert kwargs["auth_handoff"] is True
        assert kwargs["headed"] is True
        assert kwargs["import_url"] == api_routes.core.DEFAULT_MFCLOUD_TRANSACTIONS_IMPORT_URL
        return {
            "status": "ok",
            "ym": ym,
            "files_found": 5,
            "submitted_count": 4,
            "queued_count": 4,
            "result_json": "C:\\tmp\\mf_csv_import_result.json",
        }

    monkeypatch.setattr(api_routes.core, "_run_mf_csv_import_for_ym", _fake_run)

    res = client.post("/api/mf-csv-import/2026-01")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["files_found"] == 5
    assert body["submitted_count"] == 4
    assert body["queued_count"] == 4

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "mf_csv_import" and e.get("action") == "run"]
    assert events
    last = events[-1]
    assert last.get("status") == "success"
    details = last.get("details") or {}
    assert details.get("files_found") == 5
    assert details.get("submitted_count") == 4
    assert details.get("queued_count") == 4


def test_api_mf_csv_import_rejects_when_run_is_in_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    monkeypatch.setattr(api_routes.core, "_running_mode_for_ym", lambda y, m: "preflight")

    res = client.post("/api/mf-csv-import/2026-01")
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "Another run is already in progress" in detail

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "mf_csv_import" and e.get("action") == "run"]
    assert events
    assert events[-1].get("status") == "rejected"


def test_api_open_provider_inbox_creates_and_opens_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/2026-01/provider-inbox/chatgpt")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["ym"] == ym
    assert body["provider"] == "chatgpt"
    opened = Path(str(body["path"]))
    assert opened.exists()
    assert opened.name == "chatgpt"
    assert opened.parent.name == "inbox"

    assert calls
    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "provider_ingest" and e.get("action") == "open_inbox"]
    assert events
    assert events[-1].get("status") == "success"


def test_api_open_provider_source_opens_configured_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    source_dir = _artifact_root(tmp_path) / "gaspdf"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "sample.txt").write_text("placeholder", encoding="utf-8")
    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes, "_provider_source_status_for_ym", lambda year, month: {
        "path": str(source_dir),
        "configured": True,
        "exists": True,
        "pending_files": 3,
    })
    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/2026-01/provider-source")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["ym"] == ym
    assert body["path"] == str(source_dir)
    source_status = body["source_status"]
    assert source_status["configured"] is True
    assert source_status["exists"] is True
    assert source_status["pending_files"] == 3
    assert calls

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "provider_ingest" and e.get("action") == "open_source"]
    assert events
    assert events[-1].get("status") == "success"


def test_api_open_provider_source_rejects_when_not_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    calls: list[list[str]] = []

    monkeypatch.setattr(api_routes, "_provider_source_status_for_ym", lambda year, month: {
        "path": "",
        "configured": False,
        "exists": False,
        "pending_files": 0,
    })

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)
    res = client.post("/api/folders/2026-01/provider-source")
    assert res.status_code == 409
    assert "not configured" in str(res.json().get("detail") or "").lower()
    assert not calls

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "provider_ingest" and e.get("action") == "open_source"]
    assert events
    assert events[-1].get("status") == "rejected"


def test_api_open_provider_source_rejects_when_folder_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    source_dir = _artifact_root(tmp_path) / "gaspdf_missing"
    calls: list[list[str]] = []

    monkeypatch.setattr(api_routes, "_provider_source_status_for_ym", lambda year, month: {
        "path": str(source_dir),
        "configured": True,
        "exists": False,
        "pending_files": 0,
    })

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)
    res = client.post("/api/folders/2026-01/provider-source")
    assert res.status_code == 409
    assert "does not exist" in str(res.json().get("detail") or "").lower()
    assert not calls

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "provider_ingest" and e.get("action") == "open_source"]
    assert events
    assert events[-1].get("status") == "rejected"


def test_api_open_provider_skipped_latest_creates_and_opens_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    skipped_dir = _artifact_root(tmp_path) / ym / "manual" / "inbox" / "_skipped" / "20260212_104250"
    skipped_file = skipped_dir / "20260212.pdf"
    _touch(skipped_file, "%PDF-1.4\n")
    _write_json(
        _artifact_root(tmp_path) / ym / "manual" / "reports" / "provider_import_last.json",
        {"skipped_rows": [{"file": "20260212.pdf", "moved_to": str(skipped_file)}]},
    )

    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/folders/2026-01/provider-skipped/latest")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["ym"] == ym
    assert body["path"] == str(skipped_dir)

    assert calls
    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "provider_ingest" and e.get("action") == "open_skipped"]
    assert events
    assert events[-1].get("status") == "success"


def test_api_provider_import_returns_counts_and_writes_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"

    def _fake_import(year: int, month: int) -> dict[str, Any]:
        assert (year, month) == (2026, 1)
        return {
            "status": "ok",
            "ym": ym,
            "found_files": 5,
            "imported": 4,
            "imported_missing_amount": 1,
            "skipped_duplicates": 0,
            "failed": 0,
            "providers": {
                "chatgpt": {"found": 2, "imported": 2, "imported_missing_amount": 0, "skipped_duplicates": 0, "failed": 0}
            },
            "orders_jsonl": "C:\\tmp\\manual\\orders.jsonl",
            "provider_report_json": "C:\\tmp\\manual\\reports\\provider_import_last.json",
        }

    monkeypatch.setattr(api_routes.core, "_import_provider_receipts_for_ym", _fake_import)

    res = client.post("/api/providers/2026-01/import")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["found_files"] == 5
    assert body["imported"] == 4
    assert body["skipped_duplicates"] == 0
    assert body["providers"]["chatgpt"]["imported"] == 2
    assert body["manual_action_required"] is False

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "provider_ingest" and e.get("action") == "import"]
    assert events
    last = events[-1]
    assert last.get("status") == "success"
    details = last.get("details") or {}
    assert details.get("found_files") == 5
    assert details.get("imported") == 4


def test_api_provider_import_marks_warning_when_skipped_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"

    def _fake_import(year: int, month: int) -> dict[str, Any]:
        assert (year, month) == (2026, 1)
        return {
            "status": "ok",
            "ym": ym,
            "found_files": 3,
            "imported": 0,
            "imported_missing_amount": 0,
            "skipped_duplicates": 3,
            "failed": 0,
            "providers": {},
            "orders_jsonl": "C:\\tmp\\manual\\orders.jsonl",
            "provider_report_json": "C:\\tmp\\manual\\reports\\provider_import_last.json",
            "manual_action_required": True,
            "manual_action_reason": "skipped",
            "skipped_dir": "C:\\tmp\\manual\\inbox\\_skipped\\20260212_104250",
            "skipped_files": ["20260212.pdf", "20260212_001.pdf", "20260212_002.pdf"],
        }

    monkeypatch.setattr(api_routes.core, "_import_provider_receipts_for_ym", _fake_import)

    res = client.post("/api/providers/2026-01/import")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["manual_action_required"] is True
    assert body["manual_action_reason"] == "skipped"
    assert body["skipped_dir"] == "C:\\tmp\\manual\\inbox\\_skipped\\20260212_104250"
    assert body["skipped_files"] == ["20260212.pdf", "20260212_001.pdf", "20260212_002.pdf"]

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "provider_ingest" and e.get("action") == "import"]
    assert events
    last = events[-1]
    assert last.get("status") == "warning"
    details = last.get("details") or {}
    assert details.get("manual_action_required") is True
    assert details.get("manual_action_reason") == "skipped"


def test_api_provider_print_run_merges_pdf_and_opens_manual_print(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    pdf_a = _artifact_root(tmp_path) / ym / "manual" / "pdfs" / "provider-a.pdf"
    pdf_b = _artifact_root(tmp_path) / ym / "manual" / "pdfs" / "provider-b.pdf"
    _touch_pdf(pdf_a)
    _touch_pdf(pdf_b)

    calls: list[list[str]] = []

    def _fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_routes.subprocess, "run", _fake_run)

    res = client.post("/api/providers/2026-01/print-run")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["ym"] == ym
    assert body["print_mode"] == "manual_open"
    assert body["count"] == 2
    merged_pdf = Path(str(body["merged_pdf_path"]))
    assert merged_pdf.exists()
    assert merged_pdf.name == "print_merged_provider.pdf"

    assert calls
    assert any("print_merged_provider.pdf" in part for part in calls[0])

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "provider_ingest" and e.get("action") == "print_run"]
    assert events
    last = events[-1]
    assert last.get("status") == "success"
    details = last.get("details") or {}
    assert details.get("mode") == "manual_open"
    assert details.get("count") == 2
    assert str(details.get("merged_pdf_path") or "").endswith("print_merged_provider.pdf")


def test_api_provider_print_run_rejects_when_no_pdf_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"

    res = client.post("/api/providers/2026-01/print-run")
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "No provider PDF files were found" in detail

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "provider_ingest" and e.get("action") == "print_run"]
    assert events
    last = events[-1]
    assert last.get("status") == "rejected"


def test_api_provider_download_rejected_as_manual_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"

    res = client.post("/api/providers/2026-01/download")
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "Provider auto-download is disabled" in detail

    entries = _read_audit_entries(tmp_path, ym)
    events = [e for e in entries if e.get("event_type") == "provider_ingest" and e.get("action") == "download"]
    assert events
    last = events[-1]
    assert last.get("status") == "rejected"
    details = last.get("details") or {}
    assert details.get("mode") == "manual_only"


def test_api_month_close_checklist_get_returns_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)

    res = client.get("/api/month-close-checklist/2026-01")
    assert res.status_code == 200
    body = res.json()
    assert body["ym"] == "2026-01"
    assert body["updated_at"] is None
    assert body["checklist"] == {
        "expense_submission": False,
        "document_printout": False,
        "mf_accounting_link": False,
    }


def test_api_month_close_checklist_post_persists_state_and_writes_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    checklist = {
        "expense_submission": True,
        "document_printout": False,
        "mf_accounting_link": True,
    }

    post_res = client.post(f"/api/month-close-checklist/{ym}", json={"checklist": checklist})
    assert post_res.status_code == 200
    post_body = post_res.json()
    assert post_body["status"] == "ok"
    assert post_body["checklist"] == checklist

    get_res = client.get(f"/api/month-close-checklist/{ym}")
    assert get_res.status_code == 200
    get_body = get_res.json()
    assert get_body["ym"] == ym
    assert get_body["checklist"] == checklist
    assert isinstance(get_body["updated_at"], str)
    assert get_body["updated_at"]

    entries = _read_audit_entries(tmp_path, ym)
    checklist_events = [e for e in entries if e.get("event_type") == "month_close_checklist"]
    assert checklist_events
    last = checklist_events[-1]
    assert last["action"] == "update"
    assert last["status"] == "success"
    assert (last.get("details") or {}).get("checklist") == checklist


def test_api_month_close_checklist_post_rejects_invalid_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)

    missing_key = {
        "expense_submission": True,
        "document_printout": True,
    }
    res_missing = client.post("/api/month-close-checklist/2026-01", json={"checklist": missing_key})
    assert res_missing.status_code == 400
    assert "required keys and no unknown keys" in str(res_missing.json().get("detail") or "")

    non_bool = {
        "expense_submission": "yes",
        "document_printout": True,
        "mf_accounting_link": True,
    }
    res_non_bool = client.post("/api/month-close-checklist/2026-01", json={"checklist": non_bool})
    assert res_non_bool.status_code == 400
    assert "checklist.expense_submission must be a boolean" in str(res_non_bool.json().get("detail") or "")


def test_api_month_close_checklist_post_accepts_legacy_optional_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    checklist = {
        "transportation_expense": False,  # legacy key (ignored)
        "expense_submission": True,
        "document_printout": True,
        "mf_accounting_link": True,
    }

    res = client.post(f"/api/month-close-checklist/{ym}", json={"checklist": checklist})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["checklist"] == {
        "expense_submission": True,
        "document_printout": True,
        "mf_accounting_link": True,
    }


def test_api_workspace_state_get_returns_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)

    res = client.get("/api/workspace/state")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["links"] == []
    assert body["prompts"] == {}
    assert body["link_notes"] == {}
    assert body["active_prompt_key"] == "mf_expense_reports"
    assert body["revision"] == 0
    assert body["updated_at"] is None


def test_api_workspace_state_post_persists_and_sanitizes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)

    res = client.post(
        "/api/workspace/state",
        json={
            "links": [
                {"label": " MF 経費  ", "url": "https://expense.moneyforward.com/expense_reports"},
                {"label": "duplicate", "url": "https://expense.moneyforward.com/expense_reports"},
                {"label": "invalid", "url": "ftp://example.com/a"},
            ],
            "prompts": {
                "mf_expense_reports": "core prompt",
                "custom:https%3A%2F%2Fexample.com": "custom prompt",
                "invalid": "should be ignored",
            },
            "link_notes": {
                "mf_expense_reports": "core note",
                "custom:https%3A%2F%2Fexample.com": "custom note",
                "invalid": "ignored note",
            },
            "active_prompt_key": "invalid",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["links"] == [{"label": "MF 経費", "url": "https://expense.moneyforward.com/expense_reports"}]
    assert body["prompts"] == {
        "mf_expense_reports": "core prompt",
        "custom:https%3A%2F%2Fexample.com": "custom prompt",
    }
    assert body["link_notes"] == {
        "mf_expense_reports": "core note",
        "custom:https%3A%2F%2Fexample.com": "custom note",
    }
    assert body["active_prompt_key"] == "mf_expense_reports"
    assert body["revision"] == 1
    assert body["conflict_resolved"] is False
    assert isinstance(body["updated_at"], str)
    assert body["updated_at"]

    state_path = _artifact_root(tmp_path) / "_workspace" / "workspace_state.json"
    assert state_path.exists()
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["links"] == body["links"]
    assert persisted["prompts"] == body["prompts"]
    assert persisted["link_notes"] == body["link_notes"]
    assert persisted["active_prompt_key"] == body["active_prompt_key"]
    assert persisted["revision"] == body["revision"]

    res_partial = client.post(
        "/api/workspace/state",
        json={"active_prompt_key": "custom:https%3A%2F%2Fexample.com", "base_revision": body["revision"]},
    )
    assert res_partial.status_code == 200
    body_partial = res_partial.json()
    assert body_partial["links"] == body["links"]
    assert body_partial["prompts"] == body["prompts"]
    assert body_partial["link_notes"] == body["link_notes"]
    assert body_partial["active_prompt_key"] == "custom:https%3A%2F%2Fexample.com"
    assert body_partial["revision"] == body["revision"] + 1
    assert body_partial["conflict_resolved"] is False


def test_api_workspace_state_post_merges_on_revision_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)

    first = client.post(
        "/api/workspace/state",
        json={
            "links": [{"label": "A", "url": "https://a.example.com/"}],
            "prompts": {"mf_expense_reports": "first"},
            "link_notes": {"mf_expense_reports": "first_note"},
            "active_prompt_key": "mf_expense_reports",
        },
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["revision"] == 1
    assert first_body["conflict_resolved"] is False

    second = client.post(
        "/api/workspace/state",
        json={
            "base_revision": first_body["revision"],
            "links": [{"label": "B", "url": "https://b.example.com/"}],
            "prompts": {"custom:https%3A%2F%2Fb.example.com%2F": "second"},
            "link_notes": {"custom:https%3A%2F%2Fb.example.com%2F": "second_note"},
            "active_prompt_key": "custom:https%3A%2F%2Fb.example.com%2F",
        },
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["revision"] == 2
    assert second_body["conflict_resolved"] is False

    # stale update with base_revision=1 should be merged with latest revision=2
    third = client.post(
        "/api/workspace/state",
        json={
            "base_revision": first_body["revision"],
            "links": [{"label": "A2", "url": "https://a.example.com/"}],
            "prompts": {"mf_expense_reports": "third"},
            "link_notes": {"mf_expense_reports": "third_note"},
            "active_prompt_key": "mf_expense_reports",
        },
    )
    assert third.status_code == 200
    third_body = third.json()
    assert third_body["revision"] == 3
    assert third_body["conflict_resolved"] is True
    assert third_body["active_prompt_key"] == "mf_expense_reports"
    assert third_body["prompts"]["mf_expense_reports"] == "third"
    assert third_body["prompts"]["custom:https%3A%2F%2Fb.example.com%2F"] == "second"
    assert third_body["link_notes"]["mf_expense_reports"] == "third_note"
    assert third_body["link_notes"]["custom:https%3A%2F%2Fb.example.com%2F"] == "second_note"
    urls = [row.get("url") for row in third_body["links"]]
    assert "https://a.example.com/" in urls
    assert "https://b.example.com/" in urls


def test_api_scheduler_state_get_returns_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.get("/api/scheduler/state")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["enabled"] is False
    assert body["mode"] == "preflight"
    assert body["recurrence"] == "once"
    assert body["run_time"] == "09:00"
    assert body["catch_up_policy"] == "run_on_startup"
    assert body["next_run_at"] is None


def test_api_scheduler_state_post_persists_and_toggles_autostart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    startup_dir = tmp_path / "startup"
    monkeypatch.setenv("AX_DASHBOARD_STARTUP_DIR", str(startup_dir))
    monkeypatch.setattr(core_scheduler, "_autostart_supported", lambda: True)

    post_res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": False,
            "mode": "preflight_mf",
            "year": 2026,
            "month": 1,
            "run_date": "2026-03-01",
            "run_time": "08:30",
            "catch_up_policy": "run_on_startup",
            "recurrence": "daily",
            "auth_handoff": False,
            "auto_start_enabled": True,
        },
    )
    assert post_res.status_code == 200
    body = post_res.json()
    assert body["status"] == "ok"
    assert body["mode"] == "preflight_mf"
    assert body["year"] == 2026
    assert body["month"] == 1
    assert body["run_date"] == "2026-03-01"
    assert body["run_time"] == "08:30"
    assert body["recurrence"] == "daily"
    assert body["auto_start_enabled"] is True
    assert body["auto_start_active"] is True

    autostart_path = Path(str(body["autostart_path"]))
    assert autostart_path.exists()

    state_path = _artifact_root(tmp_path) / "_scheduler" / "scheduler_state.json"
    assert state_path.exists()
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["mode"] == "preflight_mf"
    assert persisted["run_date"] == "2026-03-01"
    assert persisted["run_time"] == "08:30"
    assert persisted["recurrence"] == "daily"
    assert persisted["auto_start_enabled"] is True

    off_res = client.post("/api/scheduler/state", json={"enabled": False, "auto_start_enabled": False})
    assert off_res.status_code == 200
    assert off_res.json()["auto_start_enabled"] is False
    assert off_res.json()["auto_start_active"] is False
    assert not autostart_path.exists()


def test_api_scheduler_state_post_rejects_enable_without_schedule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": True,
            "mode": "preflight",
            "year": 2026,
            "month": 1,
            "run_date": "",
            "run_time": "09:00",
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "run_date" in detail


def test_api_scheduler_state_daily_recurrence_advances_run_date(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, object]] = []

    def fake_start_run(payload: dict[str, object]) -> dict[str, str]:
        run_payloads.append(payload)
        return {"run_id": "run_20260210_000001"}

    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", fake_start_run)

    now = datetime.now()
    run_time = (now - timedelta(minutes=1)).strftime("%H:%M")
    run_date = now.strftime("%Y-%m-%d")

    post_res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": True,
            "mode": "preflight",
            "year": now.year,
            "month": now.month,
            "run_date": run_date,
            "run_time": run_time,
            "recurrence": "daily",
            "catch_up_policy": "run_on_startup",
            "auth_handoff": False,
        },
    )
    assert post_res.status_code == 200
    body = post_res.json()
    assert body["status"] == "ok"
    assert body["recurrence"] == "daily"
    assert body["enabled"] is True
    assert body["last_result"]["status"] == "started"
    assert run_payloads
    assert run_payloads[0]["year"] == now.year
    assert run_payloads[0]["month"] == now.month

    expected_next = now + timedelta(days=1)
    assert body["run_date"] == expected_next.strftime("%Y-%m-%d")
    assert body["run_time"] == run_time
    assert body["year"] == expected_next.year
    assert body["month"] == expected_next.month

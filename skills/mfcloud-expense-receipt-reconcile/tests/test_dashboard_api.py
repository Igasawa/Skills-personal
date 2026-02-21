from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfWriter
import pytest

from dashboard.routes import api as api_routes
from dashboard.routes import api_workspace_routes
from dashboard.services import ai_chat
from dashboard.services import core_runs
from services import core as public_core
from services import core_scheduler as public_core_scheduler


def _artifact_root(ax_home: Path) -> Path:
    return ax_home / "artifacts" / "mfcloud-expense-receipt-reconcile"


def _reports_dir(ax_home: Path, ym: str) -> Path:
    return _artifact_root(ax_home) / ym / "reports"


def _workflow_template_store(ax_home: Path) -> Path:
    return _artifact_root(ax_home) / "_workflow_templates" / "workflow_templates.json"


def _workflow_pages_store(ax_home: Path) -> Path:
    return _artifact_root(ax_home) / "_workflow_pages" / "workflow_pages.json"


def _workflow_event_retry_jobs_store(ax_home: Path) -> Path:
    return _artifact_root(ax_home) / "_workflow_events" / "retry_jobs.json"


def _workflow_event_notification_settings_store(ax_home: Path) -> Path:
    return _artifact_root(ax_home) / "_workflow_events" / "notification_settings.json"


def _write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
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


def _read_workflow_event_retry_jobs(ax_home: Path) -> dict[str, Any]:
    path = _workflow_event_retry_jobs_store(ax_home)
    if not path.exists():
        return {"jobs": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"jobs": {}}


def _read_workflow_event_notification_settings(ax_home: Path) -> dict[str, Any]:
    path = _workflow_event_notification_settings_store(ax_home)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _create_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(api_routes.create_api_router())
    return TestClient(app)


def _set_ai_chat_env(monkeypatch: pytest.MonkeyPatch, *, api_key: str | None, model: str = "gemini-2.0-flash") -> None:
    monkeypatch.setattr(ai_chat, "_SECRET_ENV_LOADED", True)
    monkeypatch.setattr(api_workspace_routes.ai_chat, "_SECRET_ENV_LOADED", True)
    if api_key:
        monkeypatch.setenv("GEMINI_API_KEY", api_key)
    else:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("KIL_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("KIL_GEMINI_MODEL", model)
    monkeypatch.delenv("KIL_AI_GUARDRAIL_MODE", raising=False)


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
    assert body["pinned_links"] == []
    assert body["pinned_link_groups"] == []
    assert body["prompts"] == {}
    assert body["link_notes"] == {}
    assert body["link_profiles"] == {}
    assert body["active_prompt_key"] == "mf_expense_reports"
    assert body["revision"] == 0
    assert body["updated_at"] is None


def test_api_workspace_state_post_persists_and_sanitizes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)

    res = client.post(
        "/api/workspace/state",
        json={
            "links": [
                {"label": " MF 邨瑚ｲｻ  ", "url": "https://expense.moneyforward.com/expense_reports"},
                {"label": "duplicate", "url": "https://expense.moneyforward.com/expense_reports"},
                {"label": "invalid", "url": "ftp://example.com/a"},
            ],
            "pinned_links": [
                {"label": " Pinned Ops ", "url": "https://ops.example.com/"},
                {"label": "duplicate", "url": "https://ops.example.com/"},
                {"label": "invalid", "url": "ftp://example.com/pinned"},
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
            "link_profiles": {
                "mf_expense_reports": {
                    "owner": " 邨檎炊 逕ｰ荳ｭ ",
                    "agent": "codex",
                    "reviewed_on": "2026-02-18",
                },
                "custom:https%3A%2F%2Fexample.com": {
                    "owner": "B Team",
                    "agent": "unsupported-agent",
                    "reviewed_on": "2026-99-99",
                },
                "invalid": {"owner": "ignored"},
            },
            "active_prompt_key": "invalid",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["links"] == [{"label": "MF 邨瑚ｲｻ", "url": "https://expense.moneyforward.com/expense_reports"}]
    assert body["pinned_links"] == [{"label": "Pinned Ops", "url": "https://ops.example.com/"}]
    pinned_group = body["pinned_link_groups"][0]
    assert pinned_group["id"]
    assert pinned_group["label"] == "固定リンク1"
    assert pinned_group["links"] == [{"label": "Pinned Ops", "url": "https://ops.example.com/"}]
    assert pinned_group["created_at"] == ""
    assert body["prompts"] == {
        "mf_expense_reports": "core prompt",
        "custom:https%3A%2F%2Fexample.com": "custom prompt",
    }
    assert body["link_notes"] == {
        "mf_expense_reports": "core note",
        "custom:https%3A%2F%2Fexample.com": "custom note",
    }
    assert body["link_profiles"] == {
        "mf_expense_reports": {"owner": "邨檎炊 逕ｰ荳ｭ", "agent": "codex", "reviewed_on": "2026-02-18"},
        "custom:https%3A%2F%2Fexample.com": {"owner": "B Team", "agent": "", "reviewed_on": ""},
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
    assert persisted["pinned_links"] == body["pinned_links"]
    assert persisted["pinned_link_groups"] == body["pinned_link_groups"]
    assert persisted["prompts"] == body["prompts"]
    assert persisted["link_notes"] == body["link_notes"]
    assert persisted["link_profiles"] == body["link_profiles"]
    assert persisted["active_prompt_key"] == body["active_prompt_key"]
    assert persisted["revision"] == body["revision"]

    res_partial = client.post(
        "/api/workspace/state",
        json={"active_prompt_key": "custom:https%3A%2F%2Fexample.com", "base_revision": body["revision"]},
    )
    assert res_partial.status_code == 200
    body_partial = res_partial.json()
    assert body_partial["links"] == body["links"]
    assert body_partial["pinned_links"] == body["pinned_links"]
    assert body_partial["pinned_link_groups"] == body["pinned_link_groups"]
    assert body_partial["prompts"] == body["prompts"]
    assert body_partial["link_notes"] == body["link_notes"]
    assert body_partial["link_profiles"] == body["link_profiles"]
    assert body_partial["active_prompt_key"] == "custom:https%3A%2F%2Fexample.com"
    assert body_partial["revision"] == body["revision"] + 1
    assert body_partial["conflict_resolved"] is False


def test_api_workspace_state_post_legacy_pinned_links_keeps_existing_groups(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)

    initial = client.post(
        "/api/workspace/state",
        json={
            "pinned_link_groups": [
                {
                    "id": "group-a",
                    "label": "Pinned Card A",
                    "links": [{"label": "Pinned A", "url": "https://pinned-a.example.com/"}],
                },
                {
                    "id": "group-b",
                    "label": "Pinned Card B",
                    "links": [{"label": "Pinned B", "url": "https://pinned-b.example.com/"}],
                },
            ],
            "links": [],
        },
    )
    assert initial.status_code == 200
    initial_body = initial.json()
    assert initial_body["revision"] == 1
    assert len(initial_body["pinned_link_groups"]) == 2
    assert initial_body["pinned_link_groups"][0]["id"] == "group-a"
    assert initial_body["pinned_link_groups"][1]["id"] == "group-b"

    updated = client.post(
        "/api/workspace/state",
        json={
            "base_revision": initial_body["revision"],
            "pinned_links": [{"label": "Pinned C", "url": "https://pinned-c.example.com/"}],
            "links": [],
        },
    )
    assert updated.status_code == 200
    updated_body = updated.json()
    assert updated_body["revision"] == 2
    assert updated_body["conflict_resolved"] is False
    assert len(updated_body["pinned_link_groups"]) == 2
    assert updated_body["pinned_link_groups"][0]["links"] == [{"label": "Pinned C", "url": "https://pinned-c.example.com/"}]
    assert updated_body["pinned_link_groups"][1]["links"] == [{"label": "Pinned B", "url": "https://pinned-b.example.com/"}]

    cleared = client.post(
        "/api/workspace/state",
        json={
            "base_revision": updated_body["revision"],
            "pinned_links": [],
            "links": [],
        },
    )
    assert cleared.status_code == 200
    cleared_body = cleared.json()
    assert cleared_body["revision"] == 3
    assert cleared_body["conflict_resolved"] is False
    assert cleared_body["pinned_link_groups"][0]["links"] == []
    assert cleared_body["pinned_link_groups"][1]["links"] == [{"label": "Pinned B", "url": "https://pinned-b.example.com/"}]


def test_api_workspace_state_post_merges_on_revision_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)

    first = client.post(
        "/api/workspace/state",
        json={
            "links": [{"label": "A", "url": "https://a.example.com/"}],
            "pinned_links": [{"label": "Pinned A", "url": "https://pinned-a.example.com/"}],
            "prompts": {"mf_expense_reports": "first"},
            "link_notes": {"mf_expense_reports": "first_note"},
            "link_profiles": {
                "mf_expense_reports": {"owner": "A team", "agent": "codex", "reviewed_on": "2026-02-10"}
            },
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
            "pinned_links": [{"label": "Pinned B", "url": "https://pinned-b.example.com/"}],
            "prompts": {"custom:https%3A%2F%2Fb.example.com%2F": "second"},
            "link_notes": {"custom:https%3A%2F%2Fb.example.com%2F": "second_note"},
            "link_profiles": {
                "custom:https%3A%2F%2Fb.example.com%2F": {
                    "owner": "B team",
                    "agent": "chatgpt",
                    "reviewed_on": "2026-02-11",
                }
            },
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
            "pinned_links": [{"label": "Pinned C", "url": "https://pinned-c.example.com/"}],
            "prompts": {"mf_expense_reports": "third"},
            "link_notes": {"mf_expense_reports": "third_note"},
            "link_profiles": {
                "mf_expense_reports": {"owner": "A2 team", "agent": "claude", "reviewed_on": "2026-02-12"}
            },
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
    assert third_body["link_profiles"]["mf_expense_reports"] == {
        "owner": "A2 team",
        "agent": "claude",
        "reviewed_on": "2026-02-12",
    }
    assert third_body["link_profiles"]["custom:https%3A%2F%2Fb.example.com%2F"] == {
        "owner": "B team",
        "agent": "chatgpt",
        "reviewed_on": "2026-02-11",
    }
    urls = [row.get("url") for row in third_body["links"]]
    assert "https://a.example.com/" in urls
    assert "https://b.example.com/" in urls
    pinned_urls = [row.get("url") for row in third_body["pinned_links"]]
    assert "https://pinned-c.example.com/" in pinned_urls
    assert "https://pinned-b.example.com/" in pinned_urls


def test_api_workspace_prompt_optimize_returns_goal_first_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_ai_chat_env(monkeypatch, api_key="test-key")
    captured_messages: list[dict[str, str]] = []
    captured_context: dict[str, str] = {}
    captured_policy: dict[str, str] = {}

    def _fake_chat(
        *,
        messages: list[dict[str, str]],
        page_context: dict[str, str],
        policy_profile: str = "",
    ) -> dict[str, Any]:
        captured_messages.extend(messages)
        captured_context.update(page_context)
        captured_policy["value"] = policy_profile
        return {
            "provider": "gemini",
            "model": "gemini-2.0-flash",
            "reply": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "optimizedPrompt": "目的:\n- 月次処理を完遂する\n\n手順:\n1. 未処理を洗い出す\n2. 完了条件を確認する",
                        "changes": ["目的を明確化", "手順を具体化"],
                        "assumptions": ["対象月が指定済み"],
                        "risks": [],
                        "needsConfirmation": [],
                    },
                    ensure_ascii=False,
                ),
            },
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }

    monkeypatch.setattr(api_workspace_routes.ai_chat, "chat", _fake_chat)

    res = client.post(
        "/api/workspace/prompt/optimize",
        json={
            "text": "目的: 月次の未処理をなくす\n\n対象月:\n- {month}",
            "locale": "ja-JP",
            "stylePreset": "goal-first",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["changed"] is True
    assert body["goal"] == "月次の未処理をなくす"
    assert body["goalMeta"]["source"] == "inline_label"
    assert body["provider"] == "gemini"
    assert body["model"] == "gemini-2.0-flash"
    assert "optimizedPrompt" in body and body["optimizedPrompt"]
    assert body["changes"] == ["目的を明確化", "手順を具体化"]
    assert captured_context["path"] == "/workspace"
    assert captured_context["feature"] == "workspace_prompt_optimize"
    assert captured_messages and captured_messages[-1]["role"] == "user"
    assert captured_policy["value"] == ai_chat.POLICY_PROFILE_STRUCTURED_JSON
    assert "goal: 月次の未処理をなくす" in captured_messages[-1]["content"]


def test_api_workspace_prompt_optimize_adds_token_integrity_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_ai_chat_env(monkeypatch, api_key="test-key")

    def _fake_chat(
        *,
        messages: list[dict[str, str]],
        page_context: dict[str, str],
        policy_profile: str = "",
    ) -> dict[str, Any]:
        del messages, page_context, policy_profile
        return {
            "provider": "gemini",
            "model": "gemini-2.0-flash",
            "reply": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "optimizedPrompt": "目的:\n- 月次処理を完了する",
                        "changes": ["簡潔化"],
                        "assumptions": [],
                        "risks": [],
                        "needsConfirmation": [],
                    },
                    ensure_ascii=False,
                ),
            },
            "usage": {"prompt_tokens": 8, "completion_tokens": 8, "total_tokens": 16},
        }

    monkeypatch.setattr(api_workspace_routes.ai_chat, "chat", _fake_chat)

    res = client.post(
        "/api/workspace/prompt/optimize",
        json={"text": "目的:\n- 月次処理を完了する\n\n対象月:\n- {month}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["needsConfirmation"]
    assert any("保護トークン" in str(row) for row in body["needsConfirmation"])


def test_api_workspace_prompt_optimize_fallbacks_on_invalid_ai_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_ai_chat_env(monkeypatch, api_key="test-key")

    def _fake_chat(
        *,
        messages: list[dict[str, str]],
        page_context: dict[str, str],
        policy_profile: str = "",
    ) -> dict[str, Any]:
        del messages, page_context, policy_profile
        return {
            "provider": "gemini",
            "model": "gemini-2.0-flash",
            "reply": {"role": "assistant", "content": "not-json-response"},
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(api_workspace_routes.ai_chat, "chat", _fake_chat)

    res = client.post(
        "/api/workspace/prompt/optimize",
        json={"text": "目的: テスト"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert str(body.get("optimizedPrompt") or "").strip()
    needs = body.get("needsConfirmation") if isinstance(body.get("needsConfirmation"), list) else []
    assert needs
def test_api_workspace_prompt_optimize_rejects_empty_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_ai_chat_env(monkeypatch, api_key="test-key")
    res = client.post("/api/workspace/prompt/optimize", json={"text": ""})
    assert res.status_code == 400
    assert "must not be empty" in str(res.json().get("detail") or "")


def test_api_workspace_prompt_optimize_enforces_skill_first_for_kintone_portal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_ai_chat_env(monkeypatch, api_key="test-key")

    def _fake_chat(
        *,
        messages: list[dict[str, str]],
        page_context: dict[str, str],
        policy_profile: str = "",
    ) -> dict[str, Any]:
        del messages, page_context, policy_profile
        return {
            "provider": "gemini",
            "model": "gemini-2.0-flash",
            "reply": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "optimizedPrompt": "Kintone page summary",
                        "changes": ["simplify"],
                        "assumptions": [],
                        "risks": [],
                        "needsConfirmation": [],
                    },
                    ensure_ascii=False,
                ),
            },
            "usage": {"prompt_tokens": 8, "completion_tokens": 8, "total_tokens": 16},
        }

    monkeypatch.setattr(api_workspace_routes.ai_chat, "chat", _fake_chat)

    res = client.post(
        "/api/workspace/prompt/optimize",
        json={
            "text": "Kintoneのトップページ（https://5atx9.cybozu.com/k/#/portal）を解析して通知・未処理・更新を報告して",
            "locale": "ja-JP",
            "stylePreset": "goal-first",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    optimized = str(body.get("optimizedPrompt") or "")
    assert "skill id playwright" in optimized
    assert "--session kintone_audit" in optimized
    assert "snapshot" in optimized
    assert "日本語" in optimized
    assert "報告形式:" in optimized
    assert "現状:" in optimized
    assert "次アクション:" in optimized
    assert "注意点:" in optimized


def test_api_workspace_prompt_optimize_appends_japanese_rule_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _set_ai_chat_env(monkeypatch, api_key="test-key")

    def _fake_chat(
        *,
        messages: list[dict[str, str]],
        page_context: dict[str, str],
        policy_profile: str = "",
    ) -> dict[str, Any]:
        del messages, page_context, policy_profile
        return {
            "provider": "gemini",
            "model": "gemini-2.0-flash",
            "reply": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "optimizedPrompt": "Purpose:\n1. Check data\n2. Summarize findings",
                        "changes": ["structure"],
                        "assumptions": [],
                        "risks": [],
                        "needsConfirmation": [],
                    },
                    ensure_ascii=False,
                ),
            },
            "usage": {"prompt_tokens": 8, "completion_tokens": 8, "total_tokens": 16},
        }

    monkeypatch.setattr(api_workspace_routes.ai_chat, "chat", _fake_chat)

    res = client.post(
        "/api/workspace/prompt/optimize",
        json={"text": "遉ｾ蜀・・騾ｲ謐励ｒ遒ｺ隱阪☆繧九・繝ｭ繝ｳ繝励ヨ繧呈隼蝟・＠縺ｦ", "locale": "ja-JP"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    optimized = str(body.get("optimizedPrompt") or "")
    assert "出力は日本語で統一する。" in optimized


def test_api_scheduler_state_get_returns_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.get("/api/scheduler/state")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["enabled"] is False
    assert body["action_key"] == "preflight"
    assert body["card_id"] == ""
    assert body["recurrence"] == "once"
    assert body["run_time"] == "09:00"
    assert body["catch_up_policy"] == "run_on_startup"
    assert body["next_run_at"] is None
    assert isinstance(body.get("worker_running"), bool)
    assert int(body.get("worker_poll_seconds") or 0) >= 1
    assert str(body.get("worker_started_at") or "")


def test_api_scheduler_state_post_persists_context_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)

    post_res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": False,
            "card_id": "workflow-status",
            "action_key": "preflight_mf",
            "year": 2026,
            "month": 1,
            "run_date": "2026-03-01",
            "run_time": "08:30",
            "catch_up_policy": "run_on_startup",
            "recurrence": "daily",
        },
    )
    assert post_res.status_code == 200
    body = post_res.json()
    assert body["status"] == "ok"
    assert body["action_key"] == "preflight_mf"
    assert body["card_id"] == "workflow-status"
    assert body["year"] == 2026
    assert body["month"] == 1
    assert body["run_date"] == "2026-03-01"
    assert body["run_time"] == "08:30"
    assert body["recurrence"] == "daily"
    assert isinstance(body.get("worker_running"), bool)
    assert int(body.get("worker_poll_seconds") or 0) >= 1
    assert str(body.get("worker_started_at") or "")

    state_path = _artifact_root(tmp_path) / "_scheduler" / "scheduler_state.json"
    assert state_path.exists()
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["action_key"] == "preflight_mf"
    assert persisted["card_id"] == "workflow-status"
    assert persisted["run_date"] == "2026-03-01"
    assert persisted["run_time"] == "08:30"
    assert persisted["recurrence"] == "daily"


def test_api_scheduler_health_reports_worker_and_timers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    template_id = "tmpl-health-001"

    post_res = client.post(
        f"/api/scheduler/state?template_id={template_id}",
        json={
            "enabled": False,
            "card_id": "workflow-status",
            "action_key": "preflight",
            "run_time": "09:00",
            "recurrence": "once",
            "catch_up_policy": "run_on_startup",
        },
    )
    assert post_res.status_code == 200

    res = client.get("/api/scheduler/health?limit=20")
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"
    assert isinstance(body.get("worker_running"), bool)
    assert int(body.get("worker_poll_seconds") or 0) >= 1
    assert str(body.get("worker_started_at") or "")
    assert int(body.get("total_timers") or 0) >= 1
    assert int(body.get("enabled_timers") or 0) >= 0
    assert int(body.get("due_timers") or 0) >= 0
    assert int(body.get("active_locks") or 0) >= 0
    assert int(body.get("stale_locks") or 0) >= 0
    timers = body.get("timers") if isinstance(body.get("timers"), list) else []
    assert any(str(row.get("template_id") or "") == template_id for row in timers)


def test_api_scheduler_health_reports_trigger_lock_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    now = datetime.now()

    active_template = "scheduler-lock-active-health"
    stale_template = "scheduler-lock-stale-health"
    _write_json(
        public_core_scheduler._trigger_lock_path(active_template),
        {
            "template_id": active_template,
            "signature": "sig-active",
            "scheduled_for": now.isoformat(timespec="seconds"),
            "acquired_at": now.isoformat(timespec="seconds"),
            "token": "token-active",
        },
    )
    stale_at = now - timedelta(hours=7)
    _write_json(
        public_core_scheduler._trigger_lock_path(stale_template),
        {
            "template_id": stale_template,
            "signature": "sig-stale",
            "scheduled_for": stale_at.isoformat(timespec="seconds"),
            "acquired_at": stale_at.isoformat(timespec="seconds"),
            "token": "token-stale",
        },
    )

    res = client.get("/api/scheduler/health?limit=10")
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"
    assert int(body.get("active_locks") or 0) >= 1
    assert int(body.get("stale_locks") or 0) >= 1


def test_api_scheduler_restart_returns_health_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called: dict[str, Any] = {}

    def _fake_restart_worker() -> dict[str, Any]:
        called["restart"] = True
        return {
            "running": True,
            "poll_seconds": 7,
            "started_at": "2026-02-21T10:00:00",
        }

    def _fake_health_snapshot(*, limit: int = 50) -> dict[str, Any]:
        called["limit"] = int(limit)
        return {
            "worker_running": True,
            "worker_poll_seconds": 7,
            "worker_started_at": "2026-02-21T10:00:00",
            "total_timers": 1,
            "enabled_timers": 1,
            "due_timers": 0,
            "active_locks": 0,
            "stale_locks": 0,
            "timers": [
                {
                    "template_id": "tmpl-health-001",
                    "enabled": True,
                    "next_run_at": "2026-02-21T10:05:00",
                    "action_key": "preflight",
                    "run_date": "2026-02-21",
                    "run_time": "10:05",
                    "updated_at": "2026-02-21T10:00:00",
                }
            ],
        }

    monkeypatch.setattr(public_core_scheduler, "restart_worker", _fake_restart_worker)
    monkeypatch.setattr(public_core_scheduler, "health_snapshot", _fake_health_snapshot)
    client = _create_client(monkeypatch, tmp_path)

    res = client.post("/api/scheduler/restart", json={"limit": 25})
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"
    assert body.get("restarted") is True
    assert body.get("worker_running") is True
    assert int(body.get("worker_poll_seconds") or 0) == 7
    assert body.get("worker_started_at") == "2026-02-21T10:00:00"
    assert int(body.get("total_timers") or 0) == 1
    assert isinstance(body.get("timers"), list)
    assert called.get("restart") is True
    assert int(called.get("limit") or 0) == 25


def test_api_scheduler_state_post_rejects_enable_without_schedule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": True,
            "action_key": "preflight",
            "year": 2026,
            "month": 1,
            "run_date": "",
            "run_time": "09:00",
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "run_date" in detail


def test_api_scheduler_state_post_rejects_invalid_action_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": False,
            "action_key": "invalid_action",
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "action_key" in detail


def test_api_scheduler_state_post_rejects_invalid_recurrence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": False,
            "recurrence": "hourly",
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "recurrence" in detail


def test_api_scheduler_state_post_rejects_invalid_catch_up_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": False,
            "catch_up_policy": "invalid",
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "catch_up_policy" in detail


def test_api_scheduler_state_post_rejects_invalid_run_date_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": False,
            "run_date": "2026-02-30",
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "run_date" in detail


def test_api_scheduler_state_post_rejects_invalid_run_time_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": False,
            "run_time": "24:61",
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "run_time" in detail


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
            "action_key": "preflight",
            "card_id": "daily-test-card",
            "year": now.year,
            "month": now.month,
            "run_date": run_date,
            "run_time": run_time,
            "recurrence": "daily",
            "catch_up_policy": "run_on_startup",
        },
    )
    assert post_res.status_code == 200
    body = post_res.json()
    assert body["status"] == "ok"
    assert body["recurrence"] == "daily"
    assert body["enabled"] is True
    assert body["last_result"]["status"] == "started"
    assert body["last_result"]["reason_code"] == "started"
    assert run_payloads
    assert run_payloads[0]["year"] == now.year
    assert run_payloads[0]["month"] == now.month
    assert run_payloads[0]["mode"] == "preflight"
    assert run_payloads[0]["auth_handoff"] is False

    expected_next = now + timedelta(days=1)
    assert body["run_date"] == expected_next.strftime("%Y-%m-%d")
    assert body["run_time"] == run_time
    assert body["year"] == expected_next.year
    assert body["month"] == expected_next.month


def test_api_scheduler_state_daily_recurrence_run_on_startup_does_not_backfill_all_slots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def fake_start_run(payload: dict[str, Any]) -> dict[str, str]:
        run_payloads.append(dict(payload))
        return {"run_id": f"run_{len(run_payloads):03d}"}

    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", fake_start_run)

    now = datetime.now()
    run_time = (now - timedelta(minutes=1)).strftime("%H:%M")
    run_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")

    res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": True,
            "action_key": "preflight",
            "card_id": "daily-missed-run-on-startup",
            "year": now.year,
            "month": now.month,
            "run_date": run_date,
            "run_time": run_time,
            "recurrence": "daily",
            "catch_up_policy": "run_on_startup",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert (body.get("last_result") or {}).get("status") == "started"
    assert (body.get("last_result") or {}).get("reason_code") == "started"
    assert len(run_payloads) == 1
    expected_next = now + timedelta(days=1)
    assert body["run_date"] == expected_next.strftime("%Y-%m-%d")
    assert body["run_time"] == run_time


def test_api_scheduler_state_daily_recurrence_skip_policy_advances_to_future_slot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def fake_start_run(payload: dict[str, Any]) -> dict[str, str]:
        run_payloads.append(dict(payload))
        return {"run_id": f"run_{len(run_payloads):03d}"}

    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", fake_start_run)

    now = datetime.now()
    run_time = (now - timedelta(minutes=1)).strftime("%H:%M")
    run_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")

    res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": True,
            "action_key": "preflight",
            "card_id": "daily-missed-skip",
            "year": now.year,
            "month": now.month,
            "run_date": run_date,
            "run_time": run_time,
            "recurrence": "daily",
            "catch_up_policy": "skip",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert (body.get("last_result") or {}).get("status") == "skipped_missed"
    assert (body.get("last_result") or {}).get("reason_code") == "skipped_missed"
    assert len(run_payloads) == 0
    expected_next = now + timedelta(days=1)
    assert body["run_date"] == expected_next.strftime("%Y-%m-%d")
    assert body["run_time"] == run_time


def test_api_scheduler_state_weekly_recurrence_advances_by_week(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def fake_start_run(payload: dict[str, Any]) -> dict[str, str]:
        run_payloads.append(dict(payload))
        return {"run_id": f"run_{len(run_payloads):03d}"}

    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", fake_start_run)

    now = datetime.now()
    run_time = (now - timedelta(minutes=1)).strftime("%H:%M")
    run_date = now.strftime("%Y-%m-%d")

    res = client.post(
        "/api/scheduler/state",
        json={
            "enabled": True,
            "action_key": "preflight",
            "card_id": "weekly-test-card",
            "year": now.year,
            "month": now.month,
            "run_date": run_date,
            "run_time": run_time,
            "recurrence": "weekly",
            "catch_up_policy": "run_on_startup",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert (body.get("last_result") or {}).get("status") == "started"
    assert (body.get("last_result") or {}).get("reason_code") == "started"
    assert len(run_payloads) == 1

    expected_next = now + timedelta(days=7)
    assert body["run_date"] == expected_next.strftime("%Y-%m-%d")
    assert body["run_time"] == run_time
    assert body["year"] == expected_next.year
    assert body["month"] == expected_next.month


def test_api_scheduler_state_monthly_recurrence_preserves_anchor_day_after_short_month(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def fake_start_run(payload: dict[str, Any]) -> dict[str, str]:
        run_payloads.append(dict(payload))
        return {"run_id": f"run_{len(run_payloads):03d}"}

    class FrozenDateTime(datetime):
        current = datetime(2026, 2, 15, 10, 0, 0)

        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is not None:
                return cls.current.astimezone(tz)
            return cls.current

    monkeypatch.setattr(public_core_scheduler, "datetime", FrozenDateTime)
    monkeypatch.setattr(public_core_scheduler, "_started_at", datetime(2026, 2, 1, 0, 0, 0))
    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", fake_start_run)

    template_id = "scheduler-monthly-anchor"
    first = client.post(
        f"/api/scheduler/state?template_id={template_id}",
        json={
            "enabled": True,
            "action_key": "preflight",
            "card_id": "monthly-anchor-card",
            "year": 2026,
            "month": 1,
            "run_date": "2026-01-31",
            "run_time": "09:00",
            "recurrence": "monthly",
            "catch_up_policy": "run_on_startup",
        },
    )
    assert first.status_code == 200
    first_body = first.json()
    assert (first_body.get("last_result") or {}).get("status") == "started"
    assert first_body["run_date"] == "2026-02-28"
    assert first_body["run_time"] == "09:00"
    assert len(run_payloads) == 1

    FrozenDateTime.current = datetime(2026, 3, 1, 10, 0, 0)
    second = client.post(f"/api/scheduler/state?template_id={template_id}", json={"enabled": True})
    assert second.status_code == 200
    second_body = second.json()
    assert (second_body.get("last_result") or {}).get("status") == "started"
    assert second_body["run_date"] == "2026-03-31"
    assert second_body["run_time"] == "09:00"
    assert len(run_payloads) == 2


def test_api_scheduler_state_run_failure_retries_once_then_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def failing_start_run(payload: dict[str, Any]) -> dict[str, str]:
        run_payloads.append(dict(payload))
        raise HTTPException(status_code=500, detail="scheduler-test-failure")

    class FrozenDateTime(datetime):
        current = datetime(2026, 2, 20, 10, 0, 0)

        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is not None:
                return cls.current.astimezone(tz)
            return cls.current

    monkeypatch.setattr(public_core_scheduler, "datetime", FrozenDateTime)
    monkeypatch.setattr(public_core_scheduler, "_started_at", datetime(2026, 2, 20, 0, 0, 0))
    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", failing_start_run)

    template_id = "scheduler-failure-retry-once"
    payload = {
        "enabled": True,
        "action_key": "preflight",
        "card_id": "failure-retry-card",
        "year": 2026,
        "month": 2,
        "run_date": "2026-02-20",
        "run_time": "09:00",
        "recurrence": "once",
        "catch_up_policy": "run_on_startup",
    }

    first = client.post(f"/api/scheduler/state?template_id={template_id}", json=payload)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["enabled"] is True
    assert (first_body.get("last_result") or {}).get("status") == "deferred"
    assert (first_body.get("last_result") or {}).get("reason_code") == "retry_scheduled"
    assert len(run_payloads) == 1

    before_retry = client.post(f"/api/scheduler/state?template_id={template_id}", json={"enabled": True})
    assert before_retry.status_code == 200
    assert len(run_payloads) == 1
    assert (before_retry.json().get("last_result") or {}).get("reason_code") == "retry_scheduled"

    FrozenDateTime.current = datetime(2026, 2, 20, 10, 1, 5)
    second = client.post(f"/api/scheduler/state?template_id={template_id}", json={"enabled": True})
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["enabled"] is False
    assert (second_body.get("last_result") or {}).get("status") == "failed"
    assert (second_body.get("last_result") or {}).get("reason_code") == "retry_exhausted"
    assert len(run_payloads) == 2


def test_api_scheduler_state_run_failure_retry_succeeds_on_second_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def flaky_start_run(payload: dict[str, Any]) -> dict[str, str]:
        run_payloads.append(dict(payload))
        if len(run_payloads) == 1:
            raise HTTPException(status_code=500, detail="scheduler-test-flaky")
        return {"run_id": "run_retry_success_001"}

    class FrozenDateTime(datetime):
        current = datetime(2026, 2, 20, 10, 0, 0)

        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is not None:
                return cls.current.astimezone(tz)
            return cls.current

    monkeypatch.setattr(public_core_scheduler, "datetime", FrozenDateTime)
    monkeypatch.setattr(public_core_scheduler, "_started_at", datetime(2026, 2, 20, 0, 0, 0))
    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", flaky_start_run)

    template_id = "scheduler-failure-retry-success"
    payload = {
        "enabled": True,
        "action_key": "preflight",
        "card_id": "failure-retry-success-card",
        "year": 2026,
        "month": 2,
        "run_date": "2026-02-20",
        "run_time": "09:00",
        "recurrence": "once",
        "catch_up_policy": "run_on_startup",
    }

    first = client.post(f"/api/scheduler/state?template_id={template_id}", json=payload)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["enabled"] is True
    assert (first_body.get("last_result") or {}).get("reason_code") == "retry_scheduled"
    assert len(run_payloads) == 1

    FrozenDateTime.current = datetime(2026, 2, 20, 10, 1, 5)
    second = client.post(f"/api/scheduler/state?template_id={template_id}", json={"enabled": True})
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["enabled"] is False
    assert (second_body.get("last_result") or {}).get("status") == "started"
    assert (second_body.get("last_result") or {}).get("reason_code") == "started"
    assert len(run_payloads) == 2


def test_api_scheduler_state_enabled_true_without_transition_keeps_last_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def fake_start_run(payload: dict[str, Any]) -> dict[str, str]:
        run_payloads.append(dict(payload))
        return {"run_id": f"run_{len(run_payloads):03d}"}

    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", fake_start_run)

    now = datetime.now()
    run_time = (now - timedelta(minutes=1)).strftime("%H:%M")
    run_date = now.strftime("%Y-%m-%d")

    first = client.post(
        "/api/scheduler/state",
        json={
            "enabled": True,
            "action_key": "preflight",
            "card_id": "daily-rearm-transition",
            "year": now.year,
            "month": now.month,
            "run_date": run_date,
            "run_time": run_time,
            "recurrence": "daily",
            "catch_up_policy": "run_on_startup",
        },
    )
    assert first.status_code == 200
    assert (first.json().get("last_result") or {}).get("status") == "started"
    assert len(run_payloads) == 1

    second = client.post("/api/scheduler/state", json={"enabled": True})
    assert second.status_code == 200
    second_body = second.json()
    assert (second_body.get("last_result") or {}).get("status") == "started"
    assert len(run_payloads) == 1


def test_api_scheduler_state_defers_when_template_lock_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def fake_start_run(payload: dict[str, Any]) -> dict[str, str]:
        run_payloads.append(dict(payload))
        return {"run_id": "run_lock_should_not_start"}

    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", fake_start_run)

    now = datetime.now()
    template_id = "scheduler-template-lock-active"
    lock_path = public_core_scheduler._trigger_lock_path(template_id)
    _write_json(
        lock_path,
        {
            "template_id": template_id,
            "signature": "sig-1",
            "scheduled_for": now.isoformat(timespec="seconds"),
            "acquired_at": now.isoformat(timespec="seconds"),
            "token": "token-active",
        },
    )

    run_time = (now - timedelta(minutes=1)).strftime("%H:%M")
    run_date = now.strftime("%Y-%m-%d")
    res = client.post(
        f"/api/scheduler/state?template_id={template_id}",
        json={
            "enabled": True,
            "action_key": "preflight",
            "card_id": "lock-active-card",
            "year": now.year,
            "month": now.month,
            "run_date": run_date,
            "run_time": run_time,
            "recurrence": "daily",
            "catch_up_policy": "run_on_startup",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert (body.get("last_result") or {}).get("status") == "deferred"
    assert (body.get("last_result") or {}).get("reason_code") == "template_lock_active"
    assert len(run_payloads) == 0
    assert lock_path.exists() is True


def test_api_scheduler_state_reclaims_stale_template_lock_and_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def fake_start_run(payload: dict[str, Any]) -> dict[str, str]:
        run_payloads.append(dict(payload))
        return {"run_id": "run_stale_lock_reclaimed"}

    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", fake_start_run)

    now = datetime.now()
    template_id = "scheduler-template-lock-stale"
    lock_path = public_core_scheduler._trigger_lock_path(template_id)
    stale_at = now - timedelta(hours=7)
    _write_json(
        lock_path,
        {
            "template_id": template_id,
            "signature": "sig-stale",
            "scheduled_for": stale_at.isoformat(timespec="seconds"),
            "acquired_at": stale_at.isoformat(timespec="seconds"),
            "token": "token-stale",
        },
    )

    run_time = (now - timedelta(minutes=1)).strftime("%H:%M")
    run_date = now.strftime("%Y-%m-%d")
    res = client.post(
        f"/api/scheduler/state?template_id={template_id}",
        json={
            "enabled": True,
            "action_key": "preflight",
            "card_id": "lock-stale-card",
            "year": now.year,
            "month": now.month,
            "run_date": run_date,
            "run_time": run_time,
            "recurrence": "daily",
            "catch_up_policy": "run_on_startup",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert (body.get("last_result") or {}).get("status") == "started"
    assert (body.get("last_result") or {}).get("reason_code") == "started"
    assert len(run_payloads) == 1
    assert lock_path.exists() is False


def test_api_scheduler_state_once_rearm_with_same_slot_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def fake_start_run(payload: dict[str, Any]) -> dict[str, str]:
        run_payloads.append(dict(payload))
        return {"run_id": f"run_{len(run_payloads):03d}"}

    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", fake_start_run)

    now = datetime.now()
    run_time = (now - timedelta(minutes=1)).strftime("%H:%M")
    run_date = now.strftime("%Y-%m-%d")
    template_id = "scheduler-once-idempotent"

    payload = {
        "enabled": True,
        "action_key": "preflight",
        "card_id": "once-idempotent-card",
        "year": now.year,
        "month": now.month,
        "run_date": run_date,
        "run_time": run_time,
        "recurrence": "once",
        "catch_up_policy": "run_on_startup",
    }

    first = client.post(f"/api/scheduler/state?template_id={template_id}", json=payload)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["status"] == "ok"
    assert first_body["enabled"] is False
    assert (first_body.get("last_result") or {}).get("status") == "started"
    assert len(run_payloads) == 1

    second = client.post(f"/api/scheduler/state?template_id={template_id}", json=payload)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["status"] == "ok"
    assert second_body["enabled"] is False
    assert (second_body.get("last_result") or {}).get("status") == "skipped_duplicate"
    assert (second_body.get("last_result") or {}).get("reason_code") == "duplicate_once_schedule"
    assert len(run_payloads) == 1

    state_path = _artifact_root(tmp_path) / "_scheduler" / "scheduler_state.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    once_receipts = persisted.get("once_trigger_receipts")
    assert isinstance(once_receipts, dict)
    receipt_key = f"{template_id}|{run_date}|{run_time}"
    assert receipt_key in once_receipts
    assert str((once_receipts.get(receipt_key) or {}).get("run_id") or "") == "run_001"

    ym = f"{now.year:04d}-{now.month:02d}"
    entries = _read_audit_entries(tmp_path, ym)
    scheduler_entries = [row for row in entries if str(row.get("event_type") or "") == "scheduler"]
    assert any(str(row.get("status") or "") == "started" for row in scheduler_entries)
    assert any(
        str(row.get("status") or "") == "skipped"
        and str((row.get("details") or {}).get("reason") or "") == "duplicate_once_schedule"
        for row in scheduler_entries
    )


def test_scheduler_delete_timer_state_removes_once_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)

    def fake_start_run(payload: dict[str, Any]) -> dict[str, str]:
        return {"run_id": "run_001"}

    monkeypatch.setattr(public_core_scheduler.core_runs, "_start_run", fake_start_run)

    now = datetime.now()
    run_time = (now - timedelta(minutes=1)).strftime("%H:%M")
    run_date = now.strftime("%Y-%m-%d")
    template_id = "scheduler-delete-receipt"

    res = client.post(
        f"/api/scheduler/state?template_id={template_id}",
        json={
            "enabled": True,
            "action_key": "preflight",
            "card_id": "delete-receipt-card",
            "year": now.year,
            "month": now.month,
            "run_date": run_date,
            "run_time": run_time,
            "recurrence": "once",
            "catch_up_policy": "run_on_startup",
        },
    )
    assert res.status_code == 200

    state_path = _artifact_root(tmp_path) / "_scheduler" / "scheduler_state.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    before_receipts = persisted.get("once_trigger_receipts") or {}
    assert any(str(key).startswith(f"{template_id}|") for key in before_receipts)

    public_core_scheduler.delete_timer_state(template_id)
    persisted_after = json.loads(state_path.read_text(encoding="utf-8"))
    after_receipts = persisted_after.get("once_trigger_receipts") or {}
    assert not any(str(key).startswith(f"{template_id}|") for key in after_receipts)


def test_api_get_workflow_templates_supports_search_sort_and_pagination(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_json(
        _workflow_template_store(tmp_path),
        [
            {
                "id": "tmpl-alpha",
                "name": "Alpha",
                "year": 2026,
                "month": 1,
                "mfcloud_url": "https://example.com/alpha",
                "notes": "alpha workflow",
                "rakuten_orders_url": "",
                "created_at": "2026-02-01T10:00:00",
                "updated_at": "2026-02-01T10:00:00",
            },
            {
                "id": "tmpl-beta",
                "name": "Beta",
                "year": 2025,
                "month": 12,
                "mfcloud_url": "https://example.com/beta",
                "notes": "beta workflow",
                "rakuten_orders_url": "",
                "created_at": "2026-02-02T10:00:00",
                "updated_at": "2026-02-03T10:00:00",
            },
            {
                "id": "tmpl-gamma",
                "name": "Gamma",
                "year": 2027,
                "month": 3,
                "mfcloud_url": "https://example.com/gamma",
                "notes": "gamma workflow",
                "rakuten_orders_url": "",
                "created_at": "2026-02-03T10:00:00",
                "updated_at": "2026-01-30T10:00:00",
            },
        ],
    )
    client = _create_client(monkeypatch, tmp_path)

    res_by_year = client.get("/api/workflow-templates?sort=year_desc")
    assert res_by_year.status_code == 200
    body_by_year = res_by_year.json()
    assert [item["name"] for item in body_by_year["templates"]] == ["Gamma", "Alpha", "Beta"]
    assert body_by_year["count"] == 3
    assert body_by_year["total_count"] == 3

    res_by_name = client.get("/api/workflow-templates?search=alpha&sort=name_asc")
    assert res_by_name.status_code == 200
    body_by_name = res_by_name.json()
    assert [item["name"] for item in body_by_name["templates"]] == ["Alpha"]
    assert body_by_name["count"] == 1
    assert body_by_name["total_count"] == 1

    res_paged = client.get("/api/workflow-templates?sort=updated_desc&limit=2&offset=1")
    assert res_paged.status_code == 200
    body_paged = res_paged.json()
    assert [item["name"] for item in body_paged["templates"]] == ["Alpha", "Gamma"]
    assert body_paged["count"] == 2
    assert body_paged["total_count"] == 3


def test_api_workflow_subheading_treats_legacy_default_text_as_blank(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_json(
        _workflow_template_store(tmp_path),
        [
            {
                "id": "tmpl-legacy-subheading",
                "name": "Legacy Template",
                "year": 2026,
                "month": 1,
                "mfcloud_url": "https://example.com/legacy",
                "notes": "",
                "subheading": "成果物の確認と実行をまとめて管理します。ローカル専用（127.0.0.1）。",
                "rakuten_orders_url": "",
                "created_at": "2026-02-01T10:00:00",
                "updated_at": "2026-02-01T10:00:00",
            },
        ],
    )
    _write_json(
        _workflow_pages_store(tmp_path),
        [
            {
                "id": "wf-legacy-subheading",
                "name": "Legacy Page",
                "subheading": "補足説明（任意）はここに書かれる。",
                "year": 2026,
                "month": 2,
                "mfcloud_url": "https://example.com/mf",
                "source_urls": ["https://example.com/mf"],
                "steps": [{"id": "step-1", "title": "Amazon蜿門ｾ・", "action": "amazon_download"}],
                "notes": "",
                "rakuten_orders_url": "",
                "source_template_id": "tmpl-legacy-subheading",
                "step_version": 1,
                "step_versions": [
                    {
                        "version": 1,
                        "updated_at": "2026-02-01T10:00:00",
                        "steps": [{"id": "step-1", "title": "Amazon蜿門ｾ・", "action": "amazon_download"}],
                    }
                ],
                "archived": False,
                "archived_at": "",
                "created_at": "2026-02-01T10:00:00",
                "updated_at": "2026-02-01T10:00:00",
            },
        ],
    )
    client = _create_client(monkeypatch, tmp_path)

    templates_res = client.get("/api/workflow-templates")
    assert templates_res.status_code == 200
    templates = templates_res.json()["templates"]
    assert templates and templates[0]["subheading"] == ""

    pages_res = client.get("/api/workflow-pages")
    assert pages_res.status_code == 200
    pages = pages_res.json()["workflow_pages"]
    assert pages and pages[0]["subheading"] == ""


def test_api_save_workflow_template_duplicate_name_and_update_conflict(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    create_payload = {
        "name": "Alpha",
        "year": 2026,
        "month": 1,
        "mfcloud_url": "https://example.com/alpha",
        "notes": "first",
    }
    create_res = client.post("/api/workflow-templates", json=create_payload)
    assert create_res.status_code == 200
    created = create_res.json()["template"]
    template_id = str(created["id"])
    base_updated_at = str(created.get("updated_at") or "")
    assert template_id

    duplicate_res = client.post("/api/workflow-templates", json=create_payload)
    assert duplicate_res.status_code == 409
    assert "Template name already exists." in str(duplicate_res.json().get("detail"))

    update_payload = {
        "template_id": template_id,
        "name": "Alpha",
        "year": 2026,
        "month": 1,
        "mfcloud_url": "https://example.com/alpha",
        "notes": "updated",
        "base_updated_at": base_updated_at,
    }
    update_res = client.post("/api/workflow-templates", json=update_payload)
    assert update_res.status_code == 200
    assert update_res.json()["updated"] is True
    assert update_res.json()["template"]["notes"] == "updated"

    stale_payload = dict(update_payload)
    stale_payload["notes"] = "stale"
    stale_payload["base_updated_at"] = base_updated_at
    stored = json.loads(_workflow_template_store(tmp_path).read_text(encoding="utf-8"))
    assert isinstance(stored, list) and stored
    stored[0]["updated_at"] = "2026-03-01T00:00:00"
    _write_json(_workflow_template_store(tmp_path), stored)

    stale_conflict_res = client.post("/api/workflow-templates", json=stale_payload)
    assert stale_conflict_res.status_code == 409
    assert "Template was updated by another action." in str(stale_conflict_res.json().get("detail"))


def test_api_save_workflow_template_allows_empty_year_month(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "No Ym",
            "mfcloud_url": "https://example.com/no-ym",
            "notes": "no year/month",
            "steps": [
                {"title": "  Step 1  "},
                {"name": "Step 2"},
                {},
            ],
        },
    )
    assert res.status_code == 200
    template = res.json()["template"]
    assert template["year"] == 0
    assert template["month"] == 0
    steps = template["steps"]
    assert isinstance(steps, list)
    assert len(steps) == 2
    assert any(
        str(step.get("title") or "") == "Step 1"
        and str(step.get("action") or "") == ""
        and str(step.get("type") or "") == "manual"
        and str(step.get("trigger") or "") == "manual"
        and str(step.get("target_url") or "") == ""
        and str(step.get("agent_prompt") or "") == ""
        and int(step.get("order") or 0) >= 1
        and bool(step.get("auto_run")) is False
        and step.get("timer_minutes") is None
        and isinstance(step.get("execution_log"), list)
        for step in steps
        if isinstance(step, dict)
    )
    assert any(
        str(step.get("title") or "") == "Step 2"
        and int(step.get("order") or 0) >= 1
        for step in steps
        if isinstance(step, dict)
    )

    rows = json.loads(_workflow_template_store(tmp_path).read_text(encoding="utf-8"))
    assert isinstance(rows, list) and rows
    assert rows[0]["year"] == 0
    assert rows[0]["month"] == 0
    stored_steps = rows[0]["steps"]
    assert isinstance(stored_steps, list)
    assert len(stored_steps) == len(steps)
    assert any(
        str(step.get("title") or "") == "Step 1"
        and str(step.get("action") or "") == ""
        and str(step.get("type") or "") == "manual"
        and str(step.get("trigger") or "") == "manual"
        and str(step.get("target_url") or "") == ""
        and str(step.get("agent_prompt") or "") == ""
        and isinstance(step.get("execution_log"), list)
        for step in stored_steps
        if isinstance(step, dict)
    )


def test_api_create_workflow_page_keeps_blank_action_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-pages",
        json={
            "name": "Blank Workflow",
            "year": 2026,
            "month": 1,
            "steps": [
                {"title": "step only title"},
                {"title": "explicit blank action", "action": ""},
            ],
        },
    )
    assert res.status_code == 200
    page = res.json()["workflow_page"]
    assert page["lifecycle_state"] == "draft"
    assert page["fixed_at"] == ""
    assert page["mfcloud_url"] == ""
    assert page["source_urls"] == []
    assert page["notes"] == ""
    assert page["rakuten_orders_url"] == ""
    steps = page.get("steps") if isinstance(page.get("steps"), list) else []
    assert len(steps) == 2
    assert all(str(step.get("action") or "") == "" for step in steps if isinstance(step, dict))

    rows = json.loads(_workflow_pages_store(tmp_path).read_text(encoding="utf-8"))
    assert isinstance(rows, list) and rows
    assert str(rows[0].get("lifecycle_state") or "") == "draft"
    assert str(rows[0].get("fixed_at") or "") == ""
    stored_steps = rows[0].get("steps") if isinstance(rows[0], dict) else []
    assert isinstance(stored_steps, list)
    assert len(stored_steps) == 2
    assert all(str(step.get("action") or "") == "" for step in stored_steps if isinstance(step, dict))


def test_api_create_workflow_page_does_not_copy_scheduler_or_template_card_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copy_calls: list[tuple[str, str]] = []

    def _fake_copy_timer_state(source_template_id: str, target_template_id: str) -> dict[str, Any]:
        copy_calls.append((source_template_id, target_template_id))
        return {"status": "ok"}

    monkeypatch.setattr(public_core_scheduler, "copy_timer_state", _fake_copy_timer_state)
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-pages",
        json={
            "name": "Workflow Only",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/from-template",
            "source_urls": ["https://example.com/from-template"],
            "notes": "template notes should not be copied",
            "rakuten_orders_url": "https://example.com/rakuten",
            "source_template_id": "template-source-1",
            "steps": [{"title": "Step 1", "action": "preflight"}],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("scheduler_copied") is False
    page = body.get("workflow_page") if isinstance(body.get("workflow_page"), dict) else {}
    assert page.get("lifecycle_state") == "draft"
    assert page.get("fixed_at") == ""
    assert page.get("mfcloud_url") == ""
    assert page.get("source_urls") == []
    assert page.get("notes") == ""
    assert page.get("rakuten_orders_url") == ""
    assert copy_calls == []


def test_api_workflow_page_fixed_state_blocks_mutations_until_draft(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    create_res = client.post(
        "/api/workflow-pages",
        json={
            "name": "Lock Target",
            "year": 2026,
            "month": 2,
            "steps": [{"title": "Step 1", "action": "preflight"}],
        },
    )
    assert create_res.status_code == 200
    created_page = create_res.json()["workflow_page"]
    page_id = str(created_page.get("id") or "")
    assert page_id

    fixed_res = client.patch(
        f"/api/workflow-pages/{page_id}",
        json={
            "lifecycle_state": "fixed",
            "base_updated_at": str(created_page.get("updated_at") or ""),
        },
    )
    assert fixed_res.status_code == 200
    fixed_page = fixed_res.json()["workflow_page"]
    assert fixed_page["lifecycle_state"] == "fixed"
    assert str(fixed_page.get("fixed_at") or "")

    blocked_res = client.patch(
        f"/api/workflow-pages/{page_id}",
        json={
            "steps": [{"title": "Step 1 updated", "action": "preflight"}],
            "base_updated_at": str(fixed_page.get("updated_at") or ""),
            "base_step_version": int(fixed_page.get("step_version") or 1),
        },
    )
    assert blocked_res.status_code == 409
    assert "Workflow page is fixed. Switch to draft before editing." in str(blocked_res.json().get("detail"))

    to_draft_res = client.patch(
        f"/api/workflow-pages/{page_id}",
        json={
            "lifecycle_state": "draft",
            "base_updated_at": str(fixed_page.get("updated_at") or ""),
        },
    )
    assert to_draft_res.status_code == 200
    draft_page = to_draft_res.json()["workflow_page"]
    assert draft_page["lifecycle_state"] == "draft"
    assert str(draft_page.get("fixed_at") or "") == ""

    edit_res = client.patch(
        f"/api/workflow-pages/{page_id}",
        json={
            "steps": [{"title": "Step 1 updated", "action": "preflight"}],
            "base_updated_at": str(draft_page.get("updated_at") or ""),
            "base_step_version": int(draft_page.get("step_version") or 1),
        },
    )
    assert edit_res.status_code == 200
    edited_page = edit_res.json()["workflow_page"]
    edited_steps = edited_page.get("steps") if isinstance(edited_page.get("steps"), list) else []
    assert edited_steps and str(edited_steps[0].get("title") or "") == "Step 1 updated"


def test_api_save_workflow_template_persists_step_timer_minutes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _write_json(
        _workflow_template_store(tmp_path),
        [
            {
                "id": "timer-template",
                "name": "Timer Template",
                "year": 2026,
                "month": 2,
                "mfcloud_url": "https://example.com/timer",
                "source_urls": ["https://example.com/timer"],
                "steps": [{"title": "Initial"}],
                "notes": "",
                "subheading": "",
                "rakuten_orders_url": "",
                "created_at": "2026-02-01T00:00:00",
                "updated_at": "2026-02-01T00:00:00",
            },
        ],
    )
    res = client.post(
        "/api/workflow-templates",
        json={
            "template_id": "timer-template",
            "template_mode": "edit",
            "base_updated_at": "2026-02-01T00:00:00",
            "name": "Timer Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/timer",
            "steps": [
                {"title": "Step 1", "action": "preflight", "timer_minutes": 15},
                {"title": "Step 2", "timer_minutes": 999999},
            ],
        },
    )
    assert res.status_code == 200
    template = res.json()["template"]
    steps = template["steps"]
    assert any(
        str(step.get("title") or "") == "Step 1"
        and str(step.get("action") or "") == "preflight"
        and int(step.get("timer_minutes") or 0) == 15
        for step in steps
        if isinstance(step, dict)
    )
    assert any(
        str(step.get("title") or "") == "Step 2"
        and int(step.get("timer_minutes") or 0) == 10080
        for step in steps
        if isinstance(step, dict)
    )

    rows = json.loads(_workflow_template_store(tmp_path).read_text(encoding="utf-8"))
    assert isinstance(rows, list) and rows
    stored_steps = rows[0]["steps"]
    assert any(
        str(step.get("title") or "") == "Step 1"
        and str(step.get("action") or "") == "preflight"
        and int(step.get("timer_minutes") or 0) == 15
        for step in stored_steps
        if isinstance(step, dict)
    )
    assert any(
        str(step.get("title") or "") == "Step 2"
        and int(step.get("timer_minutes") or 0) == 10080
        for step in stored_steps
        if isinstance(step, dict)
    )


def test_api_save_workflow_template_persists_step_v2_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    _write_json(
        _workflow_template_store(tmp_path),
        [
            {
                "id": "v2-template",
                "name": "V2 Template",
                "year": 2026,
                "month": 2,
                "mfcloud_url": "https://example.com/v2",
                "source_urls": ["https://example.com/v2"],
                "steps": [{"title": "Initial"}],
                "notes": "",
                "subheading": "",
                "rakuten_orders_url": "",
                "created_at": "2026-02-01T00:00:00",
                "updated_at": "2026-02-01T00:00:00",
            },
        ],
    )
    res = client.post(
        "/api/workflow-templates",
        json={
            "template_id": "v2-template",
            "template_mode": "edit",
            "base_updated_at": "2026-02-01T00:00:00",
            "name": "V2 Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/v2",
            "steps": [
                {
                    "title": "Browser Step",
                    "action": "preflight",
                    "type": "browser",
                    "trigger": "webhook",
                    "target_url": "https://example.com/browser",
                },
                {
                    "title": "Agent Step",
                    "trigger": "after_step",
                    "agent_prompt": "  collect summary and post result  ",
                },
                {
                    "title": "Manual Step",
                    "type": "invalid-type",
                    "trigger": "invalid-trigger",
                    "target_url": "javascript:alert(1)",
                    "agent_prompt": "",
                },
            ],
        },
    )
    assert res.status_code == 200
    template = res.json()["template"]
    steps = template["steps"]
    assert any(
        str(step.get("title") or "") == "Browser Step"
        and str(step.get("type") or "") == "browser"
        and str(step.get("step_type") or "") == "browser"
        and str(step.get("trigger_kind") or "") == "external_event"
        and str(step.get("trigger") or "") == "webhook"
        and str(step.get("execution_mode") or "") == "manual_confirm"
        and str(step.get("target_url") or "") == "https://example.com/browser"
        and str(step.get("agent_prompt") or "") == ""
        for step in steps
        if isinstance(step, dict)
    )
    assert any(
        str(step.get("title") or "") == "Agent Step"
        and str(step.get("type") or "") == "agent"
        and str(step.get("step_type") or "") == "agent"
        and str(step.get("trigger_kind") or "") == "after_previous"
        and str(step.get("trigger") or "") == "after_step"
        and str(step.get("execution_mode") or "") == "manual_confirm"
        and str(step.get("target_url") or "") == ""
        and str(step.get("agent_prompt") or "") == "collect summary and post result"
        for step in steps
        if isinstance(step, dict)
    )
    assert any(
        str(step.get("title") or "") == "Manual Step"
        and str(step.get("type") or "") == "manual"
        and str(step.get("step_type") or "") == "manual"
        and str(step.get("trigger_kind") or "") == "after_previous"
        and str(step.get("trigger") or "") == "after_step"
        and str(step.get("execution_mode") or "") == "manual_confirm"
        and str(step.get("target_url") or "") == ""
        and str(step.get("agent_prompt") or "") == ""
        for step in steps
        if isinstance(step, dict)
    )

    rows = json.loads(_workflow_template_store(tmp_path).read_text(encoding="utf-8"))
    assert isinstance(rows, list) and rows
    stored_steps = rows[0]["steps"]
    assert any(
        str(step.get("title") or "") == "Browser Step"
        and str(step.get("type") or "") == "browser"
        and str(step.get("step_type") or "") == "browser"
        and str(step.get("trigger_kind") or "") == "external_event"
        and str(step.get("trigger") or "") == "webhook"
        and str(step.get("execution_mode") or "") == "manual_confirm"
        and str(step.get("target_url") or "") == "https://example.com/browser"
        for step in stored_steps
        if isinstance(step, dict)
    )
    assert any(
        str(step.get("title") or "") == "Agent Step"
        and str(step.get("type") or "") == "agent"
        and str(step.get("step_type") or "") == "agent"
        and str(step.get("trigger_kind") or "") == "after_previous"
        and str(step.get("trigger") or "") == "after_step"
        and str(step.get("execution_mode") or "") == "manual_confirm"
        and str(step.get("agent_prompt") or "") == "collect summary and post result"
        for step in stored_steps
        if isinstance(step, dict)
    )


def test_api_save_workflow_template_maps_legacy_step_fields_to_canonical(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Legacy Mapping Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/legacy-map",
            "steps": [
                {
                    "title": "Start",
                    "type": "agent",
                    "trigger": "schedule",
                    "auto_run": True,
                    "timer_minutes": 10,
                    "agent_prompt": "collect and summarize",
                },
                {
                    "title": "Follow",
                    "trigger": "after_step",
                },
            ],
        },
    )
    assert res.status_code == 200
    template = res.json()["template"]
    steps = template.get("steps") if isinstance(template.get("steps"), list) else []
    first = next(
        (step for step in steps if isinstance(step, dict) and str(step.get("title") or "") == "Start"),
        None,
    )
    assert isinstance(first, dict)
    assert str(first.get("trigger_kind") or "") == "scheduled"
    assert str(first.get("trigger") or "") == "schedule"
    assert str(first.get("execution_mode") or "") == "auto"
    assert bool(first.get("auto_run")) is True
    assert int(first.get("timer_minutes") or 0) == 10


def test_api_save_workflow_template_rejects_invalid_trigger_by_position(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Invalid Trigger Position",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/invalid-trigger",
            "steps": [
                {"title": "Step 1", "trigger_kind": "manual_start"},
                {"title": "Step 2", "trigger_kind": "scheduled"},
            ],
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "Step 2 trigger_kind must be after_previous" in detail


def test_api_save_workflow_template_rejects_invalid_first_trigger_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Invalid First Trigger",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/invalid-first-trigger",
            "steps": [
                {"title": "Step 1", "trigger_kind": "after_previous"},
            ],
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "Step 1 trigger_kind must be manual_start, scheduled, or external_event" in detail


def test_api_save_workflow_template_rejects_manual_auto_execution_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Invalid Manual Auto Mode",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/manual-auto",
            "steps": [
                {
                    "title": "Step 1",
                    "type": "manual",
                    "trigger_kind": "manual_start",
                    "execution_mode": "auto",
                    "timer_minutes": 5,
                }
            ],
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "manual step must use execution_mode=manual_confirm" in detail


def test_api_save_workflow_template_rejects_browser_without_target_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Invalid Browser Step",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/browser-invalid",
            "steps": [
                {
                    "title": "Step 1",
                    "type": "browser",
                    "trigger_kind": "manual_start",
                }
            ],
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "browser step requires a valid target_url" in detail


def test_api_save_workflow_template_rejects_agent_without_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Invalid Agent Step",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/agent-invalid",
            "steps": [
                {
                    "title": "Step 1",
                    "type": "agent",
                    "trigger_kind": "manual_start",
                }
            ],
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "agent step requires agent_prompt" in detail


def test_api_save_workflow_template_rejects_auto_mode_without_timer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Invalid Auto Timer",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/auto-invalid",
            "steps": [
                {
                    "title": "Step 1",
                    "type": "agent",
                    "trigger_kind": "manual_start",
                    "execution_mode": "auto",
                    "agent_prompt": "run task",
                }
            ],
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "execution_mode=auto requires timer_minutes" in detail


def test_api_save_workflow_template_rejects_auto_mode_with_zero_timer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Invalid Auto Zero Timer",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/auto-zero",
            "steps": [
                {
                    "title": "Step 1",
                    "type": "agent",
                    "trigger_kind": "manual_start",
                    "execution_mode": "auto",
                    "agent_prompt": "run task",
                    "timer_minutes": 0,
                }
            ],
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "execution_mode=auto requires timer_minutes" in detail


def test_api_save_workflow_template_copy_mode_creates_new_template(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    create_payload = {
        "name": "Alpha",
        "year": 2026,
        "month": 1,
        "mfcloud_url": "https://example.com/alpha",
        "notes": "base",
    }
    create_res = client.post("/api/workflow-templates", json=create_payload)
    assert create_res.status_code == 200
    created = create_res.json()["template"]

    copy_payload = {
        "template_id": "",
        "name": "Alpha Copy",
        "year": 2026,
        "month": 1,
        "mfcloud_url": "https://example.com/alpha",
        "notes": "copied",
        "base_updated_at": str(created.get("updated_at") or ""),
        "rakuten_orders_url": "",
    }
    copy_res = client.post("/api/workflow-templates", json=copy_payload)
    assert copy_res.status_code == 200
    body = copy_res.json()
    assert body["updated"] is False
    assert body["template"]["name"] == "Alpha Copy"
    assert body["template"]["id"] != created["id"]

    rows = json.loads(_workflow_template_store(tmp_path).read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    assert len(rows) == 2


def test_api_save_workflow_template_copy_mode_copies_source_scheduler_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    create_payload = {
        "name": "Alpha",
        "year": 2026,
        "month": 1,
        "mfcloud_url": "https://example.com/alpha",
        "notes": "base",
    }
    create_res = client.post("/api/workflow-templates", json=create_payload)
    assert create_res.status_code == 200
    created = create_res.json()["template"]
    source_template_id = str(created["id"])
    assert source_template_id

    scheduler_res = client.post(
        f"/api/scheduler/state?template_id={source_template_id}",
        json={
            "enabled": True,
            "card_id": "source-card",
            "action_key": "preflight_mf",
            "year": 2026,
            "month": 1,
            "run_date": "2099-01-01",
            "run_time": "08:30",
            "catch_up_policy": "run_on_startup",
            "recurrence": "daily",
        },
    )
    assert scheduler_res.status_code == 200
    source_timer_state = scheduler_res.json()
    assert source_timer_state["status"] == "ok"

    copy_payload = {
        "template_mode": "copy",
        "template_source_id": source_template_id,
        "name": "Alpha Copy",
        "year": 2026,
        "month": 1,
        "mfcloud_url": "https://example.com/alpha",
        "notes": "copied",
        "base_updated_at": str(created.get("updated_at") or ""),
        "rakuten_orders_url": "",
    }
    copy_res = client.post("/api/workflow-templates", json=copy_payload)
    assert copy_res.status_code == 200
    copied = copy_res.json()["template"]
    copied_template_id = str(copied["id"])
    assert copied_template_id
    assert copied_template_id != source_template_id

    state_path = _artifact_root(tmp_path) / "_scheduler" / "scheduler_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    timers = state.get("template_timers")
    assert isinstance(timers, dict)
    assert source_template_id in timers
    assert copied_template_id in timers

    copied_timer = timers[copied_template_id]
    assert copied_timer["action_key"] == source_timer_state["action_key"]
    assert copied_timer["card_id"] == source_timer_state["card_id"]
    assert copied_timer["run_date"] == source_timer_state["run_date"]
    assert copied_timer["run_time"] == source_timer_state["run_time"]
    assert copied_timer["catch_up_policy"] == source_timer_state["catch_up_policy"]
    assert copied_timer["recurrence"] == source_timer_state["recurrence"]
    assert copied_timer["year"] == source_timer_state["year"]
    assert copied_timer["month"] == source_timer_state["month"]
    assert copied_timer["enabled"] is False
    assert copied_timer["last_result"] is None
    assert copied_timer["last_triggered_signature"] == ""


def test_api_save_workflow_template_copy_mode_requires_source_template_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "template_mode": "copy",
            "name": "Alpha Copy",
            "year": 2026,
            "month": 1,
            "mfcloud_url": "https://example.com/alpha",
            "notes": "copied",
        },
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "template_source_id is required for copy mode" in detail


def test_api_save_workflow_template_copy_mode_rejects_unknown_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "template_mode": "copy",
            "template_source_id": "not-exists-123",
            "name": "Alpha Copy",
            "year": 2026,
            "month": 1,
            "mfcloud_url": "https://example.com/alpha",
            "notes": "copied",
            "base_updated_at": "2099-01-01T00:00:00",
        },
    )
    assert res.status_code == 404
    detail = str(res.json().get("detail") or "")
    assert "template_source_id not found" in detail


def test_api_delete_workflow_template_removes_template_timer_and_clears_references(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Base",
            "year": 2026,
            "month": 1,
            "mfcloud_url": "https://example.com/base",
            "notes": "base",
        },
    )
    assert create_res.status_code == 200
    base_template = create_res.json()["template"]
    base_template_id = str(base_template["id"])
    assert base_template_id

    state_res = client.post(
        f"/api/scheduler/state?template_id={base_template_id}",
        json={
            "enabled": True,
            "card_id": "base-card",
            "action_key": "preflight_mf",
            "year": 2026,
            "month": 1,
            "run_date": "2099-01-01",
            "run_time": "08:30",
            "catch_up_policy": "run_on_startup",
            "recurrence": "daily",
        },
    )
    assert state_res.status_code == 200

    copy_child_res = client.post(
        "/api/workflow-templates",
        json={
            "template_mode": "copy",
            "template_source_id": base_template_id,
            "name": "Child Copy",
            "year": 2026,
            "month": 1,
            "mfcloud_url": "https://example.com/base",
            "notes": "child",
            "rakuten_orders_url": "",
        },
    )
    assert copy_child_res.status_code == 200
    child_template = copy_child_res.json()["template"]
    child_template_id = str(child_template["id"])
    assert child_template_id

    copy_grandchild_res = client.post(
        "/api/workflow-templates",
        json={
            "template_mode": "copy",
            "template_source_id": child_template_id,
            "name": "Grandchild Copy",
            "year": 2026,
            "month": 1,
            "mfcloud_url": "https://example.com/base",
            "notes": "grandchild",
            "rakuten_orders_url": "",
        },
    )
    assert copy_grandchild_res.status_code == 200
    grandchild_template = copy_grandchild_res.json()["template"]
    grandchild_template_id = str(grandchild_template["id"])
    assert grandchild_template_id

    delete_res = client.delete(f"/api/workflow-templates/{child_template_id}")
    assert delete_res.status_code == 200
    delete_body = delete_res.json()
    assert delete_body["deleted_template_id"] == child_template_id
    assert delete_body["count"] == 2

    templates = json.loads(_workflow_template_store(tmp_path).read_text(encoding="utf-8"))
    assert isinstance(templates, list)
    assert all(str(row.get("id") or "") != child_template_id for row in templates)
    assert any(str(row.get("id") or "") == grandchild_template_id for row in templates)
    for row in templates:
        if str(row.get("id") or "") == grandchild_template_id:
            assert str(row.get("source_template_id") or "") == ""

    state_path = _artifact_root(tmp_path) / "_scheduler" / "scheduler_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    timers = state.get("template_timers")
    assert isinstance(timers, dict)
    assert base_template_id in timers
    assert child_template_id not in timers
    assert grandchild_template_id in timers


def test_api_delete_workflow_template_concurrency_conflict(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Base",
            "year": 2026,
            "month": 1,
            "mfcloud_url": "https://example.com/base",
            "notes": "base",
        },
    )
    assert create_res.status_code == 200
    created = create_res.json()["template"]
    template_id = str(created["id"])
    assert template_id
    stale_stamp = "2000-01-01T00:00:00"

    conflict_res = client.delete(f"/api/workflow-templates/{template_id}?base_updated_at={stale_stamp}")
    assert conflict_res.status_code == 409
    detail = str(conflict_res.json().get("detail") or "")
    assert "Template was updated by another action." in detail


def test_api_delete_workflow_template_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    target_id = "a" * 24
    res = client.delete(f"/api/workflow-templates/{target_id}")
    assert res.status_code == 404
    assert str(res.json().get("detail") or "").startswith("Template not found")


def test_api_delete_workflow_template_invalid_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    invalid_id = "x" * 65
    res = client.delete(f"/api/workflow-templates/{invalid_id}")
    assert res.status_code == 400
    assert str(res.json().get("detail") or "") == "Invalid template id."


def test_api_save_workflow_template_syncs_scheduled_step_to_scheduler_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Scheduled Sync",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/scheduled-sync",
            "notes": "sync-note",
            "steps": [
                {
                    "title": "Scheduled Step",
                    "action": "preflight_mf",
                    "trigger_kind": "scheduled",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert res.status_code == 200
    body = res.json()
    template = body.get("template") or {}
    template_id = str(template.get("id") or "")
    assert template_id

    scheduler_sync = body.get("scheduler_sync") or {}
    assert scheduler_sync.get("status") == "ok"
    assert str(scheduler_sync.get("reason") or "") in {"scheduled_synced", "scheduled_not_armed"}

    scheduler_res = client.get(f"/api/scheduler/state?template_id={template_id}")
    assert scheduler_res.status_code == 200
    scheduler_state = scheduler_res.json()
    assert scheduler_state["enabled"] is False
    assert scheduler_state["action_key"] == "preflight_mf"
    assert scheduler_state["year"] == 2026
    assert scheduler_state["month"] == 2
    assert scheduler_state["mfcloud_url"] == "https://example.com/scheduled-sync"
    assert scheduler_state["notes"] == "sync-note"


def test_api_save_workflow_template_disables_scheduler_when_step1_not_scheduled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Disable Scheduled",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/disable-scheduled",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "scheduled",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    created = create_res.json().get("template") or {}
    template_id = str(created.get("id") or "")
    assert template_id

    arm_res = client.post(
        f"/api/scheduler/state?template_id={template_id}",
        json={
            "enabled": True,
            "card_id": f"workflow-template:{template_id}",
            "action_key": "preflight",
            "year": 2026,
            "month": 2,
            "run_date": "2099-02-01",
            "run_time": "09:00",
            "catch_up_policy": "run_on_startup",
            "recurrence": "once",
        },
    )
    assert arm_res.status_code == 200
    assert arm_res.json()["enabled"] is True

    edit_res = client.post(
        "/api/workflow-templates",
        json={
            "template_id": template_id,
            "template_mode": "edit",
            "base_updated_at": str(created.get("updated_at") or ""),
            "name": "Disable Scheduled",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/disable-scheduled",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "manual_start",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert edit_res.status_code == 200
    scheduler_sync = edit_res.json().get("scheduler_sync") or {}
    assert scheduler_sync.get("status") == "ok"
    assert scheduler_sync.get("reason") == "trigger_not_scheduled"

    scheduler_res = client.get(f"/api/scheduler/state?template_id={template_id}")
    assert scheduler_res.status_code == 200
    assert scheduler_res.json()["enabled"] is False


def test_api_save_workflow_template_disables_scheduler_for_unsupported_scheduled_action(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Unsupported Scheduled Action",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/unsupported",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "provider_ingest",
                    "trigger_kind": "scheduled",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert res.status_code == 200
    body = res.json()
    template = body.get("template") or {}
    template_id = str(template.get("id") or "")
    assert template_id

    scheduler_sync = body.get("scheduler_sync") or {}
    assert scheduler_sync.get("status") == "ok"
    assert scheduler_sync.get("reason") == "unsupported_action"

    scheduler_res = client.get(f"/api/scheduler/state?template_id={template_id}")
    assert scheduler_res.status_code == 200
    assert scheduler_res.json()["enabled"] is False


def test_api_workflow_events_triggers_run_for_external_event_template(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_calls: list[dict[str, Any]] = []

    def _fake_start_run(payload: dict[str, Any]) -> dict[str, Any]:
        run_calls.append(dict(payload))
        return {"status": "started", "run_id": "run_external_evt_001"}

    monkeypatch.setattr(public_core, "_start_run", _fake_start_run)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    event_res = client.post(
        "/api/workflow-events",
        json={
            "template_id": template_id,
            "event_id": "evt_external_001",
            "source": "test-suite",
        },
    )
    assert event_res.status_code == 200
    body = event_res.json()
    assert body["status"] == "ok"
    assert body["duplicate"] is False
    assert body["triggered"] is True
    assert body["run_id"] == "run_external_evt_001"
    assert body["template_id"] == template_id
    assert body["action_key"] == "preflight"

    assert len(run_calls) == 1
    assert run_calls[0]["mode"] == "preflight"
    assert run_calls[0]["year"] == 2026
    assert run_calls[0]["month"] == 2
    assert run_calls[0]["auth_handoff"] is False


def test_api_workflow_events_idempotency_returns_duplicate_without_rerun(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    run_count = 0

    def _fake_start_run(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal run_count
        run_count += 1
        return {"status": "started", "run_id": "run_external_evt_dedupe"}

    monkeypatch.setattr(public_core, "_start_run", _fake_start_run)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Dedupe Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-dedupe",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    payload = {
        "template_id": template_id,
        "idempotency_key": "evt-dedupe-001",
        "event_name": "preflight",
    }
    first_res = client.post("/api/workflow-events", json=payload)
    assert first_res.status_code == 200
    first_body = first_res.json()
    assert first_body["duplicate"] is False
    assert first_body["triggered"] is True

    second_res = client.post("/api/workflow-events", json=payload)
    assert second_res.status_code == 200
    second_body = second_res.json()
    assert second_body["duplicate"] is True
    assert second_body["triggered"] is False
    assert second_body["run_id"] == first_body["run_id"]
    assert run_count == 1


def test_api_workflow_events_rejects_template_without_external_event_trigger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "Manual Start Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/manual-start",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "manual_start",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    res = client.post("/api/workflow-events", json={"template_id": template_id})
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "trigger_kind=external_event" in detail


def test_api_workflow_events_validates_token_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setenv("AX_WORKFLOW_EVENT_TOKEN", "secret-workflow-token")

    def _fake_start_run(payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "started", "run_id": "run_external_evt_token"}

    monkeypatch.setattr(public_core, "_start_run", _fake_start_run)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Token Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-token",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    unauthorized_res = client.post("/api/workflow-events", json={"template_id": template_id})
    assert unauthorized_res.status_code == 401

    authorized_res = client.post(
        "/api/workflow-events",
        headers={"x-workflow-event-token": "secret-workflow-token"},
        json={"template_id": template_id, "event_id": "evt-token-001"},
    )
    assert authorized_res.status_code == 200
    body = authorized_res.json()
    assert body["status"] == "ok"
    assert body["triggered"] is True
    assert body["duplicate"] is False


def test_api_workflow_events_rejects_unsupported_action_for_mvp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Unsupported Action",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-unsupported",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "provider_ingest",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    res = client.post("/api/workflow-events", json={"template_id": template_id, "event_id": "evt-unsupported-001"})
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "external_event action is not executable in MVP" in detail


def test_api_workflow_events_rejects_invalid_year_month_after_template_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Invalid YM",
            "year": 0,
            "month": 0,
            "mfcloud_url": "https://example.com/external-invalid-ym",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    res = client.post("/api/workflow-events", json={"template_id": template_id, "event_id": "evt-invalid-ym-001"})
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "requires valid year/month" in detail


def test_api_workflow_events_event_name_route_rejects_not_matched(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Name Route",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-event-name",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200

    res = client.post("/api/workflow-events", json={"event_name": "amazon_download", "event_id": "evt-name-404"})
    assert res.status_code == 404
    detail = str(res.json().get("detail") or "")
    assert "matched event_name" in detail


def test_api_workflow_events_event_name_route_rejects_multiple_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    payload = {
        "year": 2026,
        "month": 2,
        "mfcloud_url": "https://example.com/external-event-duplicate-name",
        "steps": [
            {
                "title": "Step 1",
                "action": "preflight",
                "trigger_kind": "external_event",
                "execution_mode": "manual_confirm",
            }
        ],
    }
    first = client.post("/api/workflow-templates", json={"name": "External Event Name A", **payload})
    second = client.post("/api/workflow-templates", json={"name": "External Event Name B", **payload})
    assert first.status_code == 200
    assert second.status_code == 200

    res = client.post("/api/workflow-events", json={"event_name": "preflight", "event_id": "evt-name-409"})
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "Multiple templates matched event_name" in detail


def test_api_workflow_events_accepts_authorization_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setenv("AX_WORKFLOW_EVENT_TOKEN", "bearer-token-001")

    def _fake_start_run(payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "started", "run_id": "run_external_evt_bearer"}

    monkeypatch.setattr(public_core, "_start_run", _fake_start_run)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Bearer Token Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-bearer-token",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    unauthorized_res = client.post("/api/workflow-events", json={"template_id": template_id, "event_id": "evt-bearer-1"})
    assert unauthorized_res.status_code == 401

    authorized_res = client.post(
        "/api/workflow-events",
        headers={"Authorization": "Bearer bearer-token-001"},
        json={"template_id": template_id, "event_id": "evt-bearer-2"},
    )
    assert authorized_res.status_code == 200
    body = authorized_res.json()
    assert body["status"] == "ok"
    assert body["triggered"] is True
    assert body["duplicate"] is False


def test_api_workflow_events_receipt_ttl_expires_duplicate_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setenv("AX_WORKFLOW_EVENT_RECEIPT_TTL_DAYS", "1")
    run_count = 0

    def _fake_start_run(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal run_count
        run_count += 1
        return {"status": "started", "run_id": f"run_ttl_{run_count:03d}"}

    monkeypatch.setattr(public_core, "_start_run", _fake_start_run)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event TTL Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-ttl",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    idempotency_key = "evt-ttl-001"
    receipts_path = _artifact_root(tmp_path) / "_workflow_events" / "receipts.json"
    old_created_at = (datetime.now() - timedelta(days=5)).isoformat(timespec="seconds")
    _write_json(
        receipts_path,
        {
            "receipts": {
                f"{template_id}:{idempotency_key}": {
                    "template_id": template_id,
                    "template_name": "External Event TTL Template",
                    "action_key": "preflight",
                    "event_name": "preflight",
                    "source": "seed",
                    "idempotency_key": idempotency_key,
                    "run_id": "run_expired_001",
                    "created_at": old_created_at,
                }
            }
        },
    )

    res = client.post(
        "/api/workflow-events",
        json={"template_id": template_id, "idempotency_key": idempotency_key},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["duplicate"] is False
    assert body["triggered"] is True
    assert run_count == 1

    persisted = json.loads(receipts_path.read_text(encoding="utf-8"))
    receipts = persisted.get("receipts") or {}
    key = f"{template_id}:{idempotency_key}"
    assert key in receipts
    assert str((receipts.get(key) or {}).get("run_id") or "") == "run_ttl_001"
    assert str((receipts.get(key) or {}).get("created_at") or "") != old_created_at


def test_api_workflow_events_receipt_max_limit_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setenv("AX_WORKFLOW_EVENT_MAX_RECEIPTS", "2")
    monkeypatch.setenv("AX_WORKFLOW_EVENT_RECEIPT_TTL_DAYS", "3650")
    run_count = 0

    def _fake_start_run(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal run_count
        run_count += 1
        return {"status": "started", "run_id": f"run_max_{run_count:03d}"}

    monkeypatch.setattr(public_core, "_start_run", _fake_start_run)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Max Receipt Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-max",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    for idx in range(1, 4):
        res = client.post(
            "/api/workflow-events",
            json={"template_id": template_id, "idempotency_key": f"evt-max-{idx:03d}"},
        )
        assert res.status_code == 200
        assert res.json()["triggered"] is True
        assert res.json()["duplicate"] is False

    receipts_path = _artifact_root(tmp_path) / "_workflow_events" / "receipts.json"
    persisted = json.loads(receipts_path.read_text(encoding="utf-8"))
    receipts = persisted.get("receipts") or {}
    assert len(receipts) == 2
    assert f"{template_id}:evt-max-001" not in receipts


def test_api_workflow_events_auth_failure_writes_classified_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setenv("AX_WORKFLOW_EVENT_TOKEN", "required-token")

    res = client.post(
        "/api/workflow-events",
        json={"year": 2026, "month": 2, "event_name": "preflight"},
    )
    assert res.status_code == 401
    detail = str(res.json().get("detail") or "")
    assert "Invalid workflow event token" in detail

    entries = _read_audit_entries(tmp_path, "2026-02")
    workflow_entries = [row for row in entries if str(row.get("event_type") or "") == "workflow_event"]
    assert workflow_entries
    last = workflow_entries[-1]
    assert str(last.get("status") or "") == "rejected"
    details = last.get("details") or {}
    assert str(details.get("reason_class") or "") == "auth"
    assert str(details.get("reason_code") or "") == "http_401"
    assert str(details.get("retry_advice") or "") == "retry_after_fix"


def test_api_workflow_events_run_conflict_writes_classified_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)

    def _fake_start_run(payload: dict[str, Any]) -> dict[str, Any]:
        raise HTTPException(status_code=409, detail="Another run is already in progress.")

    monkeypatch.setattr(public_core, "_start_run", _fake_start_run)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Conflict Template",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-conflict",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    res = client.post("/api/workflow-events", json={"template_id": template_id, "event_id": "evt-conflict-001"})
    assert res.status_code == 409
    detail = str(res.json().get("detail") or "")
    assert "already in progress" in detail

    entries = _read_audit_entries(tmp_path, "2026-02")
    workflow_entries = [row for row in entries if str(row.get("event_type") or "") == "workflow_event"]
    assert workflow_entries
    last = workflow_entries[-1]
    assert str(last.get("status") or "") == "rejected"
    details = last.get("details") or {}
    assert str(details.get("reason_class") or "") == "run_conflict"
    assert str(details.get("reason_code") or "") == "http_409"
    assert str(details.get("retry_advice") or "") == "retry_with_backoff"

    retry_jobs = _read_workflow_event_retry_jobs(tmp_path)
    jobs = retry_jobs.get("jobs") if isinstance(retry_jobs.get("jobs"), dict) else {}
    key = f"{template_id}:evt-conflict-001"
    assert key in jobs
    queued = jobs.get(key) or {}
    assert str(queued.get("status") or "") == "pending"
    assert int(queued.get("attempts") or 0) == 0
    assert int(queued.get("max_attempts") or 0) >= 1


def test_api_workflow_event_retry_jobs_drain_succeeds_and_marks_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    call_count = 0

    def _fake_start_run(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise HTTPException(status_code=409, detail="Another run is already in progress.")
        return {"status": "started", "run_id": "run_retry_success_001"}

    monkeypatch.setattr(public_core, "_start_run", _fake_start_run)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Retry Drain Success",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-retry-drain-success",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    event_res = client.post(
        "/api/workflow-events",
        json={"template_id": template_id, "idempotency_key": "evt-retry-drain-001"},
    )
    assert event_res.status_code == 409

    queue_before = client.get("/api/workflow-events/retry-jobs")
    assert queue_before.status_code == 200
    before_body = queue_before.json()
    assert int(before_body.get("total") or 0) >= 1

    drain_res = client.post(
        "/api/workflow-events/retry-jobs/drain",
        json={"limit": 1, "force": True},
    )
    assert drain_res.status_code == 200
    drain_body = drain_res.json()
    assert drain_body.get("status") == "ok"
    assert drain_body.get("processed") == 1
    assert drain_body.get("succeeded") == 1
    assert drain_body.get("retrying") == 0
    assert drain_body.get("escalated") == 0

    retry_jobs = _read_workflow_event_retry_jobs(tmp_path)
    jobs = retry_jobs.get("jobs") if isinstance(retry_jobs.get("jobs"), dict) else {}
    key = f"{template_id}:evt-retry-drain-001"
    assert key in jobs
    job = jobs.get(key) or {}
    assert str(job.get("status") or "") == "succeeded"
    assert int(job.get("attempts") or 0) == 1
    assert str(job.get("last_run_id") or "") == "run_retry_success_001"

    duplicate_res = client.post(
        "/api/workflow-events",
        json={"template_id": template_id, "idempotency_key": "evt-retry-drain-001"},
    )
    assert duplicate_res.status_code == 200
    duplicate_body = duplicate_res.json()
    assert duplicate_body.get("duplicate") is True
    assert duplicate_body.get("triggered") is False
    assert duplicate_body.get("run_id") == "run_retry_success_001"


def test_api_workflow_event_retry_jobs_drain_escalates_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setenv("AX_WORKFLOW_EVENT_RETRY_MAX_ATTEMPTS", "2")
    monkeypatch.setenv(
        "AX_GOOGLE_CHAT_WEBHOOK_URL",
        "https://chat.googleapis.com/v1/spaces/test/messages?key=test&token=test",
    )
    notifications: list[dict[str, Any]] = []

    class _FakeWebhookResponse:
        status = 200

        def __enter__(self) -> "_FakeWebhookResponse":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

        def read(self) -> bytes:
            return b"{\"status\":\"ok\"}"

        def getcode(self) -> int:
            return 200

    def _fake_urlopen(req: Any, timeout: int = 0) -> _FakeWebhookResponse:
        payload_raw = req.data if isinstance(req.data, (bytes, bytearray)) else b"{}"
        payload = json.loads(payload_raw.decode("utf-8"))
        notifications.append(
            {
                "url": str(getattr(req, "full_url", "")).strip(),
                "timeout": int(timeout),
                "payload": payload if isinstance(payload, dict) else {},
            }
        )
        return _FakeWebhookResponse()

    def _fake_start_run(payload: dict[str, Any]) -> dict[str, Any]:
        raise HTTPException(status_code=409, detail="Another run is already in progress.")

    monkeypatch.setattr(public_core, "_start_run", _fake_start_run)
    monkeypatch.setattr(api_workspace_routes.url_request, "urlopen", _fake_urlopen)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Retry Escalation",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-retry-escalation",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    first_res = client.post(
        "/api/workflow-events",
        json={"template_id": template_id, "idempotency_key": "evt-retry-escalate-001"},
    )
    assert first_res.status_code == 409

    drain_retrying = client.post("/api/workflow-events/retry-jobs/drain", json={"force": True})
    assert drain_retrying.status_code == 200
    body_retrying = drain_retrying.json()
    assert body_retrying.get("processed") == 1
    assert body_retrying.get("retrying") == 1
    assert body_retrying.get("escalated") == 0

    drain_escalated = client.post("/api/workflow-events/retry-jobs/drain", json={"force": True})
    assert drain_escalated.status_code == 200
    body_escalated = drain_escalated.json()
    assert body_escalated.get("processed") == 1
    assert body_escalated.get("retrying") == 0
    assert body_escalated.get("escalated") == 1

    retry_jobs = _read_workflow_event_retry_jobs(tmp_path)
    jobs = retry_jobs.get("jobs") if isinstance(retry_jobs.get("jobs"), dict) else {}
    key = f"{template_id}:evt-retry-escalate-001"
    assert key in jobs
    job = jobs.get(key) or {}
    assert str(job.get("status") or "") == "escalated"
    assert int(job.get("attempts") or 0) == 2
    assert str(job.get("last_reason_code") or "") == "retry_exhausted"
    assert str(job.get("last_retry_advice") or "") == "retry_after_fix"
    assert len(notifications) == 1
    notify = notifications[0]
    assert "chat.googleapis.com" in str(notify.get("url") or "")
    assert int(notify.get("timeout") or 0) >= 1
    payload = notify.get("payload") if isinstance(notify.get("payload"), dict) else {}
    text = str(payload.get("text") or "")
    assert "[Workflow Retry Escalated]" in text
    assert "evt-retry-escalate-001" in text
    assert "attempts: 2/2" in text

    entries = _read_audit_entries(tmp_path, "2026-02")
    workflow_entries = [row for row in entries if str(row.get("event_type") or "") == "workflow_event"]
    assert workflow_entries
    last = workflow_entries[-1]
    details = last.get("details") or {}
    assert str(last.get("status") or "") == "failed"
    assert str(details.get("reason_code") or "") == "retry_exhausted"
    assert str(details.get("retry_advice") or "") == "retry_after_fix"
    notification_entries = [
        row for row in entries if str(row.get("event_type") or "") == "workflow_event_notification"
    ]
    assert notification_entries
    notification_last = notification_entries[-1]
    notification_details = notification_last.get("details") or {}
    assert str(notification_last.get("status") or "") == "success"
    assert str(notification_details.get("channel") or "") == "google_chat"
    assert str(notification_details.get("idempotency_key") or "") == "evt-retry-escalate-001"


def test_api_workflow_event_retry_jobs_drain_escalation_notification_failure_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    monkeypatch.setenv("AX_WORKFLOW_EVENT_RETRY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv(
        "AX_GOOGLE_CHAT_WEBHOOK_URL",
        "https://chat.googleapis.com/v1/spaces/test/messages?key=test&token=test",
    )

    def _fake_start_run(payload: dict[str, Any]) -> dict[str, Any]:
        raise HTTPException(status_code=409, detail="Another run is already in progress.")

    def _failing_urlopen(req: Any, timeout: int = 0) -> Any:
        raise RuntimeError("google chat unavailable")

    monkeypatch.setattr(public_core, "_start_run", _fake_start_run)
    monkeypatch.setattr(api_workspace_routes.url_request, "urlopen", _failing_urlopen)

    create_res = client.post(
        "/api/workflow-templates",
        json={
            "name": "External Event Retry Escalation Notification Failure",
            "year": 2026,
            "month": 2,
            "mfcloud_url": "https://example.com/external-retry-escalation-notify-fail",
            "steps": [
                {
                    "title": "Step 1",
                    "action": "preflight",
                    "trigger_kind": "external_event",
                    "execution_mode": "manual_confirm",
                }
            ],
        },
    )
    assert create_res.status_code == 200
    template_id = str((create_res.json().get("template") or {}).get("id") or "")
    assert template_id

    first_res = client.post(
        "/api/workflow-events",
        json={"template_id": template_id, "idempotency_key": "evt-retry-escalate-notify-fail-001"},
    )
    assert first_res.status_code == 409

    drain_res = client.post("/api/workflow-events/retry-jobs/drain", json={"force": True})
    assert drain_res.status_code == 200
    body = drain_res.json()
    assert body.get("processed") == 1
    assert body.get("retrying") == 0
    assert body.get("escalated") == 1

    retry_jobs = _read_workflow_event_retry_jobs(tmp_path)
    jobs = retry_jobs.get("jobs") if isinstance(retry_jobs.get("jobs"), dict) else {}
    key = f"{template_id}:evt-retry-escalate-notify-fail-001"
    assert key in jobs
    job = jobs.get(key) or {}
    assert str(job.get("status") or "") == "escalated"
    assert int(job.get("attempts") or 0) == 1

    entries = _read_audit_entries(tmp_path, "2026-02")
    workflow_entries = [row for row in entries if str(row.get("event_type") or "") == "workflow_event"]
    assert workflow_entries
    workflow_last = workflow_entries[-1]
    workflow_details = workflow_last.get("details") or {}
    assert str(workflow_last.get("status") or "") == "failed"
    assert str(workflow_details.get("reason_code") or "") == "retry_exhausted"

    notification_entries = [
        row for row in entries if str(row.get("event_type") or "") == "workflow_event_notification"
    ]
    assert notification_entries
    notification_last = notification_entries[-1]
    notification_details = notification_last.get("details") or {}
    assert str(notification_last.get("status") or "") == "failed"
    assert str(notification_details.get("channel") or "") == "google_chat"
    assert str(notification_details.get("idempotency_key") or "") == "evt-retry-escalate-notify-fail-001"
    assert "google chat unavailable" in str(notification_details.get("reason") or "")


def test_api_workflow_events_summary_returns_aggregated_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-02"
    reports = _reports_dir(tmp_path, ym)
    reports.mkdir(parents=True, exist_ok=True)
    audit_path = reports / "audit_log.jsonl"
    rows = [
        {
            "at": "2026-02-20T10:00:00",
            "event_type": "workflow_event",
            "action": "preflight",
            "status": "success",
            "run_id": "run_001",
            "details": {
                "template_id": "tpl_001",
                "template_name": "Template A",
                "event_name": "preflight",
                "source": "webhook",
                "idempotency_key": "evt-001",
                "duplicate": False,
            },
        },
        {
            "at": "2026-02-20T10:05:00",
            "event_type": "workflow_event",
            "action": "preflight",
            "status": "rejected",
            "details": {
                "template_id": "tpl_001",
                "event_name": "preflight",
                "source": "webhook",
                "idempotency_key": "evt-002",
                "reason_class": "auth",
                "reason_code": "http_401",
                "retry_advice": "retry_after_fix",
            },
        },
        {
            "at": "2026-02-20T10:06:00",
            "event_type": "workflow_event",
            "action": "preflight",
            "status": "skipped",
            "run_id": "run_001",
            "details": {
                "template_id": "tpl_001",
                "event_name": "preflight",
                "source": "webhook",
                "idempotency_key": "evt-001",
                "reason_class": "duplicate",
                "reason_code": "duplicate_idempotency_key",
                "retry_advice": "do_not_retry",
                "duplicate": True,
            },
        },
        {
            "at": "2026-02-20T10:07:00",
            "event_type": "workflow_event",
            "action": "preflight",
            "status": "failed",
            "details": {
                "template_id": "tpl_001",
                "event_name": "preflight",
                "source": "webhook",
                "idempotency_key": "evt-003",
                "reason_class": "infra",
                "reason_code": "exception",
                "retry_advice": "retry_with_backoff",
                "duplicate": False,
            },
        },
        {
            "at": "2026-02-20T10:07:30",
            "event_type": "workflow_event_notification",
            "action": "preflight",
            "status": "success",
            "details": {
                "template_id": "tpl_001",
                "template_name": "Template A",
                "event_name": "preflight",
                "source": "webhook:retry",
                "idempotency_key": "evt-003",
                "channel": "google_chat",
                "attempts": 3,
                "max_attempts": 3,
                "reason": "sent",
                "reason_code": "sent",
            },
        },
        {
            "at": "2026-02-20T10:07:40",
            "event_type": "workflow_event_notification",
            "action": "preflight",
            "status": "failed",
            "details": {
                "template_id": "tpl_002",
                "template_name": "Template B",
                "event_name": "preflight",
                "source": "webhook:retry",
                "idempotency_key": "evt-004",
                "channel": "google_chat",
                "attempts": 3,
                "max_attempts": 3,
                "reason": "network unavailable",
                "reason_code": "network_error",
            },
        },
        {
            "at": "2026-02-20T10:08:00",
            "event_type": "run",
            "action": "preflight",
            "status": "success",
            "details": {},
        },
    ]
    audit_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    res = client.get("/api/workflow-events/summary?ym=2026-02&recent_limit=2")
    assert res.status_code == 200
    body = res.json()

    assert body.get("status") == "ok"
    assert body.get("ym") == "2026-02"
    assert body.get("event_type") == "workflow_event"
    assert body.get("total") == 4
    assert body.get("first_at") == "2026-02-20T10:00:00"
    assert body.get("last_at") == "2026-02-20T10:07:00"

    by_status = body.get("by_status") or {}
    assert by_status.get("success") == 1
    assert by_status.get("skipped") == 1
    assert by_status.get("rejected") == 1
    assert by_status.get("failed") == 1
    assert by_status.get("unknown") == 0

    by_reason_class_rows = body.get("by_reason_class") if isinstance(body.get("by_reason_class"), list) else []
    by_reason_class = {str(item.get("reason_class") or ""): int(item.get("count") or 0) for item in by_reason_class_rows}
    assert by_reason_class.get("auth") == 1
    assert by_reason_class.get("duplicate") == 1
    assert by_reason_class.get("infra") == 1

    by_reason_code_rows = body.get("by_reason_code") if isinstance(body.get("by_reason_code"), list) else []
    by_reason_code = {str(item.get("reason_code") or ""): int(item.get("count") or 0) for item in by_reason_code_rows}
    assert by_reason_code.get("http_401") == 1
    assert by_reason_code.get("duplicate_idempotency_key") == 1
    assert by_reason_code.get("exception") == 1

    by_retry_advice_rows = body.get("by_retry_advice") if isinstance(body.get("by_retry_advice"), list) else []
    by_retry_advice = {
        str(item.get("retry_advice") or ""): int(item.get("count") or 0) for item in by_retry_advice_rows
    }
    assert by_retry_advice.get("retry_after_fix") == 1
    assert by_retry_advice.get("do_not_retry") == 1
    assert by_retry_advice.get("retry_with_backoff") == 1

    duplicate = body.get("duplicate") or {}
    assert duplicate.get("true") == 1
    assert duplicate.get("false") == 2
    assert duplicate.get("unknown") == 1

    recent = body.get("recent") if isinstance(body.get("recent"), list) else []
    assert len(recent) == 2
    assert str(recent[0].get("at") or "") == "2026-02-20T10:07:00"
    assert str(recent[1].get("at") or "") == "2026-02-20T10:06:00"

    receipt_retention = body.get("receipt_retention") or {}
    assert int(receipt_retention.get("ttl_days") or 0) >= 1
    assert int(receipt_retention.get("max_receipts") or 0) >= 1
    retry_queue = body.get("retry_queue") or {}
    assert int(retry_queue.get("total") or 0) >= 0
    assert int(retry_queue.get("due") or 0) >= 0
    assert isinstance(retry_queue.get("by_status"), list)
    assert isinstance(retry_queue.get("policy"), dict)
    notification = body.get("notification") or {}
    assert notification.get("event_type") == "workflow_event_notification"
    assert int(notification.get("total") or 0) == 2
    assert str(notification.get("first_at") or "") == "2026-02-20T10:07:30"
    assert str(notification.get("last_at") or "") == "2026-02-20T10:07:40"
    notification_status = notification.get("by_status") or {}
    assert int(notification_status.get("success") or 0) == 1
    assert int(notification_status.get("failed") or 0) == 1
    assert int(notification_status.get("skipped") or 0) == 0
    assert int(notification_status.get("unknown") or 0) == 0
    notification_reason_rows = (
        notification.get("by_reason_code") if isinstance(notification.get("by_reason_code"), list) else []
    )
    notification_reason = {str(item.get("reason_code") or ""): int(item.get("count") or 0) for item in notification_reason_rows}
    assert notification_reason.get("sent") == 1
    assert notification_reason.get("network_error") == 1
    notification_recent = notification.get("recent") if isinstance(notification.get("recent"), list) else []
    assert len(notification_recent) == 2
    assert str(notification_recent[0].get("at") or "") == "2026-02-20T10:07:40"
    assert str(notification_recent[1].get("at") or "") == "2026-02-20T10:07:30"


def test_api_workflow_events_summary_returns_empty_when_audit_not_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.get("/api/workflow-events/summary?ym=2026-02")
    assert res.status_code == 200
    body = res.json()

    assert body.get("status") == "ok"
    assert body.get("ym") == "2026-02"
    assert body.get("total") == 0
    assert body.get("first_at") == ""
    assert body.get("last_at") == ""
    assert body.get("recent") == []
    assert body.get("by_retry_advice") == []
    assert body.get("duplicate") == {"true": 0, "false": 0, "unknown": 0}
    retry_queue = body.get("retry_queue") or {}
    assert retry_queue.get("total") == 0
    assert retry_queue.get("due") == 0
    assert isinstance(retry_queue.get("by_status"), list)
    assert isinstance(retry_queue.get("policy"), dict)
    by_status = body.get("by_status") or {}
    assert by_status.get("success") == 0
    assert by_status.get("skipped") == 0
    assert by_status.get("rejected") == 0
    assert by_status.get("failed") == 0
    assert by_status.get("unknown") == 0
    notification = body.get("notification") or {}
    assert notification.get("event_type") == "workflow_event_notification"
    assert notification.get("total") == 0
    assert notification.get("first_at") == ""
    assert notification.get("last_at") == ""
    assert notification.get("by_reason_code") == []
    assert notification.get("recent") == []
    notification_status = notification.get("by_status") or {}
    assert notification_status.get("success") == 0
    assert notification_status.get("failed") == 0
    assert notification_status.get("skipped") == 0
    assert notification_status.get("unknown") == 0


def test_api_workflow_event_notification_settings_get_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.get("/api/workflow-events/notification-settings")
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"
    assert body.get("configured") is False
    assert body.get("source") == "none"
    assert body.get("webhook_url_masked") == ""
    assert body.get("updated_at") == ""


def test_api_workflow_event_notification_settings_get_env_masked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    webhook_url = "https://chat.googleapis.com/v1/spaces/AAAAAABBBBB/messages?key=KEYVALUE1234&token=TOKENVALUE9876"
    monkeypatch.setenv("AX_GOOGLE_CHAT_WEBHOOK_URL", webhook_url)
    client = _create_client(monkeypatch, tmp_path)
    res = client.get("/api/workflow-events/notification-settings")
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"
    assert body.get("configured") is True
    assert body.get("source") == "env"
    masked = str(body.get("webhook_url_masked") or "")
    assert "chat.googleapis.com" in masked
    assert "KEYVALUE1234" not in masked
    assert "TOKENVALUE9876" not in masked
    assert body.get("updated_at") == ""


def test_api_workflow_event_notification_settings_save_and_clear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    webhook_url = "https://chat.googleapis.com/v1/spaces/CCCCCCDDDD/messages?key=SAVEKEY1234&token=SAVETOKEN9999"

    save_res = client.post(
        "/api/workflow-events/notification-settings",
        json={"webhook_url": webhook_url},
    )
    assert save_res.status_code == 200
    save_body = save_res.json()
    assert save_body.get("status") == "ok"
    assert save_body.get("configured") is True
    assert save_body.get("source") == "file"
    assert str(save_body.get("updated_at") or "")
    assert "SAVEKEY1234" not in str(save_body.get("webhook_url_masked") or "")
    assert "SAVETOKEN9999" not in str(save_body.get("webhook_url_masked") or "")

    stored = _read_workflow_event_notification_settings(tmp_path)
    assert str(stored.get("webhook_url") or "") == webhook_url
    assert str(stored.get("updated_at") or "")

    clear_res = client.post(
        "/api/workflow-events/notification-settings",
        json={"webhook_url": ""},
    )
    assert clear_res.status_code == 200
    clear_body = clear_res.json()
    assert clear_body.get("status") == "ok"
    assert clear_body.get("configured") is False
    assert clear_body.get("source") == "none"
    assert clear_body.get("webhook_url_masked") == ""
    assert _workflow_event_notification_settings_store(tmp_path).exists() is False


def test_api_workflow_event_notification_settings_rejects_invalid_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/workflow-events/notification-settings",
        json={"webhook_url": "https://example.com/hook"},
    )
    assert res.status_code == 400
    detail = str(res.json().get("detail") or "")
    assert "Invalid webhook_url" in detail


def test_api_workflow_event_notification_settings_test_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "AX_GOOGLE_CHAT_WEBHOOK_URL",
        "https://chat.googleapis.com/v1/spaces/test/messages?key=testkey&token=testtoken",
    )

    class _FakeWebhookResponse:
        status = 200

        def __enter__(self) -> "_FakeWebhookResponse":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

        def read(self) -> bytes:
            return b"{\"status\":\"ok\"}"

        def getcode(self) -> int:
            return 200

    sent_payload: dict[str, Any] = {}

    def _fake_urlopen(req: Any, timeout: int = 0) -> _FakeWebhookResponse:
        payload_raw = req.data if isinstance(req.data, (bytes, bytearray)) else b"{}"
        payload = json.loads(payload_raw.decode("utf-8"))
        sent_payload["url"] = str(getattr(req, "full_url", "")).strip()
        sent_payload["payload"] = payload
        sent_payload["timeout"] = int(timeout)
        return _FakeWebhookResponse()

    monkeypatch.setattr(api_workspace_routes.url_request, "urlopen", _fake_urlopen)
    client = _create_client(monkeypatch, tmp_path)
    res = client.post("/api/workflow-events/notification-settings/test", json={})
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"
    assert body.get("sent") is True
    assert int(body.get("http_status") or 0) == 200
    assert "Test notification sent." in str(body.get("message") or "")
    assert "chat.googleapis.com" in str(sent_payload.get("url") or "")
    payload = sent_payload.get("payload") if isinstance(sent_payload.get("payload"), dict) else {}
    assert "[Workflow Notification Test]" in str(payload.get("text") or "")
    assert int(sent_payload.get("timeout") or 0) >= 1
    now = datetime.now()
    ym = f"{int(now.year):04d}-{int(now.month):02d}"
    entries = _read_audit_entries(tmp_path, ym)
    rows = [row for row in entries if str(row.get("event_type") or "") == "workflow_event_notification"]
    assert rows
    last = rows[-1]
    assert str(last.get("action") or "") == "notification_settings_test"
    assert str(last.get("status") or "") == "success"
    details = last.get("details") or {}
    assert str(details.get("event_name") or "") == "notification_settings_test"
    assert str(details.get("source") or "") == "admin_center"
    assert str(details.get("reason_code") or "") == "sent"


def test_api_workflow_event_notification_settings_test_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "AX_GOOGLE_CHAT_WEBHOOK_URL",
        "https://chat.googleapis.com/v1/spaces/test/messages?key=testkey&token=testtoken",
    )

    def _failing_urlopen(req: Any, timeout: int = 0) -> Any:
        raise RuntimeError("google chat test unavailable")

    monkeypatch.setattr(api_workspace_routes.url_request, "urlopen", _failing_urlopen)
    client = _create_client(monkeypatch, tmp_path)
    res = client.post("/api/workflow-events/notification-settings/test", json={})
    assert res.status_code == 502
    body = res.json()
    assert body.get("status") == "error"
    assert body.get("sent") is False
    assert int(body.get("http_status") or 0) == 0
    assert "google chat test unavailable" in str(body.get("message") or "")
    now = datetime.now()
    ym = f"{int(now.year):04d}-{int(now.month):02d}"
    entries = _read_audit_entries(tmp_path, ym)
    rows = [row for row in entries if str(row.get("event_type") or "") == "workflow_event_notification"]
    assert rows
    last = rows[-1]
    assert str(last.get("action") or "") == "notification_settings_test"
    assert str(last.get("status") or "") == "failed"
    details = last.get("details") or {}
    assert str(details.get("event_name") or "") == "notification_settings_test"
    assert str(details.get("source") or "") == "admin_center"
    assert str(details.get("reason_code") or "") == "network_error"
    assert "google chat test unavailable" in str(details.get("reason") or "")


def test_workflow_event_retry_worker_starts_and_invokes_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    done = threading.Event()

    def _callback() -> None:
        done.set()

    monkeypatch.setenv("AX_WORKFLOW_EVENT_RETRY_WORKER_ENABLED", "1")
    monkeypatch.setenv("AX_WORKFLOW_EVENT_RETRY_WORKER_POLL_SECONDS", "5")

    api_workspace_routes.stop_workflow_event_retry_worker()
    api_workspace_routes.set_workflow_event_retry_drain_callback(_callback)
    try:
        api_workspace_routes.start_workflow_event_retry_worker()
        assert done.wait(1.5) is True
    finally:
        api_workspace_routes.stop_workflow_event_retry_worker()
        api_workspace_routes.set_workflow_event_retry_drain_callback(None)


def test_api_document_freshness_filters_kil_and_classifies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    docs_root = tmp_path / "knowledge_docs"
    refs_root = tmp_path / "knowledge_refs"

    now = datetime.now()

    def _write_target(path: Path, *, days_ago: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test", encoding="utf-8")
        ts = (now - timedelta(days=days_ago)).timestamp()
        os.utime(path, (ts, ts))

    _write_target(docs_root / "fresh_guide.md", days_ago=5)
    _write_target(docs_root / "warning_guide.md", days_ago=45)
    _write_target(refs_root / "stale_guide.md", days_ago=95)
    _write_target(docs_root / "KIL_PLAN.md", days_ago=1)
    _write_target(refs_root / "AGENT_BRAIN.md", days_ago=1)

    monkeypatch.setenv(
        "AX_DOC_FRESHNESS_ROOTS",
        os.pathsep.join([str(docs_root), str(refs_root)]),
    )

    res = client.get("/api/errors/document-freshness?fresh_days=30&warning_days=60")
    assert res.status_code == 200
    body = res.json()
    summary = body.get("summary") or {}
    items = body.get("items") if isinstance(body.get("items"), list) else []
    by_name = {str(item.get("name") or ""): item for item in items}

    assert summary.get("total") == 3
    assert summary.get("stale") == 1
    assert summary.get("warning") == 1
    assert summary.get("fresh") == 1
    assert "KIL_PLAN.md" not in by_name
    assert "AGENT_BRAIN.md" not in by_name

    assert by_name["stale_guide.md"]["freshness"] == "stale"
    assert by_name["warning_guide.md"]["freshness"] == "warning"
    assert by_name["fresh_guide.md"]["freshness"] == "fresh"

    freshness_order = [str(item.get("freshness") or "") for item in items]
    assert freshness_order[0] == "stale"
    assert freshness_order[1] == "warning"
    assert freshness_order[2] == "fresh"


def test_api_document_freshness_respects_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    docs_root = tmp_path / "knowledge_docs"
    docs_root.mkdir(parents=True, exist_ok=True)

    for index in range(4):
        target = docs_root / f"doc_{index}.md"
        target.write_text("test", encoding="utf-8")
        ts = (datetime.now() - timedelta(days=(index + 1) * 10)).timestamp()
        os.utime(target, (ts, ts))

    monkeypatch.setenv("AX_DOC_FRESHNESS_ROOTS", str(docs_root))

    res = client.get("/api/errors/document-freshness?limit=2")
    assert res.status_code == 200
    body = res.json()
    summary = body.get("summary") or {}
    items = body.get("items") if isinstance(body.get("items"), list) else []

    assert summary.get("total") == 4
    assert summary.get("displayed") == 2
    assert summary.get("hidden") == 2
    assert len(items) == 2


def test_api_error_incidents_returns_degraded_payload_when_tool_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise_error_tool(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(api_routes, "_run_error_tool", _raise_error_tool)
    client = _create_client(monkeypatch, tmp_path)
    res = client.get("/api/errors/incidents")
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "degraded"
    assert body.get("inbox_count") == 0
    assert body.get("archive_resolved_count") == 0
    assert body.get("archive_escalated_count") == 0
    incidents = body.get("incidents")
    assert isinstance(incidents, list)
    assert incidents == []


def test_api_error_incident_detail_includes_handoff_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reports_root = tmp_path / "reports"
    incident_id = "incident_api_handoff_001"
    incident_dir = reports_root / "error_inbox" / incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)
    handoff_dir = reports_root / "error_handoffs" / incident_id
    handoff_dir.mkdir(parents=True, exist_ok=True)
    queue_path = tmp_path / "antigravity_queue" / f"{incident_id}.json"
    _write_json(
        incident_dir / "incident.json",
        {
            "incident_id": incident_id,
            "status": "handed_off",
            "step": "amazon_download",
            "failure_class": "run_failed",
            "ym": "2026-01",
            "handoff_path": str(handoff_dir / "handoff.json"),
            "handoff_queue_path": str(queue_path),
            "execution_owner": "antigravity",
        },
    )
    _write_json(
        handoff_dir / "handoff.json",
        {
            "status": "ok",
            "incident_id": incident_id,
            "handoff_status": "handed_off",
            "executor": "antigravity",
        },
    )

    def _fake_error_tool(script_name: str, args: list[str], *, timeout_seconds: int = 30) -> dict[str, Any]:
        _ = timeout_seconds
        assert script_name == "error_status.py"
        assert "--incident-id" in args
        return {
            "status": "ok",
            "incident_id": incident_id,
            "incident": {
                "incident_id": incident_id,
                "status": "handed_off",
                "path": str(incident_dir),
                "ym": "2026-01",
            },
        }

    monkeypatch.setattr(api_routes, "_run_error_tool", _fake_error_tool)
    monkeypatch.setattr(api_routes, "_error_reports_root", lambda: reports_root)
    client = _create_client(monkeypatch, tmp_path)

    res = client.get(f"/api/errors/incidents/{incident_id}")
    assert res.status_code == 200
    body = res.json()
    handoff = body.get("handoff") if isinstance(body.get("handoff"), dict) else {}
    assert handoff.get("incident_id") == incident_id
    handoff_json_path = str(body.get("handoff_json_path") or "").replace("\\", "/")
    assert handoff_json_path.endswith(f"error_handoffs/{incident_id}/handoff.json")
    incident = body.get("incident") if isinstance(body.get("incident"), dict) else {}
    assert str(incident.get("handoff_path") or "").replace("\\", "/").endswith(
        f"error_handoffs/{incident_id}/handoff.json"
    )
    assert str(incident.get("handoff_queue_path") or "").replace("\\", "/").endswith(
        f"antigravity_queue/{incident_id}.json"
    )


def test_api_error_incident_approve_updates_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reports_root = tmp_path / "reports"
    incident_id = "incident_api_approve_001"
    incident_dir = reports_root / "error_inbox" / incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        incident_dir / "incident.json",
        {
            "incident_id": incident_id,
            "status": "plan_proposed",
            "year": 2026,
            "month": 1,
            "ym": "2026-01",
            "step": "amazon_download",
            "failure_class": "run_failed",
            "message": "test",
        },
    )
    (incident_dir / "status.txt").write_text("plan_proposed\n", encoding="utf-8")
    plan_json = reports_root / "error_plans" / incident_id / "plan.json"
    _write_json(plan_json, {"incident_id": incident_id, "summary": "test"})

    monkeypatch.setattr(api_routes, "_error_reports_root", lambda: reports_root)
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(f"/api/errors/incidents/{incident_id}/approve", json={})
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"
    assert body.get("incident_status") == "approved"

    saved = json.loads((incident_dir / "incident.json").read_text(encoding="utf-8"))
    assert saved.get("status") == "approved"
    assert saved.get("plan_state") == "approved"
    assert saved.get("execution_owner") == "antigravity"
    assert (incident_dir / "status.txt").read_text(encoding="utf-8").strip() == "approved"


def test_api_error_incident_handoff_invokes_handoff_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called: dict[str, Any] = {}

    def _fake_error_tool(script_name: str, args: list[str], *, timeout_seconds: int = 30) -> dict[str, Any]:
        called["script_name"] = script_name
        called["args"] = list(args)
        called["timeout_seconds"] = timeout_seconds
        return {
            "status": "ok",
            "incident_id": "incident_api_handoff_002",
            "handoff_status": "handed_off",
            "handoff_json": "C:/tmp/handoff.json",
            "queue_payload": "C:/tmp/queue/incident_api_handoff_002.json",
            "year": 2026,
            "month": 1,
        }

    monkeypatch.setattr(api_routes, "_run_error_tool", _fake_error_tool)
    client = _create_client(monkeypatch, tmp_path)
    res = client.post(
        "/api/errors/incidents/incident_api_handoff_002/handoff",
        json={"queue_dir": "C:/tmp/queue", "allow_unapproved": True},
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("handoff_status") == "handed_off"
    assert called.get("script_name") == "error_handoff_prepare.py"
    args = called.get("args") if isinstance(called.get("args"), list) else []
    assert "--incident-id" in args
    assert "incident_api_handoff_002" in args
    assert "--queue-dir" in args
    assert "C:/tmp/queue" in args
    assert "--allow-unapproved" in args


def test_api_error_incident_lifecycle_plan_approve_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reports_root = tmp_path / "reports"
    incident_id = "incident_api_lifecycle_001"
    incident_dir = reports_root / "error_inbox" / incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        incident_dir / "incident.json",
        {
            "incident_id": incident_id,
            "status": "new",
            "created_at": "2026-02-20T00:00:00+00:00",
            "updated_at": "2026-02-20T00:00:00+00:00",
            "run_id": "run_lifecycle_001",
            "year": 2026,
            "month": 1,
            "ym": "2026-01",
            "step": "amazon_download",
            "failure_class": "run_failed",
            "message": "timeout while fetching receipt",
            "error_signature": "run_failed | amazon_download | timeout while fetching receipt",
        },
    )
    (incident_dir / "status.txt").write_text("new\n", encoding="utf-8")
    (incident_dir / "log_tail.txt").write_text("TimeoutError: download timed out\n", encoding="utf-8")
    (incident_dir / "audit_tail.jsonl").write_text("", encoding="utf-8")
    _write_json(incident_dir / "context.json", {"hint": "integration-test"})

    def _run_error_tool_with_temp_root(
        script_name: str,
        args: list[str],
        *,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        script_path = api_routes.core.SKILL_ROOT / "scripts" / script_name
        cmd = [sys.executable, str(script_path), "--root", str(reports_root), *args]
        result = subprocess.run(
            cmd,
            cwd=str(api_routes.core.SKILL_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1, int(timeout_seconds)),
        )
        assert result.returncode == 0, f"{script_name} failed: {result.stderr or result.stdout}"
        payload = json.loads(result.stdout or "{}")
        assert isinstance(payload, dict)
        return payload

    monkeypatch.setattr(api_routes, "_run_error_tool", _run_error_tool_with_temp_root)
    monkeypatch.setattr(api_routes, "_error_reports_root", lambda: reports_root)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("KIL_GEMINI_API_KEY", raising=False)

    client = _create_client(monkeypatch, tmp_path)

    res_plan = client.post(f"/api/errors/incidents/{incident_id}/plan", json={})
    assert res_plan.status_code == 200
    plan_body = res_plan.json()
    assert plan_body.get("status") == "ok"
    assert plan_body.get("plan_state") == "plan_proposed"
    assert Path(str(plan_body.get("plan_json") or "")).exists()

    incident_after_plan = json.loads((incident_dir / "incident.json").read_text(encoding="utf-8"))
    assert incident_after_plan.get("status") == "plan_proposed"
    assert (incident_dir / "status.txt").read_text(encoding="utf-8").strip() == "plan_proposed"

    res_approve = client.post(f"/api/errors/incidents/{incident_id}/approve", json={})
    assert res_approve.status_code == 200
    approve_body = res_approve.json()
    assert approve_body.get("incident_status") == "approved"

    queue_dir = tmp_path / "antigravity_queue"
    res_handoff = client.post(
        f"/api/errors/incidents/{incident_id}/handoff",
        json={"queue_dir": str(queue_dir)},
    )
    assert res_handoff.status_code == 200
    handoff_body = res_handoff.json()
    assert handoff_body.get("handoff_status") == "handed_off"
    assert Path(str(handoff_body.get("handoff_json") or "")).exists()
    assert Path(str(handoff_body.get("queue_payload") or "")).exists()
    assert (queue_dir / f"{incident_id}.json").exists()

    incident_after_handoff = json.loads((incident_dir / "incident.json").read_text(encoding="utf-8"))
    assert incident_after_handoff.get("status") == "handed_off"
    assert incident_after_handoff.get("execution_owner") == "antigravity"
    assert (incident_dir / "status.txt").read_text(encoding="utf-8").strip() == "handed_off"

    res_detail = client.get(f"/api/errors/incidents/{incident_id}")
    assert res_detail.status_code == 200
    detail_body = res_detail.json()
    assert detail_body.get("handoff", {}).get("handoff_status") == "handed_off"
    assert detail_body.get("plan", {}).get("incident_id") == incident_id
    incident_detail = detail_body.get("incident") if isinstance(detail_body.get("incident"), dict) else {}
    assert str(incident_detail.get("handoff_path") or "").endswith("handoff.json")
    assert str(incident_detail.get("handoff_queue_path") or "").endswith(f"{incident_id}.json")


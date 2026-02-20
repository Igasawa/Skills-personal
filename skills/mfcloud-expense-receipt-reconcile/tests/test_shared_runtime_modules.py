from __future__ import annotations

import json
import sys
from pathlib import Path
import re

from fastapi import APIRouter
from fastapi.testclient import TestClient
import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_LIB = REPO_ROOT / "scripts" / "lib"
SKILL_ROOT = REPO_ROOT / "skills" / "mfcloud-expense-receipt-reconcile"
if str(SHARED_LIB) not in sys.path:
    sys.path.insert(0, str(SHARED_LIB))
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from dashboard_app_factory import create_dashboard_app
import common


def test_common_paths_are_resolved_via_shared_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    assert common.ax_home() == tmp_path
    assert common.artifact_root() == tmp_path / "artifacts" / "mfcloud-expense-receipt-reconcile"
    assert common.runs_root() == tmp_path / "artifacts" / "mfcloud-expense-receipt-reconcile" / "_runs"
    assert common.default_storage_state("amazon") == tmp_path / "sessions" / "amazon.storage.json"


def test_common_ax_home_rejects_repo_subpath(monkeypatch) -> None:
    monkeypatch.delenv("AX_ALLOW_UNSAFE_AX_HOME", raising=False)
    monkeypatch.setenv("AX_HOME", str(REPO_ROOT / ".ax-unsafe"))
    with pytest.raises(ValueError, match="AX_HOME safety guard"):
        common.ax_home()


def test_common_ax_home_allows_repo_subpath_with_override(monkeypatch) -> None:
    monkeypatch.setenv("AX_ALLOW_UNSAFE_AX_HOME", "1")
    monkeypatch.setenv("AX_HOME", str(REPO_ROOT / ".ax-unsafe"))
    assert common.ax_home() == REPO_ROOT / ".ax-unsafe"


def test_dashboard_app_factory_mounts_and_calls_stop_worker(tmp_path: Path) -> None:
    base = tmp_path / "dashboard"
    (base / "static").mkdir(parents=True)
    (base / "templates").mkdir(parents=True)

    calls: list[str] = []

    def _create_pages_router(_templates) -> APIRouter:
        router = APIRouter()

        @router.get("/ping")
        def _ping() -> dict[str, bool]:
            return {"ok": True}

        return router

    def _create_api_router() -> APIRouter:
        router = APIRouter()

        @router.get("/api/ping")
        def _api_ping() -> dict[str, bool]:
            return {"ok": True}

        return router

    app = create_dashboard_app(
        base_dir=base,
        create_pages_router=_create_pages_router,
        create_api_router=_create_api_router,
        stop_worker=lambda: calls.append("called"),
    )

    with TestClient(app) as client:
        assert client.get("/ping").status_code == 200
        assert client.get("/api/ping").status_code == 200

    assert len(calls) == 2


def test_common_workflow_template_store_helpers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    rows = [
        {"id": "tmpl-b", "name": "Beta", "year": 2026, "month": 2, "updated_at": "2026-02-02T09:00:00"},
        {"id": "tmpl-a", "name": "Alpha", "year": 2026, "month": 1, "updated_at": "2026-02-01T09:00:00"},
    ]

    common.write_workflow_templates_raw(rows)
    store = common.workflow_templates_path()
    assert store == tmp_path / "artifacts" / "mfcloud-expense-receipt-reconcile" / "_workflow_templates" / "workflow_templates.json"

    loaded = common.read_workflow_templates_raw()
    assert loaded == rows

    by_name = common.sort_workflow_templates_rows(
        loaded,
        sort="name_asc",
        allowed_sorts={"name_asc", "updated_desc"},
    )
    assert [str(row.get("id") or "") for row in by_name] == ["tmpl-a", "tmpl-b"]

    fallback_sorted = common.sort_workflow_templates_rows(
        loaded,
        sort="unknown",
        allowed_sorts={"year_desc"},
        default_sort="year_desc",
    )
    assert [str(row.get("id") or "") for row in fallback_sorted] == ["tmpl-b", "tmpl-a"]


def test_common_run_registry_helpers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    runs = tmp_path / "artifacts" / "mfcloud-expense-receipt-reconcile" / "_runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "run_older.json").write_text(
        json.dumps(
            {
                "status": "running",
                "started_at": "2026-02-20T09:00:00",
                "params": {"year": 2026, "month": 1, "mode": "preflight"},
            }
        ),
        encoding="utf-8",
    )
    (runs / "run_newer.json").write_text(
        json.dumps(
            {
                "status": "running",
                "started_at": "2026-02-20T10:00:00",
                "params": {"year": 2026, "month": 1, "mode": "amazon_download"},
            }
        ),
        encoding="utf-8",
    )
    jobs = common.list_run_jobs()
    assert len(jobs) == 2
    assert str(jobs[0].get("params", {}).get("mode") or "") == "amazon_download"
    assert common.running_job_exists(jobs) is True
    latest = common.latest_running_job(jobs)
    assert isinstance(latest, dict)
    assert str(latest.get("params", {}).get("mode") or "") == "amazon_download"
    assert common.running_mode_for_ym(2026, 1) == "amazon_download"

    audit_path = tmp_path / "artifacts" / "mfcloud-expense-receipt-reconcile" / "2026-01" / "reports" / "audit_log.jsonl"
    common.append_audit_event_to_jsonl(
        path=audit_path,
        year=2026,
        month=1,
        event_type="run",
        action="preflight",
        status="success",
        actor={"channel": "dashboard", "id": "tester"},
        mode="preflight",
        run_id="run_20260220_100000",
        details={"sample": True},
    )
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["actor"]["id"] == "tester"
    assert rows[0]["action"] == "preflight"

    assert common.safe_int_optional("12") == 12
    assert common.safe_int_optional("x") is None
    assert common.coerce_non_negative_int("-5", default=7) == 7
    assert common.coerce_non_negative_int("3", default=0) == 3


def test_common_archive_helpers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    ym = "2026-01"
    audit_path = tmp_path / "artifacts" / "mfcloud-expense-receipt-reconcile" / ym / "reports" / "audit_log.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            {
                "ts": "2026-02-20T10:10:10",
                "ym": ym,
                "event_type": "archive",
                "action": "manual_archive",
                "status": "success",
                "details": {"archived_to": "C:\\archive\\20260220_101010"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    history = common.scan_archive_history(
        ym_matcher=lambda name: bool(re.match(r"^\d{4}-\d{2}$", str(name))),
        archive_action_label=lambda action: f"label:{action}",
        limit=10,
    )
    assert len(history) == 1
    assert history[0]["action"] == "manual_archive"
    assert history[0]["action_label"] == "label:manual_archive"

    archive_pdf = (
        tmp_path
        / "artifacts"
        / "mfcloud-expense-receipt-reconcile"
        / ym
        / "archive"
        / "20260220_101010"
        / "amazon"
        / "pdfs"
        / "A-1.pdf"
    )
    archive_pdf.parent.mkdir(parents=True, exist_ok=True)
    archive_pdf.write_bytes(b"%PDF-1.4\n")
    archived = common.scan_archived_receipts(
        tmp_path / "artifacts" / "mfcloud-expense-receipt-reconcile" / ym,
        source_labels={"amazon": "Amazon", "rakuten": "Rakuten"},
    )
    assert archived["snapshot_count"] == 1
    assert archived["receipt_count"] == 1

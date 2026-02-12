from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
import pytest

from dashboard.routes.pages import create_pages_router


def _artifact_root(ax_home: Path) -> Path:
    return ax_home / "artifacts" / "mfcloud-expense-receipt-reconcile"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _create_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    app = FastAPI()
    templates = Jinja2Templates(
        directory=str(Path(__file__).resolve().parents[1] / "dashboard" / "templates")
    )
    app.include_router(create_pages_router(templates))
    return TestClient(app)


def test_run_page_shows_pdf_preview_link_in_exclusion_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    run_root = _artifact_root(tmp_path) / ym
    pdf_path = run_root / "amazon" / "pdfs" / "AMZ-001.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")
    _write_jsonl(
        run_root / "amazon" / "orders.jsonl",
        [{"order_id": "AMZ-001", "order_date": "2026-01-12", "status": "ok", "pdf_path": str(pdf_path)}],
    )

    res = client.get(f"/runs/{ym}")
    assert res.status_code == 200
    assert f"/files/{ym}/pdf/amazon/AMZ-001.pdf" in res.text
    assert 'target="_blank"' in res.text


def test_excluded_pdfs_page_supports_month_switch_and_sort_controls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    run_root = _artifact_root(tmp_path) / ym
    pdf_path = run_root / "amazon" / "pdfs" / "AMZ-EX-1.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")
    _write_jsonl(
        run_root / "amazon" / "orders.jsonl",
        [
            {
                "order_id": "AMZ-EX-1",
                "order_date": "2026-01-12",
                "status": "ok",
                "include": False,
                "total_yen": 1200,
                "pdf_path": str(pdf_path),
            }
        ],
    )
    (_artifact_root(tmp_path) / "2026-02" / "reports").mkdir(parents=True, exist_ok=True)

    res = client.get(f"/runs/{ym}/excluded-pdfs")
    assert res.status_code == 200
    assert 'id="filter-month"' in res.text
    assert '<option value="2026-01" selected' in res.text
    assert '<option value="2026-02"' in res.text
    assert 'id="sort-order"' in res.text
    assert 'id="excluded-table-body"' in res.text
    assert 'data-order-date="2026-01-12"' in res.text
    assert 'data-order-month="2026-01"' in res.text


def test_index_page_shows_manual_archive_button(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.get("/")
    assert res.status_code == 200
    assert 'data-workspace-link' in res.text
    assert 'href="/workspace"' in res.text
    assert 'data-task-id="amazon"' in res.text
    assert 'data-task-status="amazon"' in res.text
    assert 'data-step-action="amazon_download"' in res.text
    assert 'data-step-link="amazon_exclude"' in res.text
    assert 'data-step-reset="amazon_download"' in res.text
    assert 'data-step-reset="amazon_decide_print"' in res.text
    assert 'data-step-status="amazon_download"' in res.text
    assert 'data-step-status="amazon_decide_print"' in res.text
    assert 'data-task-id="rakuten"' in res.text
    assert 'data-task-status="rakuten"' in res.text
    assert 'data-step-action="rakuten_download"' in res.text
    assert 'data-step-link="rakuten_exclude"' in res.text
    assert 'data-step-reset="rakuten_download"' in res.text
    assert 'data-step-reset="rakuten_decide_print"' in res.text
    assert 'data-step-status="rakuten_download"' in res.text
    assert 'data-step-status="rakuten_decide_print"' in res.text
    assert 'data-step-id="preflight"' in res.text
    assert 'data-step-id="provider_ingest"' in res.text
    assert 'data-step-id="mf_reconcile"' in res.text
    assert 'data-archive-action="archive_outputs"' in res.text
    assert 'data-archive-action="month_close"' in res.text
    assert "data-archive-page-link" not in res.text
    assert "data-archive-href-template=" in res.text
    assert "data-fallback-href=" not in res.text
    assert 'data-manual-action="open_inbox"' not in res.text
    assert 'data-manual-action="import_receipts"' not in res.text
    assert 'data-step-id="mf_bulk_upload_task"' in res.text
    assert 'data-step-status="mf_bulk_upload_task"' in res.text
    assert 'data-manual-action="open_mf_bulk_inbox"' in res.text
    assert 'data-manual-action="run_mf_bulk_upload"' in res.text
    assert 'data-manual-action="open_mf_csv_inbox"' in res.text
    assert 'data-manual-action="run_mf_csv_import"' in res.text
    assert 'data-provider-action="open_shared_inbox"' in res.text
    assert 'data-provider-action="import_provider_receipts"' in res.text
    assert 'data-provider-action="print_provider_receipts"' in res.text
    assert 'data-provider-action="download_provider_receipts"' not in res.text
    assert "/workspace" in res.text
    assert "data-mf-summary" not in res.text


def test_index_page_shows_archive_history_links(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    audit_log = _artifact_root(tmp_path) / ym / "reports" / "audit_log.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    audit_log.write_text(
        json.dumps(
            {
                "ts": "2026-02-10T09:10:11",
                "ym": ym,
                "event_type": "archive",
                "action": "month_close",
                "status": "success",
                "details": {"archived_to": "C:\\archive\\20260210_091011"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    res = client.get("/status")
    assert res.status_code == 200
    assert 'class="archive-history"' in res.text
    assert 'data-archive-history-list' in res.text
    assert f"/runs/{ym}/archived-receipts" in res.text


def test_index_page_exposes_latest_run_status_hooks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    runs_root = _artifact_root(tmp_path) / "_runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    run_id = "run_20260208_173457_465605"
    (runs_root / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "failed",
                "started_at": "2026-02-08T17:34:57",
                "params": {"year": 2026, "month": 1, "mode": "rakuten_download"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    res = client.get("/status")
    assert res.status_code == 200
    assert "data-latest-run-dot" in res.text
    assert "data-latest-run-status" in res.text
    assert "data-latest-run-time" in res.text
    assert "data-latest-run-id" in res.text
    assert "data-latest-run-ym" in res.text
    assert "data-log-run-id" in res.text
    assert "data-log-run-status" in res.text


def test_workspace_page_shows_core_link_and_prompt_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    res = client.get("/workspace")
    assert res.status_code == 200
    assert "エージェント作業スペース" in res.text
    assert "https://expense.moneyforward.com/expense_reports" in res.text
    assert 'data-prompt-key="mf_expense_reports"' in res.text
    assert "workspace-edit-prompt" in res.text
    assert 'id="workspace-link-form"' in res.text
    assert 'id="workspace-custom-links"' in res.text
    assert 'id="workspace-prompt-editor"' in res.text
    assert 'id="workspace-save-prompt"' in res.text
    assert "data-prompt-front" in res.text
    assert "data-workspace-link-note" in res.text
    assert "data-workspace-link-details" in res.text
    assert 'id="workspace-prompt-active-label"' in res.text
    assert "/static/js/workspace.js" in res.text


def test_run_page_shows_detail_shortcut_when_pdf_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    run_root = _artifact_root(tmp_path) / ym
    _write_jsonl(
        run_root / "rakuten" / "orders.jsonl",
        [
            {
                "order_id": "RAK-001",
                "order_date": "2026-01-20",
                "status": "error",
                "pdf_path": None,
                "detail_url": "https://order.my.rakuten.co.jp/purchase-history/?order_number=RAK-001",
            }
        ],
    )

    res = client.get(f"/runs/{ym}")
    assert res.status_code == 200
    assert "https://order.my.rakuten.co.jp/purchase-history/?order_number=RAK-001" in res.text


def test_run_page_shows_manual_print_prepare_and_complete_controls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    run_root = _artifact_root(tmp_path) / ym
    _write_jsonl(
        run_root / "amazon" / "orders.jsonl",
        [{"order_id": "AMZ-001", "order_date": "2026-01-12", "status": "ok"}],
    )
    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "print_all.ps1").write_text("Write-Host 'print'\n", encoding="utf-8")
    (reports_dir / "print_manifest.amazon.json").write_text('{"count":1}', encoding="utf-8")
    (reports_dir / "print_manifest.rakuten.json").write_text('{"count":1}', encoding="utf-8")
    (reports_dir / "workflow.json").write_text(
        json.dumps(
            {
                "amazon": {"print_prepared_at": "2026-02-09T10:00:00"},
                "rakuten": {"print_prepared_at": "2026-02-09T10:01:00"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    res = client.get(f"/runs/{ym}")
    assert res.status_code == 200
    assert f"/runs/{ym}/archived-receipts" in res.text
    assert 'class="primary exclude-save"' in res.text
    assert 'class="secondary print-complete"' in res.text
    assert 'id="print-next-box"' in res.text
    assert f'id="open-receipts-folder" data-ym="{ym}"' in res.text
    assert res.text.count('data-print-ready="1"') == 2
    assert 'class="primary run-print-script"' not in res.text
    assert 'id="run-print-script" data-ym' not in res.text


def test_run_page_shows_mf_draft_actions_download_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    run_root = _artifact_root(tmp_path) / ym
    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "mf_draft_create_actions.jsonl").write_text(
        '{"ts":"2026-02-11T10:00:00","action":"target_created","mf_expense_id":"MF-1"}\n',
        encoding="utf-8",
    )

    res = client.get(f"/runs/{ym}")
    assert res.status_code == 200
    assert f"/files/{ym}/mf_draft_actions" in res.text

    dl = client.get(f"/files/{ym}/mf_draft_actions")
    assert dl.status_code == 200


def test_archive_receipts_page_lists_archived_pdfs_with_month_switch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    run_root = _artifact_root(tmp_path) / ym
    archived_pdf = run_root / "archive" / "20260209_101530" / "amazon" / "pdfs" / "AMZ-ARC-001.pdf"
    archived_pdf.parent.mkdir(parents=True, exist_ok=True)
    archived_pdf.write_bytes(b"%PDF-1.4\n")
    (_artifact_root(tmp_path) / "2026-02" / "reports").mkdir(parents=True, exist_ok=True)

    res = client.get(f"/runs/{ym}/archived-receipts")
    assert res.status_code == 200
    assert 'id="archive-search"' in res.text
    assert "AMZ-ARC-001.pdf" in res.text
    assert f"/files/{ym}/archive/20260209_101530/amazon/AMZ-ARC-001.pdf" in res.text
    assert 'id="filter-month"' in res.text
    assert '<option value="2026-01" selected' in res.text
    assert '<option value="2026-02"' in res.text


def test_archive_receipts_legacy_route_redirects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    (_artifact_root(tmp_path) / ym / "reports").mkdir(parents=True, exist_ok=True)

    res = client.get(f"/runs/{ym}/archive-receipts", follow_redirects=False)
    assert res.status_code in {307, 308}
    assert res.headers.get("location", "").endswith(f"/runs/{ym}/archived-receipts")


def test_download_archived_pdf_route_returns_pdf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _create_client(monkeypatch, tmp_path)
    ym = "2026-01"
    run_root = _artifact_root(tmp_path) / ym
    archived_pdf = run_root / "archive" / "20260209_101530" / "rakuten" / "pdfs" / "RAK-ARC-001.pdf"
    archived_pdf.parent.mkdir(parents=True, exist_ok=True)
    archived_pdf.write_bytes(b"%PDF-1.4\n")

    res = client.get(f"/files/{ym}/archive/20260209_101530/rakuten/RAK-ARC-001.pdf")
    assert res.status_code == 200
    assert res.headers.get("content-type", "").startswith("application/pdf")

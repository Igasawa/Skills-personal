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
    assert f'/files/{ym}/pdf/amazon/AMZ-001.pdf' in res.text
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
    assert "アーカイブ作成（成果物+PDF）" in res.text
    assert 'data-archive-action="archive_outputs"' in res.text
    assert "data-mf-summary" in res.text


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

    res = client.get("/")
    assert res.status_code == 200
    assert "data-latest-run-dot" in res.text
    assert "data-latest-run-status" in res.text
    assert "data-latest-run-time" in res.text
    assert "data-latest-run-id" in res.text
    assert "data-latest-run-ym" in res.text
    assert "data-log-run-id" in res.text
    assert "data-log-run-status" in res.text


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
    assert "注文詳細" in res.text
    assert "未保存（Webあり）" in res.text
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

    res = client.get(f"/runs/{ym}")
    assert res.status_code == 200
    assert "Amazonで保存して印刷準備" in res.text
    assert "楽天で保存して印刷準備" in res.text
    assert "Amazon印刷完了を記録" in res.text
    assert "楽天印刷完了を記録" in res.text
    assert "印刷は自動実行しません" in res.text
    assert "除外PDF一覧を開く（1件ずつ印刷）" in res.text
    assert 'id="print-next-box"' in res.text

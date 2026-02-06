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
    assert "https://order.my.rakuten.co.jp/purchase-history/?order_number=RAK-001" in res.text

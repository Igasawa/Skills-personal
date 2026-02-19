from __future__ import annotations

import json
from pathlib import Path

import pytest

import dashboard.services.core_artifacts as core_artifacts
from dashboard.services.core_artifacts import _scan_artifacts


def _artifact_root(ax_home: Path) -> Path:
    return ax_home / "artifacts" / "mfcloud-expense-receipt-reconcile"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_scan_artifacts_derives_order_counts_without_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    root = _artifact_root(tmp_path) / "2026-01"

    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [
            {"order_id": "A-1", "order_date": "2026-01-03"},
            {"order_id": "A-1", "order_date": "2026-01-03"},  # duplicate
            {"order_id": "A-2", "order_date": "2025-12-29"},
        ],
    )
    _write_jsonl(
        root / "rakuten" / "orders.jsonl",
        [
            {"order_id": "R-1", "order_date": "2026-01-10"},
        ],
    )

    items = _scan_artifacts()
    assert items
    item = next(x for x in items if x["ym"] == "2026-01")
    counts = item["counts"]
    assert counts["amazon_orders_total"] == 2
    assert counts["rakuten_orders_total"] == 1
    assert counts["orders_total"] == 3
    assert counts["amazon_orders_in_month"] == 1
    assert counts["rakuten_orders_in_month"] == 1
    assert counts["orders_in_month"] == 2


def test_scan_artifacts_order_counts_override_stale_report_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    root = _artifact_root(tmp_path) / "2026-01"

    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [{"order_id": "A-1", "order_date": "2026-01-03"}],
    )
    _write_jsonl(
        root / "rakuten" / "orders.jsonl",
        [{"order_id": "R-1", "order_date": "2026-01-10"}],
    )
    _write_json(
        root / "reports" / "missing_evidence_candidates.json",
        {
            "counts": {
                "amazon_orders_in_month": 0,
                "rakuten_orders_in_month": 0,
                "orders_in_month": 0,
                "mf_missing_evidence": 7,
            },
            "rows": [],
        },
    )

    items = _scan_artifacts()
    item = next(x for x in items if x["ym"] == "2026-01")
    counts = item["counts"]
    assert counts["amazon_orders_in_month"] == 1
    assert counts["rakuten_orders_in_month"] == 1
    assert counts["orders_in_month"] == 2
    assert counts["mf_missing_evidence"] == 7


def test_scan_artifacts_counts_rows_with_missing_order_id_using_detail_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    root = _artifact_root(tmp_path) / "2026-01"

    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [
            {"order_id": None, "detail_url": "https://example.invalid/order?orderID=503-0000000-0000000", "order_date": "2026-01-03"},
            {"order_id": "A-1", "order_date": "2026-01-03"},
        ],
    )

    items = _scan_artifacts()
    item = next(x for x in items if x["ym"] == "2026-01")
    counts = item["counts"]
    assert counts["amazon_orders_in_month"] == 2
    assert counts["orders_in_month"] == 2


def test_scan_artifacts_derives_exclusion_counts_from_orders_and_exclusions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    root = _artifact_root(tmp_path) / "2026-01"

    _write_jsonl(
        root / "amazon" / "orders.jsonl",
        [
            {"order_id": "A-1", "order_date": "2026-01-03", "status": "ok", "total_yen": 1200},
            {"order_id": "A-2", "order_date": "2026-01-04", "status": "gift_card", "total_yen": 5000},
        ],
    )
    _write_jsonl(
        root / "rakuten" / "orders.jsonl",
        [
            {"order_id": "R-1", "order_date": "2026-01-10", "status": "ok", "include": False, "total_yen": 2100},
            {"order_id": "R-2", "order_date": "2026-01-11", "status": "ok", "total_yen": "-"},
        ],
    )
    _write_json(
        root / "reports" / "exclude_orders.json",
        {"ym": "2026-01", "exclude": [{"source": "amazon", "order_id": "A-1"}]},
    )

    items = _scan_artifacts()
    item = next(x for x in items if x["ym"] == "2026-01")
    counts = item["counts"]

    assert counts["manual_excluded_orders"] == 1
    assert counts["excluded_orders"] == 4
    assert counts["included_orders"] == 0
    assert counts["amazon_excluded_orders"] == 2
    assert counts["rakuten_excluded_orders"] == 2


def test_resolve_form_defaults_falls_back_when_last_run_month_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AX_HOME", str(tmp_path))
    monkeypatch.setattr(core_artifacts, "_ym_default", lambda: (2026, 1))

    _write_json(
        _artifact_root(tmp_path) / "2026-01" / "run_config.resolved.json",
        {
            "year": 2026,
            "month": 13,
            "monthly_notes": "invalid month in last run",
            "tenant": {
                "urls": {
                    "mfcloud_expense_list": "https://example.com/outgo_input",
                }
            },
        },
    )

    defaults = core_artifacts._resolve_form_defaults()
    assert defaults["year"] == 2026
    assert defaults["month"] == 1

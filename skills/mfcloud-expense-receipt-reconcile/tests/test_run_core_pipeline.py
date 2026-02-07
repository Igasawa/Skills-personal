from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from scripts import run_core_pipeline


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        preflight=False,
        skip_amazon=False,
        skip_rakuten=True,
        skip_mfcloud=True,
        skip_reconcile=True,
        print_list=False,
        print_sources="",
        skip_receipt_name=False,
    )


def _rc(tmp_path: Path) -> SimpleNamespace:
    output_root = tmp_path / "out"
    return SimpleNamespace(
        dry_run=False,
        output_root=output_root,
        amazon_storage_state=tmp_path / "amazon.storage.json",
        mfcloud_storage_state=tmp_path / "mf.storage.json",
        rakuten_storage_state=tmp_path / "rakuten.storage.json",
        amazon_orders_url="https://www.amazon.co.jp/gp/your-account/order-history",
        rakuten_orders_url="https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order",
        mfcloud_accounts_url="https://expense.moneyforward.com/accounts",
        mfcloud_expense_list_url="https://expense.moneyforward.com/outgo_input",
        tenant_key="default",
        tenant_name="default",
        receipt_name="株式会社テスト",
        receipt_name_fallback="Test Inc.",
        amazon_min_pdf_success_rate=0.8,
        history_only_receipt_flow=True,
        rakuten_enabled=False,
        headed=False,
        slow_mo_ms=0,
        date_window_days=7,
        max_candidates_per_mf=5,
        monthly_notes="",
        interactive=False,
        resolved_sources={},
    )


def test_execute_pipeline_passes_amazon_threshold_and_history_flags(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, list[str]] = {}

    def _fake_run_node_playwright_script(*, script_path, cwd, args, env=None):  # noqa: ANN001
        if Path(script_path).name == "amazon_download.mjs":
            captured["amazon_args"] = list(args)
            return {"status": "success", "data": {"monthly_orders_total": 3, "pdf_saved": 3, "coverage": 1.0}}
        return {"status": "success", "data": {}}

    monkeypatch.setattr(run_core_pipeline, "run_node_playwright_script", _fake_run_node_playwright_script)
    monkeypatch.setattr(run_core_pipeline, "archive_existing_pdfs", lambda *a, **k: None)
    monkeypatch.setattr(run_core_pipeline, "build_quality_gate", lambda **k: {"status": "pass", "ready_for_submission": True})

    rc = _rc(tmp_path)
    for state_path in (rc.amazon_storage_state, rc.mfcloud_storage_state, rc.rakuten_storage_state):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{}", encoding="utf-8")

    result = run_core_pipeline.execute_pipeline(
        args=_args(),
        rc=rc,
        year=2026,
        month=1,
        render_monthly_thread=lambda **kwargs: "# thread\n",
    )

    assert result["status"] == "success"
    amazon_args = captured.get("amazon_args") or []
    assert "--min-pdf-success-rate" in amazon_args
    idx = amazon_args.index("--min-pdf-success-rate")
    assert amazon_args[idx + 1] == "0.8"
    assert "--history-only-receipt-flow" in amazon_args

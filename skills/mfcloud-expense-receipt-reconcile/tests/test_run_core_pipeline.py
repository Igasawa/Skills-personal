from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
from types import SimpleNamespace

from scripts import run_core_pipeline


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        preflight=False,
        skip_amazon=False,
        skip_rakuten=True,
        skip_mfcloud=True,
        skip_reconcile=True,
        mf_draft_create=False,
        mf_draft_no_autofill=False,
        mf_draft_autofill_account_title="",
        mf_draft_only_expense_id="",
        mf_draft_max_targets=None,
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


def test_execute_pipeline_runs_mf_draft_create_when_enabled(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, list[str]] = {}

    def _fake_run_node_playwright_script(*, script_path, cwd, args, env=None):  # noqa: ANN001
        name = Path(script_path).name
        if name == "mfcloud_extract.mjs":
            out_jsonl = Path(args[args.index("--out-jsonl") + 1])
            out_jsonl.parent.mkdir(parents=True, exist_ok=True)
            out_jsonl.write_text(
                '{"expense_id":"MF-1","use_date":"2026-01-05","amount_yen":1200,"vendor":"AQUA VOICE","memo":"AQUA VOICE","has_evidence":false}\n',
                encoding="utf-8",
            )
            return {"status": "success", "data": {"extracted": 1}}
        if name == "mfcloud_outgo_register.mjs":
            captured["mf_draft_args"] = list(args)
            out_json = Path(args[args.index("--out-json") + 1])
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(
                '{"status":"success","data":{"targets_total":1,"attempted":1,"created":1,"skipped":0,"failed":0}}',
                encoding="utf-8",
            )
            return {"status": "success", "data": {"targets_total": 1, "attempted": 1, "created": 1, "skipped": 0, "failed": 0}}
        return {"status": "success", "data": {}}

    def _fake_subprocess_run(cmd, *args, **kwargs):  # noqa: ANN001
        cmd_list = [str(x) for x in cmd]
        if any("reconcile.py" in x for x in cmd_list):
            out_json = Path(cmd_list[cmd_list.index("--out-json") + 1])
            out_csv = Path(cmd_list[cmd_list.index("--out-csv") + 1])
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(
                '{"year":2026,"month":1,"counts":{"mf_missing_evidence":1},"rows":[{"mf_expense_id":"MF-1","mf_use_date":"2026-01-05","mf_amount_yen":1200,"mf_vendor":"AQUA VOICE","mf_memo":"AQUA VOICE","row_type":"candidate","rank":1,"order_id":"A-1","order_source":"amazon","order_date":"2026-01-05","total_yen":1200,"pdf_path":"C:/tmp/a.pdf","diff_days":0,"score":130}]}',
                encoding="utf-8",
            )
            out_csv.write_text("mf_expense_id\nMF-1\n", encoding="utf-8")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout='{"status":"success","data":{"counts":{"mf_missing_evidence":1}}}', stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(run_core_pipeline, "run_node_playwright_script", _fake_run_node_playwright_script)
    monkeypatch.setattr(run_core_pipeline, "archive_existing_pdfs", lambda *a, **k: None)
    monkeypatch.setattr(run_core_pipeline, "build_quality_gate", lambda **k: {"status": "pass", "ready_for_submission": True})
    monkeypatch.setattr(run_core_pipeline.subprocess, "run", _fake_subprocess_run)

    args = _args()
    args.skip_rakuten = True
    args.skip_mfcloud = False
    args.skip_reconcile = False
    args.mf_draft_create = True
    args.mf_draft_max_targets = 1

    rc = _rc(tmp_path)
    for state_path in (rc.amazon_storage_state, rc.mfcloud_storage_state, rc.rakuten_storage_state):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{}", encoding="utf-8")
    (rc.output_root / "amazon").mkdir(parents=True, exist_ok=True)
    (rc.output_root / "amazon" / "orders.jsonl").write_text(
        '{"order_id":"A-1","order_date":"2026-01-05","order_total_yen":1200,"pdf_path":"C:/tmp/a.pdf"}\n',
        encoding="utf-8",
    )

    result = run_core_pipeline.execute_pipeline(
        args=args,
        rc=rc,
        year=2026,
        month=1,
        render_monthly_thread=lambda **kwargs: "# thread\n",
    )

    assert result["status"] == "success"
    mf_draft_args = captured.get("mf_draft_args") or []
    assert "--report-json" in mf_draft_args
    assert "--out-json" in mf_draft_args
    assert "--audit-jsonl" in mf_draft_args
    assert "--max-targets" in mf_draft_args
    assert mf_draft_args[mf_draft_args.index("--max-targets") + 1] == "1"
    assert result["data"]["mf_draft"]["created"] == 1
    assert result["data"]["reports"]["mf_draft_create_result_json"].endswith("mf_draft_create_result.json")
    assert result["data"]["reports"]["mf_draft_create_actions_jsonl"].endswith("mf_draft_create_actions.jsonl")


def test_execute_pipeline_reconcile_includes_manual_orders_when_available(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, list[str]] = {}

    def _fake_run_node_playwright_script(*, script_path, cwd, args, env=None):  # noqa: ANN001
        return {"status": "success", "data": {}}

    def _fake_subprocess_run(cmd, *args, **kwargs):  # noqa: ANN001
        cmd_list = [str(x) for x in cmd]
        if any("reconcile.py" in x for x in cmd_list):
            captured["reconcile_cmd"] = cmd_list
            out_json = Path(cmd_list[cmd_list.index("--out-json") + 1])
            out_csv = Path(cmd_list[cmd_list.index("--out-csv") + 1])
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text('{"year":2026,"month":1,"counts":{"manual_orders_total":1},"rows":[]}', encoding="utf-8")
            out_csv.write_text("mf_expense_id\n", encoding="utf-8")
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout='{"status":"success","data":{"counts":{"manual_orders_total":1}}}',
                stderr="",
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(run_core_pipeline, "run_node_playwright_script", _fake_run_node_playwright_script)
    monkeypatch.setattr(run_core_pipeline, "archive_existing_pdfs", lambda *a, **k: None)
    monkeypatch.setattr(run_core_pipeline, "build_quality_gate", lambda **k: {"status": "pass", "ready_for_submission": True})
    monkeypatch.setattr(run_core_pipeline.subprocess, "run", _fake_subprocess_run)

    args = _args()
    args.skip_amazon = True
    args.skip_rakuten = True
    args.skip_mfcloud = True
    args.skip_reconcile = False

    rc = _rc(tmp_path)
    for state_path in (rc.amazon_storage_state, rc.mfcloud_storage_state, rc.rakuten_storage_state):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{}", encoding="utf-8")

    (rc.output_root / "manual").mkdir(parents=True, exist_ok=True)
    (rc.output_root / "manual" / "orders.jsonl").write_text(
        '{"source":"manual","order_id":"MANUAL-1","order_date":"2026-01-05","total_yen":1800,"pdf_path":"C:/tmp/manual.pdf"}\n',
        encoding="utf-8",
    )
    (rc.output_root / "mfcloud").mkdir(parents=True, exist_ok=True)
    (rc.output_root / "mfcloud" / "expenses.jsonl").write_text(
        '{"expense_id":"MF-1","use_date":"2026-01-05","amount_yen":1800,"vendor":"MANUAL","memo":"","has_evidence":false}\n',
        encoding="utf-8",
    )

    result = run_core_pipeline.execute_pipeline(
        args=args,
        rc=rc,
        year=2026,
        month=1,
        render_monthly_thread=lambda **kwargs: "# thread\n",
    )

    assert result["status"] == "success"
    cmd = captured.get("reconcile_cmd") or []
    assert "--manual-orders-jsonl" in cmd

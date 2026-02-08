#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from common import ensure_dir as _ensure_dir  # noqa: E402
from common import read_json as _read_json_file  # noqa: E402
from common import write_json as _write_json  # noqa: E402
from run_core_io import archive_existing_pdfs  # noqa: E402
from run_core_playwright import run_node_playwright_script  # noqa: E402
from run_core_quality import build_quality_gate  # noqa: E402


def _write_resolved_config(*, output_root: Path, rc: Any, year: int, month: int) -> None:
    _write_json(
        output_root / "run_config.resolved.json",
        {
            "year": year,
            "month": month,
            "dry_run": rc.dry_run,
            "output_root": str(output_root),
            "sessions": {
                "amazon_storage_state": str(rc.amazon_storage_state),
                "mfcloud_storage_state": str(rc.mfcloud_storage_state),
                "rakuten_storage_state": str(rc.rakuten_storage_state),
            },
            "urls": {
                "amazon_orders": rc.amazon_orders_url,
                "mfcloud_accounts": rc.mfcloud_accounts_url,
                "mfcloud_expense_list": rc.mfcloud_expense_list_url,
            },
            "tenant": {
                "key": rc.tenant_key,
                "name": rc.tenant_name,
                "receipt": {
                    "name": rc.receipt_name,
                    "name_fallback": rc.receipt_name_fallback,
                },
                "urls": {
                    "amazon_orders": rc.amazon_orders_url,
                    "rakuten_orders": rc.rakuten_orders_url,
                    "mfcloud_accounts": rc.mfcloud_accounts_url,
                    "mfcloud_expense_list": rc.mfcloud_expense_list_url,
                },
            },
            "rakuten": {
                "enabled": rc.rakuten_enabled,
                "orders_url": rc.rakuten_orders_url,
            },
            "playwright": {"headed": rc.headed, "slow_mo_ms": rc.slow_mo_ms},
            "amazon": {
                "min_pdf_success_rate": rc.amazon_min_pdf_success_rate,
                "history_only_receipt_flow": rc.history_only_receipt_flow,
            },
            "matching": {"date_window_days": rc.date_window_days, "max_candidates_per_mf": rc.max_candidates_per_mf},
            "monthly_notes": rc.monthly_notes,
            "receipt_name": rc.receipt_name,
            "receipt_name_fallback": rc.receipt_name_fallback,
            "interactive": rc.interactive,
            "resolved_sources": rc.resolved_sources,
        },
    )


def execute_pipeline(
    *,
    args: argparse.Namespace,
    rc: Any,
    year: int,
    month: int,
    render_monthly_thread: Callable[..., str],
) -> dict[str, Any]:
    print(f"[run] start year={year} month={month} output_root={rc.output_root}", flush=True)

    output_root = _ensure_dir(rc.output_root)
    amazon_dir = _ensure_dir(output_root / "amazon")
    amazon_pdfs_dir = _ensure_dir(amazon_dir / "pdfs")
    rakuten_dir = _ensure_dir(output_root / "rakuten")
    rakuten_pdfs_dir = _ensure_dir(rakuten_dir / "pdfs")
    mf_dir = _ensure_dir(output_root / "mfcloud")
    reports_dir = _ensure_dir(output_root / "reports")
    debug_dir = _ensure_dir(output_root / "debug")

    _write_resolved_config(output_root=output_root, rc=rc, year=year, month=month)

    amazon_orders_jsonl = amazon_dir / "orders.jsonl"
    rakuten_orders_jsonl = rakuten_dir / "orders.jsonl"
    mf_expenses_jsonl = mf_dir / "expenses.jsonl"

    amazon_summary: dict[str, Any] = {"orders_jsonl": str(amazon_orders_jsonl), "pdfs_dir": str(amazon_pdfs_dir)}
    rakuten_summary: dict[str, Any] = {"orders_jsonl": str(rakuten_orders_jsonl), "pdfs_dir": str(rakuten_pdfs_dir)}
    mf_summary: dict[str, Any] = {"expenses_jsonl": str(mf_expenses_jsonl)}

    if args.preflight:
        print("[run] Preflight start", flush=True)
        preflight_out = run_node_playwright_script(
            script_path=SCRIPT_DIR / "preflight.mjs",
            cwd=SCRIPT_DIR,
            args=[
                "--amazon-orders-url",
                rc.amazon_orders_url,
                "--rakuten-orders-url",
                rc.rakuten_orders_url,
                "--mfcloud-accounts-url",
                rc.mfcloud_accounts_url,
                "--amazon-storage-state",
                str(rc.amazon_storage_state),
                "--rakuten-storage-state",
                str(rc.rakuten_storage_state),
                "--mfcloud-storage-state",
                str(rc.mfcloud_storage_state),
                *(["--auth-handoff"] if rc.interactive else []),
                "--headed" if rc.headed else "--headless",
                "--slow-mo-ms",
                str(rc.slow_mo_ms),
            ],
        )
        preflight_data = (preflight_out.get("data") if isinstance(preflight_out, dict) else None) or preflight_out
        preflight_result = {
            "status": "success",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "year": year,
            "month": month,
            "data": preflight_data,
        }
        _write_json(reports_dir / "preflight.json", preflight_result)
        _write_json(output_root.parent / "_preflight.json", preflight_result)
        print("[run] Preflight done", flush=True)
        return {"status": "success", "data": {"preflight": preflight_data}}

    if rc.dry_run:
        print("[run] dry-run enabled: skipping browser downloads", flush=True)
    if not rc.dry_run:
        receipt_env = {
            "RECEIPT_NAME": rc.receipt_name,
            "RECEIPT_NAME_FALLBACK": rc.receipt_name_fallback,
        }

        if not args.skip_amazon:
            print("[run] Amazon download start", flush=True)
            archive_existing_pdfs(amazon_pdfs_dir, "Amazon")
            amazon_out = run_node_playwright_script(
                script_path=SCRIPT_DIR / "amazon_download.mjs",
                cwd=SCRIPT_DIR,
                args=[
                    "--storage-state",
                    str(rc.amazon_storage_state),
                    "--orders-url",
                    rc.amazon_orders_url,
                    "--out-jsonl",
                    str(amazon_orders_jsonl),
                    "--out-pdfs-dir",
                    str(amazon_pdfs_dir),
                    "--year",
                    str(year),
                    "--month",
                    str(month),
                    "--debug-dir",
                    str(debug_dir / "amazon"),
                    *(["--auth-handoff"] if rc.interactive else []),
                    "--headed" if rc.headed else "--headless",
                    "--slow-mo-ms",
                    str(rc.slow_mo_ms),
                    "--min-pdf-success-rate",
                    str(rc.amazon_min_pdf_success_rate),
                    *(["--history-only-receipt-flow"] if rc.history_only_receipt_flow else []),
                    *(["--skip-receipt-name"] if args.skip_receipt_name else []),
                ],
                env=receipt_env,
            )
            amazon_summary.update((amazon_out.get("data") if isinstance(amazon_out, dict) else None) or amazon_out)
            print("[run] Amazon download done", flush=True)
        else:
            print("[run] Amazon download skipped", flush=True)

        if rc.rakuten_enabled and not args.skip_rakuten:
            print("[run] Rakuten download start", flush=True)
            archive_existing_pdfs(rakuten_pdfs_dir, "Rakuten")
            if rakuten_orders_jsonl.exists():
                rakuten_orders_jsonl.unlink()
                print("[run] Deleted existing Rakuten orders.jsonl", flush=True)
            rakuten_out = run_node_playwright_script(
                script_path=SCRIPT_DIR / "rakuten_download.mjs",
                cwd=SCRIPT_DIR,
                args=[
                    "--storage-state",
                    str(rc.rakuten_storage_state),
                    "--orders-url",
                    rc.rakuten_orders_url,
                    "--out-jsonl",
                    str(rakuten_orders_jsonl),
                    "--out-pdfs-dir",
                    str(rakuten_pdfs_dir),
                    "--year",
                    str(year),
                    "--month",
                    str(month),
                    "--debug-dir",
                    str(debug_dir / "rakuten"),
                    *(["--auth-handoff"] if rc.interactive else []),
                    "--headed" if rc.headed else "--headless",
                    "--slow-mo-ms",
                    str(rc.slow_mo_ms),
                ],
                env=receipt_env,
            )
            rakuten_summary.update((rakuten_out.get("data") if isinstance(rakuten_out, dict) else None) or rakuten_out)
            print("[run] Rakuten download done", flush=True)
        elif args.skip_rakuten:
            print("[run] Rakuten download skipped", flush=True)
        elif not rc.rakuten_enabled:
            print("[run] Rakuten disabled", flush=True)

        if not args.skip_mfcloud:
            print("[run] MF Cloud extract start", flush=True)
            mf_out = run_node_playwright_script(
                script_path=SCRIPT_DIR / "mfcloud_extract.mjs",
                cwd=SCRIPT_DIR,
                args=[
                    "--storage-state",
                    str(rc.mfcloud_storage_state),
                    "--expense-list-url",
                    rc.mfcloud_expense_list_url,
                    "--out-jsonl",
                    str(mf_expenses_jsonl),
                    "--year",
                    str(year),
                    "--month",
                    str(month),
                    "--debug-dir",
                    str(debug_dir / "mfcloud"),
                    *(["--auth-handoff"] if rc.interactive else []),
                    "--headed" if rc.headed else "--headless",
                    "--slow-mo-ms",
                    str(rc.slow_mo_ms),
                ],
            )
            mf_summary.update((mf_out.get("data") if isinstance(mf_out, dict) else None) or mf_out)
            print("[run] MF Cloud extract done", flush=True)
        else:
            print("[run] MF Cloud extract skipped", flush=True)

    rec_out_json = reports_dir / "missing_evidence_candidates.json"
    rec_out_csv = reports_dir / "missing_evidence_candidates.csv"
    quality_gate_json = reports_dir / "quality_gate.json"
    monthly_thread_md = reports_dir / "monthly_thread.md"
    mf_draft_result_json = reports_dir / "mf_draft_create_result.json"
    exclude_orders_json = reports_dir / "exclude_orders.json"

    rec_json: dict[str, Any] = {}
    if not args.skip_reconcile:
        print("[run] Reconcile start", flush=True)
        amazon_orders_exists = amazon_orders_jsonl.exists()
        rakuten_orders_exists = rakuten_orders_jsonl.exists()
        if not amazon_orders_exists and not rakuten_orders_exists:
            raise RuntimeError(
                "Missing orders.jsonl for both amazon/rakuten. "
                "Run at least one receipt download+print step before reconcile."
            )
        if not mf_expenses_jsonl.exists():
            raise RuntimeError("Missing mfcloud/expenses.jsonl. Run MF extract or provide existing data.")

        rec_cmd = [
            sys.executable,
            str(SCRIPT_DIR / "reconcile.py"),
            "--mf-expenses-jsonl",
            str(mf_expenses_jsonl),
            "--out-json",
            str(rec_out_json),
            "--out-csv",
            str(rec_out_csv),
            "--year",
            str(year),
            "--month",
            str(month),
            "--date-window-days",
            str(rc.date_window_days),
            "--max-candidates-per-mf",
            str(rc.max_candidates_per_mf),
        ]
        if amazon_orders_exists:
            rec_cmd += ["--amazon-orders-jsonl", str(amazon_orders_jsonl)]
        if rakuten_orders_exists:
            rec_cmd += ["--rakuten-orders-jsonl", str(rakuten_orders_jsonl)]
        if exclude_orders_json.exists():
            rec_cmd += ["--exclude-orders-json", str(exclude_orders_json)]
        rec_res = subprocess.run(rec_cmd, cwd=str(SCRIPT_DIR), capture_output=True, text=True, check=False)
        if rec_res.returncode != 0:
            raise RuntimeError(
                "reconcile.py failed:\n"
                f"cmd: {rec_cmd}\n"
                f"exit: {rec_res.returncode}\n"
                f"stdout:\n{rec_res.stdout}\n"
                f"stderr:\n{rec_res.stderr}\n"
            )

        try:
            rec_json = json.loads(rec_res.stdout) if rec_res.stdout.strip() else {}
        except Exception:
            rec_json = {"status": "success", "data": {"note": "reconcile.py did not return JSON; see reports files"}}
        print("[run] Reconcile done", flush=True)
    else:
        print("[run] Reconcile skipped", flush=True)

    mf_draft_summary: dict[str, Any] = {}
    if bool(getattr(args, "mf_draft_create", False)):
        if rc.dry_run:
            print("[run] MF draft create skipped (dry-run)", flush=True)
            mf_draft_summary = {"status": "skipped", "reason": "dry_run", "out_json": str(mf_draft_result_json)}
            _write_json(mf_draft_result_json, mf_draft_summary)
        else:
            if not rec_out_json.exists():
                raise RuntimeError("Missing reports/missing_evidence_candidates.json. Reconcile must run before MF draft create.")
            print("[run] MF draft create start", flush=True)
            mf_draft_out = run_node_playwright_script(
                script_path=SCRIPT_DIR / "mfcloud_outgo_register.mjs",
                cwd=SCRIPT_DIR,
                args=[
                    "--storage-state",
                    str(rc.mfcloud_storage_state),
                    "--outgo-url",
                    rc.mfcloud_expense_list_url,
                    "--report-json",
                    str(rec_out_json),
                    "--out-json",
                    str(mf_draft_result_json),
                    "--year",
                    str(year),
                    "--month",
                    str(month),
                    "--debug-dir",
                    str(debug_dir / "mfcloud_draft"),
                    *(["--auth-handoff"] if rc.interactive else []),
                    "--headed" if rc.headed else "--headless",
                    "--slow-mo-ms",
                    str(rc.slow_mo_ms),
                ],
            )
            mf_draft_summary = (mf_draft_out.get("data") if isinstance(mf_draft_out, dict) else None) or mf_draft_out
            print("[run] MF draft create done", flush=True)

    rec_report = _read_json_file(rec_out_json)
    rec_report_dict = rec_report if isinstance(rec_report, dict) else None
    quality_gate = build_quality_gate(
        report=rec_report_dict,
        report_json_path=rec_out_json,
        report_csv_path=rec_out_csv,
        year=year,
        month=month,
    )
    _write_json(quality_gate_json, quality_gate)
    print(f"[run] Quality gate done status={quality_gate.get('status')}", flush=True)

    template_path = SCRIPT_DIR.parent / "assets" / "monthly_thread_template.md"
    receipts_path = str(amazon_pdfs_dir)
    if rc.rakuten_enabled:
        receipts_path = f"{amazon_pdfs_dir}; {rakuten_pdfs_dir}"
    monthly_thread = render_monthly_thread(
        template_path=template_path,
        year=year,
        month=month,
        receipts_path=receipts_path,
        reports_path=reports_dir,
        notes=rc.monthly_notes,
    )
    monthly_thread_md.write_text(monthly_thread, encoding="utf-8")

    if args.print_list:
        print("[run] Print list generation start", flush=True)
        print_sources = args.print_sources or ""
        print_cmd = [
            sys.executable,
            str(SCRIPT_DIR / "collect_print.py"),
            "--year",
            str(year),
            "--month",
            str(month),
            "--output-dir",
            str(output_root),
        ]
        if print_sources:
            print_cmd += ["--sources", print_sources]
        if exclude_orders_json.exists():
            print_cmd += ["--exclude-orders-json", str(exclude_orders_json)]
        print_res = subprocess.run(print_cmd, cwd=str(SCRIPT_DIR), capture_output=True, text=True, check=False)
        if print_res.returncode != 0:
            raise RuntimeError(
                "collect_print.py failed:\n"
                f"cmd: {print_cmd}\n"
                f"exit: {print_res.returncode}\n"
                f"stdout:\n{print_res.stdout}\n"
                f"stderr:\n{print_res.stderr}\n"
            )
        print("[run] Print list generation done", flush=True)

    return {
        "status": "success",
        "data": {
            "output_root": str(output_root),
            "amazon": amazon_summary,
            "rakuten": rakuten_summary,
            "mfcloud": mf_summary,
            "reports": {
                "missing_evidence_candidates_csv": str(rec_out_csv),
                "missing_evidence_candidates_json": str(rec_out_json),
                "quality_gate_json": str(quality_gate_json),
                "monthly_thread_md": str(monthly_thread_md),
                "mf_draft_create_result_json": str(mf_draft_result_json),
            },
            "reconcile": rec_json.get("data", rec_json),
            "mf_draft": mf_draft_summary,
            "quality_gate": quality_gate,
        },
    }

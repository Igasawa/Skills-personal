#!/usr/bin/env python3
"""
Run the skill with a standardized JSON interface.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from common import (  # noqa: E402
    as_int as _as_int,
    ax_home as _ax_home,
    coalesce as _coalesce,
    default_storage_state as _default_storage_state,
    ym_default as _ym_default,
    ym_to_dirname as _ym_to_dirname,
)
from run_core_io import read_json_input as _read_json_input  # noqa: E402
from run_core_pipeline import execute_pipeline  # noqa: E402
from run_core_template import render_monthly_thread  # noqa: E402


@dataclass(frozen=True)
class RunConfig:
    interactive: bool
    dry_run: bool
    output_root: Path
    amazon_orders_url: str
    mfcloud_accounts_url: str
    mfcloud_expense_list_url: str
    amazon_storage_state: Path
    mfcloud_storage_state: Path
    headed: bool
    slow_mo_ms: int
    date_window_days: int
    max_candidates_per_mf: int
    monthly_notes: str
    receipt_name: str
    receipt_name_fallback: str
    rakuten_enabled: bool
    rakuten_orders_url: str
    rakuten_storage_state: Path


def _parse_config(args: argparse.Namespace, raw: dict[str, Any]) -> tuple[RunConfig, int, int]:
    config = raw.get("config") if isinstance(raw, dict) else None
    params = raw.get("params") if isinstance(raw, dict) else None
    config = config if isinstance(config, dict) else {}
    params = params if isinstance(params, dict) else {}

    default_year, default_month = _ym_default()
    year = _as_int(_coalesce(args.year, params.get("year"), default_year), name="year")
    month = _as_int(_coalesce(args.month, params.get("month"), default_month), name="month")

    urls = config.get("urls") if isinstance(config.get("urls"), dict) else {}
    sessions = config.get("sessions") if isinstance(config.get("sessions"), dict) else {}
    pw = config.get("playwright") if isinstance(config.get("playwright"), dict) else {}
    matching = config.get("matching") if isinstance(config.get("matching"), dict) else {}
    rakuten_cfg = config.get("rakuten") if isinstance(config.get("rakuten"), dict) else {}

    interactive = bool(_coalesce(args.interactive, config.get("interactive", False)))
    monthly_notes = _coalesce(args.monthly_notes, config.get("monthly_notes"))
    monthly_notes = str(monthly_notes).strip() if monthly_notes is not None else ""
    receipt_name = _coalesce(args.receipt_name, config.get("receipt_name"), "株式会社ＨＩＧＨ－ＳＴＡＮＤＡＲＤ＆ＣＯ．")
    receipt_name = str(receipt_name).strip() if receipt_name is not None else ""
    receipt_name_fallback = _coalesce(
        args.receipt_name_fallback,
        config.get("receipt_name_fallback"),
        "株式会社HIGH-STANDARD&CO.",
    )
    receipt_name_fallback = str(receipt_name_fallback).strip() if receipt_name_fallback is not None else ""

    dry_run = bool(_coalesce(args.dry_run, config.get("dry_run", False)))
    preflight = bool(getattr(args, "preflight", False))

    amazon_orders_url = str(
        _coalesce(args.amazon_orders_url, urls.get("amazon_orders"), "https://www.amazon.co.jp/gp/your-account/order-history")
    )
    rakuten_enabled = bool(_coalesce(args.enable_rakuten, rakuten_cfg.get("enabled", False)))
    rakuten_orders_url = str(
        _coalesce(
            args.rakuten_orders_url,
            rakuten_cfg.get("orders_url"),
            "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order",
        )
    )
    mfcloud_accounts_url = str(
        _coalesce(args.mfcloud_accounts_url, urls.get("mfcloud_accounts"), "https://expense.moneyforward.com/accounts")
    )
    mfcloud_expense_list_url = _coalesce(args.mfcloud_expense_list_url, urls.get("mfcloud_expense_list"))
    if not mfcloud_expense_list_url:
        if dry_run or getattr(args, "skip_mfcloud", False) or preflight:
            mfcloud_expense_list_url = ""
        else:
            raise ValueError(
                "Missing MF Cloud expense list URL. Set config.urls.mfcloud_expense_list or pass --mfcloud-expense-list-url."
            )
    mfcloud_expense_list_url = str(mfcloud_expense_list_url)

    output_root = Path(
        _coalesce(args.output_dir, config.get("output_dir"))
        or (_ax_home() / "artifacts" / "mfcloud-expense-receipt-reconcile" / _ym_to_dirname(year, month))
    )
    output_root = output_root.expanduser().resolve()

    amazon_storage_state = Path(
        _coalesce(args.amazon_storage_state, sessions.get("amazon_storage_state")) or _default_storage_state("amazon")
    )
    mfcloud_storage_state = Path(
        _coalesce(args.mfcloud_storage_state, sessions.get("mfcloud_storage_state")) or _default_storage_state("mfcloud-expense")
    )
    rakuten_storage_state = Path(
        _coalesce(args.rakuten_storage_state, sessions.get("rakuten_storage_state")) or _default_storage_state("rakuten")
    )

    headed = bool(_coalesce(args.headed, pw.get("headed", True)))
    slow_mo_ms = _as_int(_coalesce(args.slow_mo_ms, pw.get("slow_mo_ms", 0)), name="slow_mo_ms")
    date_window_days = _as_int(_coalesce(args.date_window_days, matching.get("date_window_days", 7)), name="date_window_days")
    max_candidates_per_mf = _as_int(
        _coalesce(args.max_candidates_per_mf, matching.get("max_candidates_per_mf", 5)),
        name="max_candidates_per_mf",
    )

    rc = RunConfig(
        interactive=interactive,
        dry_run=dry_run,
        output_root=output_root,
        amazon_orders_url=amazon_orders_url,
        rakuten_orders_url=rakuten_orders_url,
        mfcloud_accounts_url=mfcloud_accounts_url,
        mfcloud_expense_list_url=mfcloud_expense_list_url,
        amazon_storage_state=amazon_storage_state.expanduser().resolve(),
        mfcloud_storage_state=mfcloud_storage_state.expanduser().resolve(),
        rakuten_storage_state=rakuten_storage_state.expanduser().resolve(),
        headed=headed,
        slow_mo_ms=slow_mo_ms,
        date_window_days=date_window_days,
        max_candidates_per_mf=max_candidates_per_mf,
        monthly_notes=monthly_notes,
        receipt_name=receipt_name,
        receipt_name_fallback=receipt_name_fallback,
        rakuten_enabled=rakuten_enabled,
    )
    return rc, year, month


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="mfcloud-expense-receipt-reconcile runner")
    ap.add_argument("--input", help="path to input JSON (otherwise stdin)")
    ap.add_argument("--year", type=int, help="default: last month")
    ap.add_argument("--month", type=int, help="default: last month")
    ap.add_argument("--dry-run", dest="dry_run", action="store_const", const=True, default=None, help="skip browser and only reconcile from existing jsonl")
    ap.add_argument("--output-dir", dest="output_dir", help="override output_root")
    ap.add_argument("--amazon-orders-url", dest="amazon_orders_url", help="override Amazon order history URL")
    ap.add_argument("--mfcloud-accounts-url", dest="mfcloud_accounts_url", help="MF Cloud accounts URL")
    ap.add_argument("--mfcloud-expense-list-url", dest="mfcloud_expense_list_url", help="MF Cloud expense list URL (required)")
    ap.add_argument("--amazon-storage-state", dest="amazon_storage_state", help="path to amazon.storage.json")
    ap.add_argument("--mfcloud-storage-state", dest="mfcloud_storage_state", help="path to mfcloud-expense.storage.json")
    ap.add_argument("--rakuten-storage-state", dest="rakuten_storage_state", help="path to rakuten.storage.json")
    ap.add_argument("--notes", dest="monthly_notes", help="monthly notes for thread template")
    ap.add_argument("--receipt-name", dest="receipt_name", help="receipt addressee name for Amazon invoices")
    ap.add_argument("--receipt-name-fallback", dest="receipt_name_fallback", help="fallback receipt name when primary fails")
    ap.add_argument("--skip-receipt-name", action="store_true", help="skip auto input of receipt addressee name")
    ap.add_argument("--enable-rakuten", dest="enable_rakuten", action="store_const", const=True, default=None, help="enable Rakuten download")
    ap.add_argument("--rakuten-orders-url", dest="rakuten_orders_url", help="Rakuten order history URL")

    inter = ap.add_mutually_exclusive_group()
    inter.add_argument("--interactive", dest="interactive", action="store_const", const=True, default=None, help="allow auth handoff to user")
    inter.add_argument("--non-interactive", dest="interactive", action="store_const", const=False, default=None, help="fail fast on auth")

    head = ap.add_mutually_exclusive_group()
    head.add_argument("--headed", dest="headed", action="store_const", const=True, default=None, help="run browser headed")
    head.add_argument("--headless", dest="headed", action="store_const", const=False, default=None, help="run browser headless")
    ap.add_argument("--slow-mo-ms", dest="slow_mo_ms", type=int, help="slowMo in ms (default: 0)")

    ap.add_argument("--date-window-days", type=int, help="matching date window (default: 7)")
    ap.add_argument("--max-candidates-per-mf", type=int, help="max candidates per MF expense (default: 5)")
    ap.add_argument("--skip-amazon", action="store_true", help="skip Amazon download step")
    ap.add_argument("--skip-rakuten", action="store_true", help="skip Rakuten download step")
    ap.add_argument("--skip-mfcloud", action="store_true", help="skip MF Cloud extract step")
    ap.add_argument("--skip-reconcile", action="store_true", help="skip reconcile step")
    ap.add_argument("--print-list", action="store_true", help="generate print list after downloads")
    ap.add_argument("--print-sources", help="comma-separated sources for print list (amazon,rakuten,mfcloud)")
    ap.add_argument("--preflight", action="store_true", help="login and refresh MF linked services before running steps")

    args = ap.parse_args(argv)
    raw = _read_json_input(args.input)
    rc, year, month = _parse_config(args, raw)
    out = execute_pipeline(
        args=args,
        rc=rc,
        year=year,
        month=month,
        render_monthly_thread=render_monthly_thread,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001 - CLI boundary
        debug = os.environ.get("AX_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
        err: dict[str, Any] = {"status": "error", "error": {"type": type(e).__name__, "message": str(e)}}
        if debug:
            err["error"]["traceback"] = traceback.format_exc()
        print(json.dumps(err, ensure_ascii=False, indent=2), file=sys.stdout)
        raise SystemExit(1)

#!/usr/bin/env python3
"""
Run the skill with a standardized JSON interface.

Input (stdin or --input):
{
  "config": {
    "interactive": false,
    "dry_run": false,
    "output_dir": null,
    "sessions": {
      "amazon_storage_state": null,
      "mfcloud_storage_state": null
    },
    "urls": {
      "amazon_orders": "https://www.amazon.co.jp/gp/your-account/order-history",
      "mfcloud_expense_list": null
    },
    "playwright": {
      "headed": true,
      "slow_mo_ms": 0
    },
    "matching": {
      "date_window_days": 7,
      "max_candidates_per_mf": 5
    },
    "monthly_notes": "出張多め・特定PJ集中"
  },
  "params": {
    "year": 2026,
    "month": 1
  }
}
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import calendar
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import traceback
from typing import Any


def _ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _read_json_input(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    if sys.stdin and not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    return {}


def _coalesce(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def _as_int(value: Any, *, name: str) -> int:
    if value is None:
        raise ValueError(f"Missing required integer: {name}")
    try:
        return int(value)
    except Exception as e:  # noqa: BLE001 - CLI boundary
        raise ValueError(f"Invalid integer for {name}: {value!r}") from e


def _ym_default(now: date | None = None) -> tuple[int, int]:
    d = now or date.today()
    if d.month == 1:
        return d.year - 1, 12
    return d.year, d.month - 1


def _ym_to_dirname(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _default_storage_state(name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in name)
    return _ax_home() / "sessions" / f"{safe}.storage.json"


def _run_node_playwright_script(
    *,
    script_path: Path,
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    npx = None
    for name in ("npx.cmd", "npx.exe", "npx"):
        npx = shutil.which(name)
        if npx:
            break
    if not npx:
        raise FileNotFoundError("npx not found in PATH. Please install Node.js/npm and ensure npx is available.")
    cmd = [npx, "--yes", "-p", "playwright", "node", str(script_path), *args]
    res = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            "Node script failed:\n"
            f"cmd: {cmd}\n"
            f"exit: {res.returncode}\n"
            f"stdout:\n{res.stdout}\n"
            f"stderr:\n{res.stderr}\n"
        )
    try:
        return json.loads(res.stdout) if res.stdout.strip() else {}
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Node script returned non-JSON stdout:\n{res.stdout}") from e


@dataclass(frozen=True)
class RunConfig:
    dry_run: bool
    output_root: Path
    amazon_orders_url: str
    mfcloud_expense_list_url: str
    amazon_storage_state: Path
    mfcloud_storage_state: Path
    headed: bool
    slow_mo_ms: int
    date_window_days: int
    max_candidates_per_mf: int
    monthly_notes: str


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
    monthly_notes = _coalesce(args.monthly_notes, config.get("monthly_notes"))
    monthly_notes = str(monthly_notes).strip() if monthly_notes is not None else ""

    dry_run = bool(_coalesce(args.dry_run, config.get("dry_run", False)))

    amazon_orders_url = str(
        _coalesce(args.amazon_orders_url, urls.get("amazon_orders"), "https://www.amazon.co.jp/gp/your-account/order-history")
    )
    mfcloud_expense_list_url = _coalesce(args.mfcloud_expense_list_url, urls.get("mfcloud_expense_list"))
    if not mfcloud_expense_list_url:
        if dry_run:
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

    amazon_storage_state = Path(_coalesce(args.amazon_storage_state, sessions.get("amazon_storage_state")) or _default_storage_state("amazon"))
    mfcloud_storage_state = Path(
        _coalesce(args.mfcloud_storage_state, sessions.get("mfcloud_storage_state")) or _default_storage_state("mfcloud-expense")
    )

    headed = bool(_coalesce(args.headed, pw.get("headed", True)))
    slow_mo_ms = _as_int(_coalesce(args.slow_mo_ms, pw.get("slow_mo_ms", 0)), name="slow_mo_ms")
    date_window_days = _as_int(_coalesce(args.date_window_days, matching.get("date_window_days", 7)), name="date_window_days")
    max_candidates_per_mf = _as_int(
        _coalesce(args.max_candidates_per_mf, matching.get("max_candidates_per_mf", 5)), name="max_candidates_per_mf"
    )

    rc = RunConfig(
        dry_run=dry_run,
        output_root=output_root,
        amazon_orders_url=amazon_orders_url,
        mfcloud_expense_list_url=mfcloud_expense_list_url,
        amazon_storage_state=amazon_storage_state.expanduser().resolve(),
        mfcloud_storage_state=mfcloud_storage_state.expanduser().resolve(),
        headed=headed,
        slow_mo_ms=slow_mo_ms,
        date_window_days=date_window_days,
        max_candidates_per_mf=max_candidates_per_mf,
        monthly_notes=monthly_notes,
    )
    return rc, year, month


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_monthly_thread(
    *,
    template_path: Path,
    year: int,
    month: int,
    receipts_path: Path,
    reports_path: Path,
    notes: str,
) -> str:
    start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = date(year, month, last_day)
    replacements = {
        "{{YEAR}}": f"{year:04d}",
        "{{MONTH}}": f"{month:02d}",
        "{{RANGE_START}}": start.isoformat(),
        "{{RANGE_END}}": end.isoformat(),
        "{{NOTES}}": notes if notes else "なし",
        "{{RECEIPTS_PATH}}": str(receipts_path),
        "{{REPORTS_PATH}}": str(reports_path),
    }
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    else:
        template = (
            "# 月次処理スレッド\n\n"
            f"対象月：{year}年{month}月\n"
            f"対象期間：{start.isoformat()} ～ {end.isoformat()}\n"
            "対象ステータス：下書き / 未申請\n\n"
            "## 今月の前提・特記事項\n"
            "なし\n\n"
            "## レシート提供状況\n"
            f"- 保存場所：{receipts_path}\n"
            "- 形式：PDF\n\n"
            "## 今月の進め方\n"
            "- 基本方針：1明細=1レシート、金額/日付が一致しない場合は自動紐付けしない\n"
            "- 優先順位：完全一致 → 近似一致 → 要確認\n\n"
            "## 作業開始指示\n"
            "- Phase 1 (Scan) から開始\n"
        )
    for k, v in replacements.items():
        template = template.replace(k, v)
    return template


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="mfcloud-expense-receipt-reconcile runner")
    ap.add_argument("--input", help="path to input JSON (otherwise stdin)")

    ap.add_argument("--year", type=int, help="default: last month")
    ap.add_argument("--month", type=int, help="default: last month")
    ap.add_argument("--dry-run", dest="dry_run", action="store_const", const=True, default=None, help="skip browser and only reconcile from existing jsonl")
    ap.add_argument("--output-dir", dest="output_dir", help="override output_root")

    ap.add_argument("--amazon-orders-url", dest="amazon_orders_url", help="override Amazon order history URL")
    ap.add_argument("--mfcloud-expense-list-url", dest="mfcloud_expense_list_url", help="MF Cloud expense list URL (required)")

    ap.add_argument("--amazon-storage-state", dest="amazon_storage_state", help="path to amazon.storage.json")
    ap.add_argument("--mfcloud-storage-state", dest="mfcloud_storage_state", help="path to mfcloud-expense.storage.json")
    ap.add_argument("--notes", dest="monthly_notes", help="monthly notes for thread template")

    head = ap.add_mutually_exclusive_group()
    head.add_argument("--headed", dest="headed", action="store_const", const=True, default=None, help="run browser headed")
    head.add_argument("--headless", dest="headed", action="store_const", const=False, default=None, help="run browser headless")
    ap.add_argument("--slow-mo-ms", dest="slow_mo_ms", type=int, help="slowMo in ms (default: 0)")

    ap.add_argument("--date-window-days", type=int, help="matching date window (default: 7)")
    ap.add_argument("--max-candidates-per-mf", type=int, help="max candidates per MF expense (default: 5)")

    args = ap.parse_args(argv)

    raw = _read_json_input(args.input)
    rc, year, month = _parse_config(args, raw)

    output_root = _ensure_dir(rc.output_root)
    amazon_dir = _ensure_dir(output_root / "amazon")
    amazon_pdfs_dir = _ensure_dir(amazon_dir / "pdfs")
    mf_dir = _ensure_dir(output_root / "mfcloud")
    reports_dir = _ensure_dir(output_root / "reports")
    debug_dir = _ensure_dir(output_root / "debug")

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
            },
            "urls": {
                "amazon_orders": rc.amazon_orders_url,
                "mfcloud_expense_list": rc.mfcloud_expense_list_url,
            },
            "playwright": {"headed": rc.headed, "slow_mo_ms": rc.slow_mo_ms},
            "matching": {"date_window_days": rc.date_window_days, "max_candidates_per_mf": rc.max_candidates_per_mf},
            "monthly_notes": rc.monthly_notes,
        },
    )

    amazon_orders_jsonl = amazon_dir / "orders.jsonl"
    mf_expenses_jsonl = mf_dir / "expenses.jsonl"

    amazon_summary: dict[str, Any] = {"orders_jsonl": str(amazon_orders_jsonl), "pdfs_dir": str(amazon_pdfs_dir)}
    mf_summary: dict[str, Any] = {"expenses_jsonl": str(mf_expenses_jsonl)}

    if not rc.dry_run:
        scripts_dir = Path(__file__).parent

        amazon_out = _run_node_playwright_script(
            script_path=scripts_dir / "amazon_download.mjs",
            cwd=scripts_dir,
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
                "--headed" if rc.headed else "--headless",
                "--slow-mo-ms",
                str(rc.slow_mo_ms),
            ],
        )
        amazon_summary.update((amazon_out.get("data") if isinstance(amazon_out, dict) else None) or amazon_out)

        mf_out = _run_node_playwright_script(
            script_path=scripts_dir / "mfcloud_extract.mjs",
            cwd=scripts_dir,
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
                "--headed" if rc.headed else "--headless",
                "--slow-mo-ms",
                str(rc.slow_mo_ms),
            ],
        )
        mf_summary.update((mf_out.get("data") if isinstance(mf_out, dict) else None) or mf_out)

    scripts_dir = Path(__file__).parent
    rec_out_json = reports_dir / "missing_evidence_candidates.json"
    rec_out_csv = reports_dir / "missing_evidence_candidates.csv"
    monthly_thread_md = reports_dir / "monthly_thread.md"

    rec_cmd = [
        sys.executable,
        str(scripts_dir / "reconcile.py"),
        "--amazon-orders-jsonl",
        str(amazon_orders_jsonl),
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
    rec_res = subprocess.run(rec_cmd, cwd=str(scripts_dir), capture_output=True, text=True, check=False)
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

    template_path = Path(__file__).resolve().parent.parent / "assets" / "monthly_thread_template.md"
    monthly_thread = _render_monthly_thread(
        template_path=template_path,
        year=year,
        month=month,
        receipts_path=amazon_pdfs_dir,
        reports_path=reports_dir,
        notes=rc.monthly_notes,
    )
    monthly_thread_md.write_text(monthly_thread, encoding="utf-8")

    out = {
        "status": "success",
        "data": {
            "output_root": str(output_root),
            "amazon": amazon_summary,
            "mfcloud": mf_summary,
            "reports": {
                "missing_evidence_candidates_csv": str(rec_out_csv),
                "missing_evidence_candidates_json": str(rec_out_json),
                "monthly_thread_md": str(monthly_thread_md),
            },
            "reconcile": rec_json.get("data", rec_json),
        },
    }

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

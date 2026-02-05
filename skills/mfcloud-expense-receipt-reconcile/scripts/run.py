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
      "mfcloud_storage_state": null,
      "rakuten_storage_state": null
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
    "monthly_notes": "出張多め・特定PJ集中",
    "receipt_name": "株式会社ＨＩＧＨ－ＳＴＡＮＤＡＲＤ＆ＣＯ．",
    "receipt_name_fallback": "株式会社HIGH-STANDARD&CO.",
    "rakuten": {
      "enabled": false,
      "orders_url": "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order",
      "payment_method_allowlist": []
    }
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
from datetime import date, datetime
import calendar
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import threading
import traceback
from typing import Any


def _ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _read_json_input(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)

    if sys.stdin and not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    default_path = _ax_home() / "configs" / "mfcloud-expense-receipt-reconcile.json"
    if default_path.exists():
        with open(default_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {}


def _coalesce(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def _parse_csv_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in str(value).split(",") if s.strip()]


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


def _archive_existing_pdfs(pdfs_dir: Path, label: str) -> None:
    if not pdfs_dir.exists():
        return
    pdfs = list(pdfs_dir.glob("*.pdf"))
    if not pdfs:
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = pdfs_dir.parent / "_archive" / ts
    archive_dir.mkdir(parents=True, exist_ok=True)
    for p in pdfs:
        dest = archive_dir / p.name
        if dest.exists():
            stem = p.stem
            suffix = p.suffix
            i = 1
            while True:
                candidate = archive_dir / f"{stem}_{i}{suffix}"
                if not candidate.exists():
                    dest = candidate
                    break
                i += 1
        shutil.move(str(p), str(dest))
    print(f"[run] Archived existing {label} PDFs to {archive_dir}", flush=True)
    _cleanup_archives(pdfs_dir.parent / "_archive", keep=1, label=label)


def _cleanup_archives(archive_root: Path, keep: int, label: str) -> None:
    if keep < 1:
        keep = 1
    if not archive_root.exists():
        return
    dirs = [d for d in archive_root.iterdir() if d.is_dir()]
    if len(dirs) <= keep:
        return
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    for old in dirs[keep:]:
        try:
            shutil.rmtree(old)
        except Exception:
            continue
    print(f"[run] Cleaned old {label} archives (keep {keep})", flush=True)


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
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _drain(stream, sink, is_err: bool = False) -> None:
        if stream is None:
            return
        for raw in iter(stream.readline, b""):
            try:
                line = raw.decode("utf-8", errors="replace")
            except Exception:
                line = raw.decode(errors="replace")
            sink.append(line)
            if is_err:
                print(line.rstrip("\n"), file=sys.stderr, flush=True)
            else:
                print(line.rstrip("\n"), file=sys.stdout, flush=True)

    t_out = threading.Thread(target=_drain, args=(proc.stdout, stdout_lines))
    t_err = threading.Thread(target=_drain, args=(proc.stderr, stderr_lines, True))
    t_out.start()
    t_err.start()
    returncode = proc.wait()
    t_out.join()
    t_err.join()

    res_stdout = "".join(stdout_lines)
    res_stderr = "".join(stderr_lines)
    if returncode != 0:
        raise RuntimeError(
            "Node script failed:\n"
            f"cmd: {cmd}\n"
            f"exit: {returncode}\n"
            f"stdout:\n{res_stdout}\n"
            f"stderr:\n{res_stderr}\n"
        )
    stdout_str = res_stdout.strip()
    if not stdout_str:
        return {}
    # Accept logs before JSON: parse the last JSON-looking line.
    lines = [ln for ln in stdout_str.splitlines() if ln.strip()]
    for candidate in reversed(lines):
        if candidate.lstrip().startswith("{") and candidate.rstrip().endswith("}"):
            try:
                return json.loads(candidate)
            except Exception:
                continue
    try:
        return json.loads(stdout_str)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Node script returned non-JSON stdout:\n{res_stdout}") from e


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
    rakuten_payment_method_allowlist: list[str]


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
    receipt_name_fallback = _coalesce(args.receipt_name_fallback, config.get("receipt_name_fallback"), "株式会社HIGH-STANDARD&CO.")
    receipt_name_fallback = str(receipt_name_fallback).strip() if receipt_name_fallback is not None else ""

    dry_run = bool(_coalesce(args.dry_run, config.get("dry_run", False)))

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
    preflight = bool(getattr(args, "preflight", False))
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

    amazon_storage_state = Path(_coalesce(args.amazon_storage_state, sessions.get("amazon_storage_state")) or _default_storage_state("amazon"))
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
        _coalesce(args.max_candidates_per_mf, matching.get("max_candidates_per_mf", 5)), name="max_candidates_per_mf"
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
        rakuten_payment_method_allowlist=_parse_csv_list(_coalesce(args.rakuten_allow_payment_methods, rakuten_cfg.get("payment_method_allowlist"))),
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
    receipts_path: str | Path,
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
    ap.add_argument(
        "--rakuten-allow-payment-methods",
        dest="rakuten_allow_payment_methods",
        help="comma-separated allowlist for Rakuten payment methods",
    )

    inter = ap.add_mutually_exclusive_group()
    inter.add_argument("--interactive", dest="interactive", action="store_const", const=True, default=None, help="allow auth handoff to user")
    inter.add_argument(
        "--non-interactive", dest="interactive", action="store_const", const=False, default=None, help="fail fast on auth"
    )

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
    print(f"[run] start year={year} month={month} output_root={rc.output_root}", flush=True)

    output_root = _ensure_dir(rc.output_root)
    amazon_dir = _ensure_dir(output_root / "amazon")
    amazon_pdfs_dir = _ensure_dir(amazon_dir / "pdfs")
    rakuten_dir = _ensure_dir(output_root / "rakuten")
    rakuten_pdfs_dir = _ensure_dir(rakuten_dir / "pdfs")
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
                "rakuten_storage_state": str(rc.rakuten_storage_state),
            },
            "urls": {
                "amazon_orders": rc.amazon_orders_url,
                "mfcloud_accounts": rc.mfcloud_accounts_url,
                "mfcloud_expense_list": rc.mfcloud_expense_list_url,
            },
            "rakuten": {
                "enabled": rc.rakuten_enabled,
                "orders_url": rc.rakuten_orders_url,
                "payment_method_allowlist": rc.rakuten_payment_method_allowlist,
            },
            "playwright": {"headed": rc.headed, "slow_mo_ms": rc.slow_mo_ms},
            "matching": {"date_window_days": rc.date_window_days, "max_candidates_per_mf": rc.max_candidates_per_mf},
            "monthly_notes": rc.monthly_notes,
            "receipt_name": rc.receipt_name,
            "receipt_name_fallback": rc.receipt_name_fallback,
            "interactive": rc.interactive,
        },
    )

    amazon_orders_jsonl = amazon_dir / "orders.jsonl"
    rakuten_orders_jsonl = rakuten_dir / "orders.jsonl"
    mf_expenses_jsonl = mf_dir / "expenses.jsonl"

    amazon_summary: dict[str, Any] = {"orders_jsonl": str(amazon_orders_jsonl), "pdfs_dir": str(amazon_pdfs_dir)}
    rakuten_summary: dict[str, Any] = {"orders_jsonl": str(rakuten_orders_jsonl), "pdfs_dir": str(rakuten_pdfs_dir)}
    mf_summary: dict[str, Any] = {"expenses_jsonl": str(mf_expenses_jsonl)}

    if args.preflight:
        print("[run] Preflight start", flush=True)
        scripts_dir = Path(__file__).parent
        preflight_out = _run_node_playwright_script(
            script_path=scripts_dir / "preflight.mjs",
            cwd=scripts_dir,
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
        _write_json(
            reports_dir / "preflight.json",
            {
                "status": "success",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "data": preflight_data,
            },
        )
        print("[run] Preflight done", flush=True)
        print(json.dumps({"status": "success", "data": {"preflight": preflight_data}}, ensure_ascii=False, indent=2))
        return 0

    if rc.dry_run:
        print("[run] dry-run enabled: skipping browser downloads", flush=True)
    if not rc.dry_run:
        scripts_dir = Path(__file__).parent
        receipt_env = {
            "RECEIPT_NAME": rc.receipt_name,
            "RECEIPT_NAME_FALLBACK": rc.receipt_name_fallback,
        }

        if not args.skip_amazon:
            print("[run] Amazon download start", flush=True)
            _archive_existing_pdfs(amazon_pdfs_dir, "Amazon")
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
                    *(["--auth-handoff"] if rc.interactive else []),
                    "--headed" if rc.headed else "--headless",
                    "--slow-mo-ms",
                    str(rc.slow_mo_ms),
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
            _archive_existing_pdfs(rakuten_pdfs_dir, "Rakuten")
            if rakuten_orders_jsonl.exists():
                rakuten_orders_jsonl.unlink()
                print("[run] Deleted existing Rakuten orders.jsonl", flush=True)

            rakuten_allowlist = [str(v).strip() for v in rc.rakuten_payment_method_allowlist if str(v).strip()]
            rakuten_args = [
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
            ]
            if rakuten_allowlist:
                rakuten_args += ["--allow-payment-methods", ",".join(rakuten_allowlist)]
            rakuten_out = _run_node_playwright_script(
                script_path=scripts_dir / "rakuten_download.mjs",
                cwd=scripts_dir,
                args=rakuten_args,
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

    scripts_dir = Path(__file__).parent
    rec_out_json = reports_dir / "missing_evidence_candidates.json"
    rec_out_csv = reports_dir / "missing_evidence_candidates.csv"
    monthly_thread_md = reports_dir / "monthly_thread.md"
    exclude_orders_json = reports_dir / "exclude_orders.json"

    rec_json = {}
    if not args.skip_reconcile:
        print("[run] Reconcile start", flush=True)
        if not amazon_orders_jsonl.exists():
            raise RuntimeError("Missing amazon/orders.jsonl. Run Amazon download or provide existing data.")
        if not mf_expenses_jsonl.exists():
            raise RuntimeError("Missing mfcloud/expenses.jsonl. Run MF extract or provide existing data.")

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
        if rakuten_orders_jsonl.exists():
            rec_cmd += ["--rakuten-orders-jsonl", str(rakuten_orders_jsonl)]
        if exclude_orders_json.exists():
            rec_cmd += ["--exclude-orders-json", str(exclude_orders_json)]
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
        print("[run] Reconcile done", flush=True)
    else:
        print("[run] Reconcile skipped", flush=True)

    template_path = Path(__file__).resolve().parent.parent / "assets" / "monthly_thread_template.md"
    receipts_path = str(amazon_pdfs_dir)
    if rc.rakuten_enabled:
        receipts_path = f"{amazon_pdfs_dir}; {rakuten_pdfs_dir}"
    monthly_thread = _render_monthly_thread(
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
            str(scripts_dir / "collect_print.py"),
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
        print_res = subprocess.run(print_cmd, cwd=str(scripts_dir), capture_output=True, text=True, check=False)
        if print_res.returncode != 0:
            raise RuntimeError(
                "collect_print.py failed:\n"
                f"cmd: {print_cmd}\n"
                f"exit: {print_res.returncode}\n"
                f"stdout:\n{print_res.stdout}\n"
                f"stderr:\n{print_res.stderr}\n"
            )
        print("[run] Print list generation done", flush=True)

    out = {
        "status": "success",
        "data": {
            "output_root": str(output_root),
            "amazon": amazon_summary,
            "rakuten": rakuten_summary,
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

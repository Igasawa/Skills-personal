#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))
REPO_ROOT = SKILL_ROOT.parent.parent
SHARED_LIB_DIR = REPO_ROOT / "scripts" / "lib"
if str(SHARED_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_LIB_DIR))

from common import (  # noqa: E402
    ax_home as _ax_home,
    coalesce as _coalesce,
    default_storage_state as _default_storage_state,
    ensure_dir as _ensure_dir,
    load_order_exclusions as _load_exclusions,
    read_jsonl as _read_jsonl,
    ym_default as _ym_default,
    ym_to_dirname as _ym_to_dirname,
)
from run_core_playwright import run_node_playwright_script as _run_node_playwright_script  # noqa: E402
from shared_config import load_org_profile as _load_org_profile  # noqa: E402

DEFAULT_AMAZON_ORDERS_URL = "https://www.amazon.co.jp/gp/your-account/order-history"
DEFAULT_RAKUTEN_ORDERS_URL = "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order"
NON_ACTIONABLE_STATUS = {"out_of_month", "unknown_date", "gift_card"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _pick_non_empty_str(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        s = str(value).strip()
        if s:
            return s
    return ""


def _read_json_input(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    if path is None:
        default_path = _ax_home() / "configs" / "mfcloud-expense-receipt-reconcile.json"
        if default_path.exists():
            with open(default_path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
    return {}


def _parse_date_from_filename(name: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})_", name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_date(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    s = str(value).strip().replace("/", "-")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def _collect_local_pdfs(pdfs_dir: Path, year: int, month: int) -> list[dict[str, Any]]:
    if not pdfs_dir.exists():
        return []
    files = []
    for p in pdfs_dir.glob("*.pdf"):
        ym = _parse_date_from_filename(p.name)
        if ym and ym == (year, month):
            files.append({"path": str(p), "source": pdfs_dir.parent.name})
    return files


def _collect_orders_pdfs(
    orders_jsonl: Path,
    year: int,
    month: int,
    source: str,
    exclusions: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    rows = _read_jsonl(orders_jsonl)
    files: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _iter_pdf_paths(row: dict[str, Any]) -> list[str]:
        out: list[str] = []
        primary = str(row.get("pdf_path") or "").strip()
        if primary:
            out.append(primary)
        docs = row.get("documents")
        if isinstance(docs, list):
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                p = str(doc.get("pdf_path") or "").strip()
                if p:
                    out.append(p)
        return out

    for r in rows:
        if r.get("include") is False:
            continue
        status = str(r.get("status") or "").strip()
        if status in ("out_of_month", "unknown_date", "error", "no_receipt", "gift_card"):
            continue
        order_id = str(r.get("order_id") or "").strip()
        if order_id and (source, order_id) in exclusions:
            continue
        pdf_paths = _iter_pdf_paths(r)
        if not pdf_paths:
            continue
        ym = _parse_date(r.get("order_date") or r.get("date"))
        for pdf_path in pdf_paths:
            entry_ym = ym
            if entry_ym is None:
                entry_ym = _parse_date_from_filename(Path(pdf_path).name)
            if entry_ym != (year, month):
                continue
            if pdf_path in seen:
                continue
            seen.add(pdf_path)
            files.append({"path": pdf_path, "source": source, "order_id": order_id})
    return files


def _collect_mfcloud_attachments(attachments_jsonl: Path, year: int, month: int) -> list[dict[str, Any]]:
    rows = _read_jsonl(attachments_jsonl)
    files: list[dict[str, Any]] = []
    for r in rows:
        ym = _parse_date(r.get("use_date"))
        if ym != (year, month):
            continue
        for f in r.get("files") or []:
            files.append({"path": f, "source": "mfcloud", "expense_id": r.get("expense_id")})
    return files


def _write_print_script(path: Path, files: list[str]) -> None:
    lines = [
        "$ErrorActionPreference = 'Continue'",
        "$files = @(",
    ]
    lines += [f'  "{p}"' for p in files]
    lines += [
        ")",
        "$opened = 0",
        "$failed = 0",
        "$missing = 0",
        "foreach ($f in $files) {",
        "  if (-not (Test-Path $f)) {",
        "    Write-Warning (\"missing: \" + $f)",
        "    $missing += 1",
        "    continue",
        "  }",
        "  try {",
        "    Start-Process -FilePath $f -ErrorAction Stop",
        "    $opened += 1",
        "  } catch {",
        "    Write-Warning (\"open_failed: \" + $f + \" :: \" + $_.Exception.Message)",
        "    $failed += 1",
        "  }",
        "  Start-Sleep -Milliseconds 300",
        "}",
        "Write-Output (\"print_summary opened=\" + $opened + \" failed=\" + $failed + \" missing=\" + $missing + \" total=\" + $files.Count)",
        "if ($failed -gt 0) {",
        "  exit 1",
        "}",
        "exit 0",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_orders_url(config: dict[str, Any], source: str, org_profile: dict[str, Any] | None = None) -> str:
    tenant = _as_dict(config.get("tenant"))
    tenant_urls = _as_dict(tenant.get("urls"))
    legacy_urls = _as_dict(config.get("urls"))
    org_profile = _as_dict(org_profile)
    org_urls = _as_dict(org_profile.get("urls"))
    if source == "amazon":
        return _pick_non_empty_str(
            tenant_urls.get("amazon_orders"),
            legacy_urls.get("amazon_orders"),
            org_urls.get("amazon_orders"),
            DEFAULT_AMAZON_ORDERS_URL,
        )
    if source == "rakuten":
        rakuten_cfg = _as_dict(config.get("rakuten"))
        return _pick_non_empty_str(
            tenant_urls.get("rakuten_orders"),
            rakuten_cfg.get("orders_url"),
            legacy_urls.get("rakuten_orders"),
            org_urls.get("rakuten_orders"),
            DEFAULT_RAKUTEN_ORDERS_URL,
        )
    return ""


def _resolve_receipt_env(config: dict[str, Any], org_profile: dict[str, Any] | None = None) -> dict[str, str]:
    tenant = _as_dict(config.get("tenant"))
    receipt_cfg = _as_dict(tenant.get("receipt"))
    org_profile = _as_dict(org_profile)
    org_organization = _as_dict(org_profile.get("organization"))
    org_receipt = _as_dict(org_organization.get("receipt"))

    receipt_name = _pick_non_empty_str(receipt_cfg.get("name"), config.get("receipt_name"), org_receipt.get("name"))
    receipt_name_fallback = _pick_non_empty_str(
        receipt_cfg.get("name_fallback"),
        config.get("receipt_name_fallback"),
        org_receipt.get("name_fallback"),
    )
    env: dict[str, str] = {}
    if receipt_name:
        env["RECEIPT_NAME"] = receipt_name
    if receipt_name_fallback:
        env["RECEIPT_NAME_FALLBACK"] = receipt_name_fallback
    return env


def _collect_missing_shortcut_orders(
    orders_jsonl: Path,
    year: int,
    month: int,
    source: str,
    exclusions: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    rows = _read_jsonl(orders_jsonl)
    pending: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _iter_pdf_paths(row: dict[str, Any]) -> list[str]:
        out: list[str] = []
        primary = str(row.get("pdf_path") or "").strip()
        if primary:
            out.append(primary)
        docs = row.get("documents")
        if isinstance(docs, list):
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                p = str(doc.get("pdf_path") or "").strip()
                if p:
                    out.append(p)
        return out

    for r in rows:
        if r.get("include") is False:
            continue
        status = str(r.get("status") or "").strip()
        if status in NON_ACTIONABLE_STATUS:
            continue

        order_id = str(r.get("order_id") or "").strip()
        if order_id and (source, order_id) in exclusions:
            continue

        ym = _parse_date(r.get("order_date") or r.get("date"))
        if ym != (year, month):
            continue

        existing_pdf = False
        for pdf_path in _iter_pdf_paths(r):
            if Path(pdf_path).exists():
                existing_pdf = True
                break
        if existing_pdf:
            continue

        detail_url = str(r.get("detail_url") or "").strip()
        receipt_url = str(r.get("receipt_url") or "").strip()
        if not (detail_url or receipt_url):
            continue

        key = (order_id or detail_url or receipt_url, status)
        if key in seen:
            continue
        seen.add(key)
        pending.append(
            {
                "order_id": order_id,
                "status": status,
                "detail_url": detail_url,
                "receipt_url": receipt_url,
            }
        )
    return pending


def _attempt_source_shortcut_download(
    *,
    source: str,
    year: int,
    month: int,
    output_root: Path,
    config: dict[str, Any],
    org_profile: dict[str, Any] | None,
    exclusions: set[tuple[str, str]],
    interactive: bool,
    headed: bool,
) -> dict[str, Any]:
    orders_jsonl = output_root / source / "orders.jsonl"
    pdfs_dir = output_root / source / "pdfs"
    if not orders_jsonl.exists():
        return {"pending": 0, "attempted": False, "downloaded": False}

    pending = _collect_missing_shortcut_orders(orders_jsonl, year, month, source, exclusions)
    if not pending:
        return {"pending": 0, "attempted": False, "downloaded": False}

    sessions = config.get("sessions") if isinstance(config.get("sessions"), dict) else {}
    storage_key = "amazon_storage_state" if source == "amazon" else "rakuten_storage_state"
    storage_fallback = "amazon" if source == "amazon" else "rakuten"
    storage_state = Path(_coalesce(sessions.get(storage_key), _default_storage_state(storage_fallback))).expanduser().resolve()
    orders_url = _resolve_orders_url(config, source, org_profile=org_profile)
    debug_dir = _ensure_dir(output_root / "debug" / source / "print_hydrate")
    env = _resolve_receipt_env(config, org_profile=org_profile)

    before = len(_collect_orders_pdfs(orders_jsonl, year, month, source, exclusions))
    backup_path: Path | None = None
    if source == "rakuten" and orders_jsonl.exists():
        # Rakuten downloader skips already-listed detail_url rows, so clear the file for full retry.
        backup_path = orders_jsonl.with_suffix(".jsonl.print_retry.bak")
        shutil.copy2(orders_jsonl, backup_path)
        orders_jsonl.unlink(missing_ok=True)

    node_args = [
        "--storage-state",
        str(storage_state),
        "--orders-url",
        orders_url,
        "--out-jsonl",
        str(orders_jsonl),
        "--out-pdfs-dir",
        str(pdfs_dir),
        "--year",
        str(year),
        "--month",
        str(month),
        "--debug-dir",
        str(debug_dir),
        "--headed" if headed else "--headless",
        "--slow-mo-ms",
        "0",
    ]
    if interactive:
        node_args.append("--auth-handoff")
    if source == "amazon":
        node_args.append("--skip-receipt-name")

    script_name = "amazon_download.mjs" if source == "amazon" else "rakuten_download.mjs"
    try:
        _run_node_playwright_script(
            script_path=SCRIPT_DIR / script_name,
            cwd=SCRIPT_DIR,
            args=node_args,
            env=env,
        )
    except Exception as exc:  # noqa: BLE001
        if backup_path and backup_path.exists() and not orders_jsonl.exists():
            shutil.copy2(backup_path, orders_jsonl)
            backup_path.unlink(missing_ok=True)
        return {
            "pending": len(pending),
            "attempted": True,
            "downloaded": False,
            "error": str(exc),
        }
    if backup_path and backup_path.exists():
        backup_path.unlink(missing_ok=True)
    after = len(_collect_orders_pdfs(orders_jsonl, year, month, source, exclusions))
    return {
        "pending": len(pending),
        "attempted": True,
        "downloaded": True,
        "before_pdf_count": before,
        "after_pdf_count": after,
        "added_pdf_count": max(0, after - before),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Collect receipts and prepare bulk print")
    ap.add_argument("--input", help="path to input JSON (optional; default config in AX_HOME)")
    ap.add_argument("--year", type=int, help="default: last month")
    ap.add_argument("--month", type=int, help="default: last month")
    ap.add_argument("--output-dir", help="override output_root")
    ap.add_argument("--download-mfcloud", action="store_true", help="download MF attachments before print (optional)")
    ap.add_argument("--include-mfcloud", action="store_true", help="include MF attachments in print list")
    ap.add_argument("--sources", help="comma-separated sources to include (amazon,rakuten,mfcloud)")
    ap.add_argument("--exclude-orders-json", help="path to exclude orders json (optional)")
    ap.add_argument("--mfcloud-storage-state", help="path to mfcloud-expense.storage.json")
    ap.add_argument("--interactive", action="store_true", help="allow auth handoff during MF download")
    ap.add_argument("--headed", action="store_true", help="run browser headed during MF download")
    ap.add_argument(
        "--skip-shortcut-download",
        action="store_true",
        help="skip auto-retry download for non-excluded orders with shortcuts and missing PDFs",
    )

    args = ap.parse_args(argv)
    raw = _read_json_input(args.input)
    config = raw.get("config") if isinstance(raw, dict) else {}
    if not isinstance(config, dict):
        config = {}
    org_profile, _org_profile_path = _load_org_profile(ax_home=_ax_home())

    default_year, default_month = _ym_default()
    year = int(_coalesce(args.year, (raw.get("params") or {}).get("year"), default_year))
    month = int(_coalesce(args.month, (raw.get("params") or {}).get("month"), default_month))

    output_root = Path(
        _coalesce(args.output_dir, config.get("output_dir"))
        or (_ax_home() / "artifacts" / "mfcloud-expense-receipt-reconcile" / _ym_to_dirname(year, month))
    ).expanduser()
    output_root = output_root.resolve()

    amazon_pdfs = output_root / "amazon" / "pdfs"
    rakuten_pdfs = output_root / "rakuten" / "pdfs"
    mf_dir = output_root / "mfcloud"
    reports_dir = _ensure_dir(output_root / "reports")
    debug_dir = _ensure_dir(output_root / "debug" / "mfcloud")

    expenses_jsonl = mf_dir / "expenses.jsonl"
    attachments_dir = mf_dir / "attachments"
    attachments_jsonl = mf_dir / "attachments.jsonl"
    exclusions_path = Path(args.exclude_orders_json) if args.exclude_orders_json else (reports_dir / "exclude_orders.json")
    exclusions = _load_exclusions(exclusions_path)

    if args.download_mfcloud:
        storage_state = Path(_coalesce(args.mfcloud_storage_state, (config.get("sessions") or {}).get("mfcloud_storage_state")) or _default_storage_state("mfcloud-expense"))
        scripts_dir = Path(__file__).parent
        headed = bool(args.headed or args.interactive)
        node_args = [
            "--storage-state",
            str(storage_state.expanduser().resolve()),
            "--expenses-jsonl",
            str(expenses_jsonl),
            "--out-dir",
            str(attachments_dir),
            "--out-jsonl",
            str(attachments_jsonl),
            "--year",
            str(year),
            "--month",
            str(month),
            "--debug-dir",
            str(debug_dir),
            "--headed" if headed else "--headless",
        ]
        if args.interactive:
            node_args.append("--auth-handoff")
        _run_node_playwright_script(
            script_path=scripts_dir / "mfcloud_download_attachments.mjs",
            cwd=scripts_dir,
            args=node_args,
        )

    sources = set(s.strip() for s in (args.sources or "").split(",") if s.strip())
    include_amazon = not sources or "amazon" in sources
    include_rakuten = not sources or "rakuten" in sources
    include_mfcloud = not sources or "mfcloud" in sources

    hydrate_result: dict[str, Any] = {}
    if not args.skip_shortcut_download:
        if include_amazon:
            hydrate_result["amazon"] = _attempt_source_shortcut_download(
                source="amazon",
                year=year,
                month=month,
                output_root=output_root,
                config=config,
                org_profile=org_profile,
                exclusions=exclusions,
                interactive=bool(args.interactive),
                headed=bool(args.headed or args.interactive),
            )
        if include_rakuten:
            hydrate_result["rakuten"] = _attempt_source_shortcut_download(
                source="rakuten",
                year=year,
                month=month,
                output_root=output_root,
                config=config,
                org_profile=org_profile,
                exclusions=exclusions,
                interactive=bool(args.interactive),
                headed=bool(args.headed or args.interactive),
            )

    files = []
    if include_amazon:
        amazon_orders = output_root / "amazon" / "orders.jsonl"
        if amazon_orders.exists():
            files += _collect_orders_pdfs(amazon_orders, year, month, "amazon", exclusions)
        else:
            files += _collect_local_pdfs(amazon_pdfs, year, month)
    if include_rakuten:
        rakuten_orders = output_root / "rakuten" / "orders.jsonl"
        if rakuten_orders.exists():
            files += _collect_orders_pdfs(rakuten_orders, year, month, "rakuten", exclusions)
        else:
            files += _collect_local_pdfs(rakuten_pdfs, year, month)
    if args.include_mfcloud or include_mfcloud:
        files += _collect_mfcloud_attachments(attachments_jsonl, year, month)

    deduped: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for f in files:
        path = f.get("path")
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        deduped.append(f)
    files = deduped

    file_paths = [f["path"] for f in files]
    manifest = {
        "year": year,
        "month": month,
        "count": len(files),
        "files": files,
        "shortcut_download": hydrate_result,
    }
    manifest_path = reports_dir / "print_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    list_path = reports_dir / "print_list.txt"
    list_path.write_text("\n".join(file_paths) + ("\n" if file_paths else ""), encoding="utf-8")

    # Keep the legacy script for backward compatibility, but source-specific
    # manifests/lists are the primary input for bulk print execution.
    ps1_path = reports_dir / "print_all.ps1"
    _write_print_script(ps1_path, file_paths)

    for source_name, include_flag in (("amazon", include_amazon), ("rakuten", include_rakuten)):
        if not include_flag:
            continue
        source_files = [f for f in files if str(f.get("source") or "").strip() == source_name]
        source_file_paths = [f["path"] for f in source_files]
        source_manifest = {
            "year": year,
            "month": month,
            "source": source_name,
            "count": len(source_files),
            "files": source_files,
            "shortcut_download": hydrate_result.get(source_name),
        }
        source_manifest_path = reports_dir / f"print_manifest.{source_name}.json"
        source_manifest_path.write_text(json.dumps(source_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        source_list_path = reports_dir / f"print_list.{source_name}.txt"
        source_list_path.write_text(
            "\n".join(source_file_paths) + ("\n" if source_file_paths else ""),
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "status": "success",
                "data": {
                    "output_root": str(output_root),
                    "print_manifest": str(manifest_path),
                    "print_list": str(list_path),
                    "print_script": str(ps1_path),
                    "count": len(files),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

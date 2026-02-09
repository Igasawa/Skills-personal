#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_core_playwright import run_node_playwright_script  # noqa: E402
from manual_receipt_import import PROVIDER_KEYS, import_manual_receipts_for_month  # noqa: E402

PROVIDER_ORDER: tuple[str, ...] = ("chatgpt", "claude", "gamma", "aquavoice")
PROVIDER_SCRIPT_MAP: dict[str, str] = {
    "chatgpt": "provider_download_chatgpt.mjs",
    "claude": "provider_download_claude.mjs",
    "gamma": "provider_download_gamma.mjs",
    "aquavoice": "provider_download_aquavoice.mjs",
}
EMPTY_STORAGE_STATE: dict[str, Any] = {"cookies": [], "origins": []}


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ensure_storage_state_file(path: Path) -> tuple[Path, bool]:
    candidate = Path(path).expanduser()
    if candidate.exists():
        return candidate, False
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(json.dumps(EMPTY_STORAGE_STATE, ensure_ascii=False), encoding="utf-8")
    return candidate, True


def run_provider_downloads(
    *,
    year: int,
    month: int,
    output_root: Path,
    out_json: Path,
    storage_states: dict[str, Path],
    auth_handoff: bool,
    headed: bool,
    slow_mo_ms: int,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    reports_dir = output_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    debug_root = output_root / "debug" / "providers"
    debug_root.mkdir(parents=True, exist_ok=True)
    manual_inbox_root = output_root / "manual" / "inbox"
    manual_inbox_root.mkdir(parents=True, exist_ok=True)

    provider_results: dict[str, dict[str, Any]] = {}
    downloaded_total = 0

    for provider in PROVIDER_ORDER:
        script_name = PROVIDER_SCRIPT_MAP[provider]
        script_path = SCRIPT_DIR / script_name
        provider_out_dir = manual_inbox_root / provider
        provider_debug_dir = debug_root / provider
        provider_out_dir.mkdir(parents=True, exist_ok=True)
        provider_debug_dir.mkdir(parents=True, exist_ok=True)

        storage_state = storage_states.get(provider)
        if not storage_state:
            provider_results[provider] = {
                "status": "failed",
                "reason": "storage_state_not_provided",
                "storage_state": str(storage_state or ""),
                "out_dir": str(provider_out_dir),
                "downloaded_count": 0,
            }
            continue
        storage_state_initialized = False
        try:
            storage_state, storage_state_initialized = _ensure_storage_state_file(Path(storage_state))
        except Exception as exc:
            provider_results[provider] = {
                "status": "failed",
                "reason": f"storage_state_init_failed: {exc}",
                "storage_state": str(storage_state),
                "out_dir": str(provider_out_dir),
                "downloaded_count": 0,
            }
            continue

        args = [
            "--storage-state",
            str(storage_state),
            "--year",
            str(year),
            "--month",
            str(month),
            "--out-dir",
            str(provider_out_dir),
            "--debug-dir",
            str(provider_debug_dir),
            "--slow-mo-ms",
            str(max(0, int(slow_mo_ms))),
        ]
        if auth_handoff:
            args.append("--auth-handoff")
        if headed:
            args.append("--headed")
        else:
            args.append("--headless")

        try:
            raw = run_node_playwright_script(
                script_path=script_path,
                cwd=SCRIPT_DIR,
                args=args,
            )
            data = _ensure_dict(raw.get("data") if isinstance(raw, dict) else raw)
            downloaded_count = int(data.get("downloaded_count") or 0)
            downloaded_total += downloaded_count
            provider_results[provider] = {
                "status": "success",
                "storage_state": str(storage_state),
                "storage_state_initialized": storage_state_initialized,
                "out_dir": str(provider_out_dir),
                "downloaded_count": downloaded_count,
                "candidates_found": int(data.get("candidates_found") or 0),
                "downloaded_files": data.get("downloaded_files") if isinstance(data.get("downloaded_files"), list) else [],
                "visited_urls": data.get("visited_urls") if isinstance(data.get("visited_urls"), list) else [],
                "final_url": str(data.get("final_url") or ""),
            }
        except Exception as exc:
            provider_results[provider] = {
                "status": "failed",
                "reason": str(exc),
                "storage_state": str(storage_state),
                "storage_state_initialized": storage_state_initialized,
                "out_dir": str(provider_out_dir),
                "downloaded_count": 0,
            }

    import_status = "success"
    import_result: dict[str, Any] = {}
    try:
        imported = import_manual_receipts_for_month(
            output_root,
            year,
            month,
            provider_filter=set(PROVIDER_KEYS),
            ingestion_channel="provider_auto_download",
        )
        import_result = {
            "status": "ok",
            "found_files": int(imported.get("found_files") or imported.get("found_pdfs") or 0),
            "imported": int(imported.get("imported") or 0),
            "imported_missing_amount": int(imported.get("imported_missing_amount") or 0),
            "skipped_duplicates": int(imported.get("skipped_duplicates") or 0),
            "failed": int(imported.get("failed") or 0),
            "provider_counts": imported.get("provider_counts") if isinstance(imported.get("provider_counts"), dict) else {},
            "orders_jsonl": str(imported.get("orders_jsonl") or ""),
            "provider_report_json": str(imported.get("provider_report_json") or ""),
            "report_json": str(imported.get("report_json") or ""),
        }
    except Exception as exc:  # noqa: BLE001
        import_status = "failed"
        import_result = {"status": "failed", "reason": str(exc)}

    failed_providers = [provider for provider, result in provider_results.items() if str(result.get("status")) != "success"]
    imported_count = int(import_result.get("imported") or 0)

    overall_status = "success"
    if failed_providers or import_status != "success":
        if downloaded_total > 0 or imported_count > 0:
            overall_status = "partial_success"
        else:
            overall_status = "failed"

    payload: dict[str, Any] = {
        "status": overall_status,
        "data": {
            "ym": f"{year:04d}-{month:02d}",
            "output_root": str(output_root),
            "result_json": str(out_json),
            "downloaded_total": downloaded_total,
            "imported": imported_count,
            "failed_providers": failed_providers,
            "providers": provider_results,
            "import_result": import_result,
        },
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download SaaS provider receipts and import into manual/orders.jsonl")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--chatgpt-storage-state", required=True)
    ap.add_argument("--claude-storage-state", required=True)
    ap.add_argument("--gamma-storage-state", required=True)
    ap.add_argument("--aquavoice-storage-state", required=True)
    ap.add_argument("--auth-handoff", action="store_true")
    headed_group = ap.add_mutually_exclusive_group()
    headed_group.add_argument("--headed", dest="headed", action="store_const", const=True, default=None)
    headed_group.add_argument("--headless", dest="headed", action="store_const", const=False)
    ap.add_argument("--slow-mo-ms", type=int, default=0)
    args = ap.parse_args(argv)

    if args.month < 1 or args.month > 12:
        raise ValueError("month must be between 1 and 12.")

    storage_states = {
        "chatgpt": Path(args.chatgpt_storage_state).expanduser(),
        "claude": Path(args.claude_storage_state).expanduser(),
        "gamma": Path(args.gamma_storage_state).expanduser(),
        "aquavoice": Path(args.aquavoice_storage_state).expanduser(),
    }

    payload = run_provider_downloads(
        year=int(args.year),
        month=int(args.month),
        output_root=Path(args.output_root).expanduser(),
        out_json=Path(args.out_json).expanduser(),
        storage_states=storage_states,
        auth_handoff=bool(args.auth_handoff),
        headed=True if args.headed is None else bool(args.headed),
        slow_mo_ms=int(args.slow_mo_ms or 0),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

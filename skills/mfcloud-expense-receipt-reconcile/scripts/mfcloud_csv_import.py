#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_core_playwright import run_node_playwright_script  # noqa: E402

ALLOWED_SUFFIXES = {".csv"}
DEFAULT_IMPORT_URL = "https://expense.moneyforward.com/import_transactions/new"


def _iter_csv_files(inbox_dir: Path) -> list[Path]:
    if not inbox_dir.exists():
        return []
    files: list[Path] = []
    for path in sorted(inbox_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        files.append(path.resolve())
    return files


def _safe_move_to_dir(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    candidate = dest_dir / src.name
    if not candidate.exists():
        shutil.move(str(src), str(candidate))
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        alt = dest_dir / f"{stem}_{index}{suffix}"
        if not alt.exists():
            shutil.move(str(src), str(alt))
            return alt
        index += 1


def run_mf_csv_import(
    *,
    storage_state: Path,
    import_url: str,
    inbox_dir: Path,
    out_json: Path,
    debug_dir: Path,
    auth_handoff: bool,
    headed: bool,
    slow_mo_ms: int,
) -> dict[str, Any]:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)

    files = _iter_csv_files(inbox_dir)
    files_json = out_json.parent / "mf_csv_import_files.json"
    files_json.write_text(
        json.dumps({"files": [str(path) for path in files]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not files:
        payload = {
            "status": "ok",
            "import_url": str(import_url),
            "inbox_dir": str(inbox_dir),
            "files_found": 0,
            "queued_count": 0,
            "submitted_count": 0,
            "submitted_files": [],
            "archived_dir": "",
            "result_json": str(out_json),
        }
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    node_out = run_node_playwright_script(
        script_path=SCRIPT_DIR / "mfcloud_csv_import.mjs",
        cwd=SCRIPT_DIR,
        args=[
            "--storage-state",
            str(storage_state),
            "--import-url",
            str(import_url),
            "--files-json",
            str(files_json),
            "--debug-dir",
            str(debug_dir),
            *(["--auth-handoff"] if auth_handoff else []),
            "--headed" if headed else "--headless",
            "--slow-mo-ms",
            str(max(0, int(slow_mo_ms))),
        ],
    )
    node_data = node_out.get("data") if isinstance(node_out, dict) and isinstance(node_out.get("data"), dict) else node_out
    if not isinstance(node_data, dict):
        raise RuntimeError(f"Unexpected mfcloud_csv_import output: {node_out!r}")

    submitted_files = [Path(str(path)).resolve() for path in (node_data.get("submitted_files") or []) if str(path).strip()]
    archive_dir = inbox_dir / "_imported" / datetime.now().strftime("%Y%m%d_%H%M%S")
    moved_rows: list[dict[str, Any]] = []
    for src in submitted_files:
        if not src.exists():
            continue
        moved = _safe_move_to_dir(src, archive_dir)
        moved_rows.append({"from": str(src), "to": str(moved)})

    payload = {
        "status": "ok",
        "import_url": str(import_url),
        "inbox_dir": str(inbox_dir),
        "files_found": len(files),
        "queued_count": int(node_data.get("queued_count") or 0),
        "submitted_count": int(node_data.get("submitted_count") or 0),
        "submitted_files": [str(path) for path in submitted_files],
        "moved_rows": moved_rows,
        "archived_dir": str(archive_dir) if moved_rows else "",
        "result_json": str(out_json),
        "node_result": node_data,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MF Cloud transport CSV import runner")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--storage-state", required=True)
    ap.add_argument("--import-url", default=DEFAULT_IMPORT_URL)
    ap.add_argument("--inbox-dir", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--debug-dir", required=True)
    ap.add_argument("--auth-handoff", action="store_true")
    headed_group = ap.add_mutually_exclusive_group()
    headed_group.add_argument("--headed", dest="headed", action="store_const", const=True, default=None)
    headed_group.add_argument("--headless", dest="headed", action="store_const", const=False)
    ap.add_argument("--slow-mo-ms", type=int, default=0)
    args = ap.parse_args(argv)

    if args.month < 1 or args.month > 12:
        raise ValueError("month must be between 1 and 12.")
    headed = True if args.headed is None else bool(args.headed)

    result = run_mf_csv_import(
        storage_state=Path(args.storage_state).expanduser(),
        import_url=str(args.import_url or DEFAULT_IMPORT_URL),
        inbox_dir=Path(args.inbox_dir).expanduser(),
        out_json=Path(args.out_json).expanduser(),
        debug_dir=Path(args.debug_dir).expanduser(),
        auth_handoff=bool(args.auth_handoff),
        headed=headed,
        slow_mo_ms=int(args.slow_mo_ms or 0),
    )
    print(json.dumps({"status": "success", "data": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

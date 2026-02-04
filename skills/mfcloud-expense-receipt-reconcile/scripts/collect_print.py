#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
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
    if path is None:
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


def _run_node_playwright_script(*, script_path: Path, args: list[str], cwd: Path) -> dict[str, Any]:
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


def _parse_date_from_filename(name: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})_", name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            out.append(json.loads(s))
    return out


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
        "foreach ($f in $files) {",
        "  if (Test-Path $f) {",
        "    Start-Process -FilePath $f -Verb Print",
        "    Start-Sleep -Milliseconds 300",
        "  }",
        "}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Collect receipts and prepare bulk print")
    ap.add_argument("--input", help="path to input JSON (optional; default config in AX_HOME)")
    ap.add_argument("--year", type=int, help="default: last month")
    ap.add_argument("--month", type=int, help="default: last month")
    ap.add_argument("--output-dir", help="override output_root")
    ap.add_argument("--download-mfcloud", action="store_true", help="download MF attachments before print (optional)")
    ap.add_argument("--include-mfcloud", action="store_true", help="include MF attachments in print list")
    ap.add_argument("--mfcloud-storage-state", help="path to mfcloud-expense.storage.json")
    ap.add_argument("--interactive", action="store_true", help="allow auth handoff during MF download")
    ap.add_argument("--headed", action="store_true", help="run browser headed during MF download")

    args = ap.parse_args(argv)
    raw = _read_json_input(args.input)
    config = raw.get("config") if isinstance(raw, dict) else {}

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

    files = []
    files += _collect_local_pdfs(amazon_pdfs, year, month)
    files += _collect_local_pdfs(rakuten_pdfs, year, month)
    if args.include_mfcloud:
        files += _collect_mfcloud_attachments(attachments_jsonl, year, month)

    file_paths = [f["path"] for f in files]
    manifest = {
        "year": year,
        "month": month,
        "count": len(files),
        "files": files,
    }
    manifest_path = reports_dir / "print_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    list_path = reports_dir / "print_list.txt"
    list_path.write_text("\n".join(file_paths) + ("\n" if file_paths else ""), encoding="utf-8")

    ps1_path = reports_dir / "print_all.ps1"
    _write_print_script(ps1_path, file_paths)

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

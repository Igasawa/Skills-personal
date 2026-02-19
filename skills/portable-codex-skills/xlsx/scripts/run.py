#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Sequence

DEFAULT_TIMEOUT_SECONDS = 300
MIN_TIMEOUT_SECONDS = 5
MAX_TIMEOUT_SECONDS = 1800


def _resolve_timeout(value: int | None) -> int:
    try:
        parsed = int(value or DEFAULT_TIMEOUT_SECONDS)
    except Exception:
        parsed = DEFAULT_TIMEOUT_SECONDS
    if parsed < MIN_TIMEOUT_SECONDS:
        return MIN_TIMEOUT_SECONDS
    if parsed > MAX_TIMEOUT_SECONDS:
        return MAX_TIMEOUT_SECONDS
    return parsed


def _normalize_passthrough(value: Sequence[str]) -> list[str]:
    args = [str(item) for item in value]
    if args and args[0] == "--":
        return args[1:]
    return args


def _check_module(name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(name)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _self_check(skill_root: Path) -> int:
    ok = True

    recalc = skill_root / "recalc.py"
    if recalc.exists():
        print(f"recalc.py: {recalc}")
    else:
        print(f"recalc.py: missing ({recalc})")
        ok = False

    for module_name in ("openpyxl", "pandas"):
        mod_ok, detail = _check_module(module_name)
        print(f"python module {module_name}: {'ok' if mod_ok else 'missing'}")
        if not mod_ok:
            print(f"  detail: {detail}")
            ok = False

    soffice = shutil.which("soffice")
    print(f"soffice: {soffice or 'not found'}")
    if not soffice:
        print("  note: recalc.py requires LibreOffice (soffice).")

    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="XLSX skill runner")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="validate runtime dependencies and tool availability",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="subprocess timeout in seconds",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["recalc"],
        help="runner command",
    )
    parser.add_argument(
        "command_args",
        nargs=argparse.REMAINDER,
        help="arguments forwarded to selected command",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    skill_root = Path(__file__).resolve().parents[1]

    if args.self_check:
        return _self_check(skill_root)

    if args.command != "recalc":
        parser.print_help()
        return 0

    forwarded = _normalize_passthrough(args.command_args)
    if not forwarded:
        print("Usage: python scripts/run.py recalc <excel_file> [timeout_seconds]")
        return 2

    recalc_path = skill_root / "recalc.py"
    if not recalc_path.exists():
        print(f"recalc.py not found: {recalc_path}")
        return 2

    timeout_seconds = _resolve_timeout(args.timeout_seconds)
    cmd = [sys.executable, str(recalc_path), *forwarded]
    completed = subprocess.run(
        cmd,
        cwd=str(skill_root),
        check=False,
        timeout=timeout_seconds,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())

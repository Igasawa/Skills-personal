#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
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
    scripts_dir = skill_root / "scripts"
    ooxml_dir = skill_root / "ooxml" / "scripts"

    required_scripts = [
        scripts_dir / "thumbnail.py",
        scripts_dir / "inventory.py",
        scripts_dir / "rearrange.py",
        scripts_dir / "replace.py",
        ooxml_dir / "unpack.py",
        ooxml_dir / "pack.py",
        ooxml_dir / "validate.py",
    ]
    for script_path in required_scripts:
        exists = script_path.exists()
        print(f"{script_path.name}: {'ok' if exists else 'missing'}")
        if not exists:
            ok = False

    for module_name in ("pptx", "PIL", "defusedxml"):
        mod_ok, detail = _check_module(module_name)
        print(f"python module {module_name}: {'ok' if mod_ok else 'missing'}")
        if not mod_ok:
            print(f"  detail: {detail}")
            ok = False

    node_path = shutil.which("node")
    print(f"node: {node_path or 'not found'}")
    if not node_path:
        print("  note: html2pptx.js を使う場合は Node.js が必要です。")

    return 0 if ok else 1


def _command_map(skill_root: Path) -> dict[str, dict[str, Any]]:
    scripts_dir = skill_root / "scripts"
    ooxml_scripts_dir = skill_root / "ooxml" / "scripts"
    return {
        "thumbnail": {"runtime": "python", "path": scripts_dir / "thumbnail.py"},
        "inventory": {"runtime": "python", "path": scripts_dir / "inventory.py"},
        "rearrange": {"runtime": "python", "path": scripts_dir / "rearrange.py"},
        "replace": {"runtime": "python", "path": scripts_dir / "replace.py"},
        "unpack": {"runtime": "python", "path": ooxml_scripts_dir / "unpack.py"},
        "pack": {"runtime": "python", "path": ooxml_scripts_dir / "pack.py"},
        "validate": {"runtime": "python", "path": ooxml_scripts_dir / "validate.py"},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PPTX skill runner")
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
        choices=["thumbnail", "inventory", "rearrange", "replace", "unpack", "pack", "validate"],
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

    command = str(args.command or "").strip().lower()
    if not command:
        parser.print_help()
        return 0

    command_map = _command_map(skill_root)
    target = command_map.get(command)
    if target is None:
        print(f"Unknown command: {command}")
        return 2

    script_path = Path(str(target["path"]))
    if not script_path.exists():
        print(f"Command script not found: {script_path}")
        return 2

    forwarded = _normalize_passthrough(args.command_args)
    runtime = str(target["runtime"])
    if runtime == "python":
        cmd = [sys.executable, str(script_path), *forwarded]
    else:
        print(f"Unsupported runtime: {runtime}")
        return 2

    timeout_seconds = _resolve_timeout(args.timeout_seconds)
    completed = subprocess.run(
        cmd,
        cwd=str(skill_root),
        check=False,
        timeout=timeout_seconds,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())

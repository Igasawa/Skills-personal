#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
from typing import Sequence

DEFAULT_TIMEOUT_SECONDS = 300
MIN_TIMEOUT_SECONDS = 5
MAX_TIMEOUT_SECONDS = 1800
PLAYWRIGHT_NPX_PACKAGE = "@playwright/cli"


def _has_session_arg(args: Sequence[str]) -> bool:
    for arg in args:
        if arg == "--session" or str(arg).startswith("--session="):
            return True
    return False


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


def _npx_command() -> str:
    found = shutil.which("npx")
    if found:
        return found
    raise RuntimeError("npx was not found on PATH. Install Node.js/npm first.")


def _playwright_base_command() -> list[str]:
    return [_npx_command(), "--yes", "--package", PLAYWRIGHT_NPX_PACKAGE, "playwright-cli"]


def _self_check() -> int:
    try:
        npx = _npx_command()
    except Exception as exc:
        print(str(exc))
        return 1

    print(f"npx: {npx}")
    npx_version = subprocess.run(
        [npx, "--version"],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    version_text = str(npx_version.stdout or npx_version.stderr or "").strip() or "(unknown)"
    print(f"npx version: {version_text}")

    probe = subprocess.run(
        [*_playwright_base_command(), "--help"],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if probe.returncode != 0:
        detail = str(probe.stderr or probe.stdout or "").strip() or "playwright-cli probe failed."
        print(f"playwright-cli: error ({detail})")
        return int(probe.returncode or 1)
    print("playwright-cli: available")
    return 0


def _normalize_cli_args(value: Sequence[str]) -> list[str]:
    args = [str(item) for item in value]
    if args and args[0] == "--":
        return args[1:]
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Playwright CLI wrapper skill runner")
    parser.add_argument("--self-check", action="store_true", help="verify npx and playwright-cli availability")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="subprocess timeout")
    parser.add_argument("--session", default=None, help="default playwright-cli session id")
    parser.add_argument("--cwd", default=None, help="working directory for execution")
    parser.add_argument("playwright_args", nargs=argparse.REMAINDER, help="arguments passed to playwright-cli")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_check:
        return _self_check()

    cli_args = _normalize_cli_args(args.playwright_args)
    if not cli_args:
        cli_args = ["--help"]

    command = _playwright_base_command()
    if not _has_session_arg(cli_args):
        from_arg = str(args.session or "").strip()
        from_env = str(os.environ.get("PLAYWRIGHT_CLI_SESSION") or "").strip()
        resolved = from_arg or from_env
        if resolved:
            command.extend(["--session", resolved])

    command.extend(cli_args)
    timeout_seconds = _resolve_timeout(args.timeout_seconds)

    run_cwd: str | None = None
    if str(args.cwd or "").strip():
        run_cwd = str(Path(str(args.cwd)).expanduser())

    completed = subprocess.run(
        command,
        cwd=run_cwd,
        check=False,
        timeout=timeout_seconds,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())

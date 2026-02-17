#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import List


TEXT_EXTS = {
    ".py",
    ".pyi",
    ".js",
    ".mjs",
    ".ts",
    ".tsx",
    ".json",
    ".jsonl",
    ".yml",
    ".yaml",
    ".md",
    ".html",
    ".htm",
    ".css",
    ".txt",
    ".sh",
    ".ps1",
    ".bat",
    ".cmd",
    ".env",
    ".toml",
    ".ini",
    ".xml",
    ".sql",
}


def _get_staged_files() -> list[str]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMR",
            "--no-ext-diff",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to list staged files: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _looks_like_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _check_file(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [f"{path}: cannot read ({exc})"]

    if not path.suffix.lower() in TEXT_EXTS:
        return issues

    if _looks_like_binary(raw):
        return issues

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(
            f"{path}: not UTF-8 ({exc})"
        )
        return issues

    if text.startswith("\ufeff"):
        issues.append(
            f"{path}: UTF-8 BOM detected (remove BOM before commit)"
        )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate staged text files are UTF-8 (without BOM)."
    )
    parser.add_argument(
        "--path",
        action="append",
        help="Path to check (default: staged text files)",
    )
    args = parser.parse_args(argv)

    paths: List[Path] = []
    if args.path:
        paths = [Path(item) for item in args.path]
    else:
        paths = [Path(item) for item in _get_staged_files()]

    if not paths:
        print("No staged files.")
        return 0

    issues: list[str] = []
    for path in paths:
        issues.extend(_check_file(path))

    if issues:
        print("Encoding check failed.")
        for item in issues:
            print(f"- {item}")
        print(
            "Please save files as UTF-8 (no BOM) and retry commit."
        )
        return 1

    print("Encoding check passed (UTF-8, no BOM for staged text files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

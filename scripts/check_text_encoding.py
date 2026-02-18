#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import Iterable, List


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

SKIP_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "node_modules",
    "__pycache__",
}

MOJIBAKE_HINT_MARKERS = {
    "\u30fb\uff7d",
    "\u30fb\uff6c",
    "\u30fb\uff63",
    "\u30fb\uff6d",
    "\u7e67",
    "\u7e5d",
    "\u7e3a",
    "\u90e2",
    "\u873f",
    "\u83eb",
    "\u9b06",
    "\uf8f0",
    "\uf8f1",
    "\u7e56",
    "\u8c8e",
}

def _is_dashboard_ui_file(path: Path) -> bool:
    normalized = path.as_posix()
    return normalized.startswith("skills/mfcloud-expense-receipt-reconcile/dashboard/")


def _has_mojibake_markers(text: str) -> bool:
    for marker in MOJIBAKE_HINT_MARKERS:
        if marker in text:
            return True
    return False


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


def _get_tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to list tracked files: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _iter_text_files(path: Path) -> Iterable[Path]:
    if path.is_dir():
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
            for filename in filenames:
                candidate = Path(dirpath) / filename
                if candidate.suffix.lower() in TEXT_EXTS:
                    yield candidate
        return

    if path.is_file() and path.suffix.lower() in TEXT_EXTS:
        yield path


def _collect_paths(args: argparse.Namespace) -> List[Path]:
    if args.path:
        seen = set()
        paths: list[Path] = []
        for raw in args.path:
            candidate = Path(raw)
            if candidate.is_dir():
                for path in _iter_text_files(candidate):
                    norm = path.as_posix()
                    if norm in seen:
                        continue
                    seen.add(norm)
                    paths.append(path)
            elif candidate.is_file():
                if candidate.suffix.lower() not in TEXT_EXTS:
                    continue
                norm = candidate.as_posix()
                if norm in seen:
                    continue
                seen.add(norm)
                paths.append(candidate)
            elif candidate.exists():
                continue
            else:
                raise FileNotFoundError(f"not found: {candidate}")
        return paths

    if args.scope == "tracked":
        files = _get_tracked_files()
    else:
        files = _get_staged_files()
    return [Path(item) for item in files]


def _looks_like_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _check_file(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [f"{path}: cannot read ({exc})"]

    if not path.is_file() or path.suffix.lower() not in TEXT_EXTS:
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

    if _is_dashboard_ui_file(path) and _has_mojibake_markers(text):
        issues.append(
            f"{path}: mojibake-like markers detected (encoding corruption likely)."
        )

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
        "--scope",
        choices=("staged", "tracked"),
        default="staged",
        help="Which file set to check: staged or tracked.",
    )
    parser.add_argument(
        "--path",
        action="append",
        help="Path to check (default: staged text files)",
    )
    args = parser.parse_args(argv)

    paths: List[Path] = []
    if args.path:
        scope_label = "explicit paths"
    else:
        scope_label = f"{args.scope} files"

    try:
        paths = _collect_paths(args)
    except FileNotFoundError as exc:
        print(f"Encoding check failed.")
        print(f"- {exc}")
        return 1

    if not paths:
        print(f"No {scope_label} to check.")
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

    print(f"Encoding check passed ({scope_label}, no BOM).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


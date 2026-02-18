#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

try:
    from .run_support import _ensure_utf8_stdout, _read_json_input
    from .run_processing import _execute_audit
except Exception:  # pragma: no cover - direct script execution fallback
    from run_support import _ensure_utf8_stdout, _read_json_input  # type: ignore
    from run_processing import _execute_audit  # type: ignore


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="knowledge freshness audit for markdown docs")
    ap.add_argument("--input", help="path to JSON input")
    ap.add_argument("--scan", action="append", help="scan path (repeatable)")
    ap.add_argument("--extension", action="append", help="file extension to include (default: .md)")
    ap.add_argument("--exclude-dir", action="append", help="directory names to exclude")
    ap.add_argument("--registry", help="policy registry JSON path")
    ap.add_argument("--max-age-days", type=int, help="default stale threshold")
    ap.add_argument("--warn-within-days", type=int, help="warning window before stale")
    ap.add_argument("--as-of", help="evaluation date (YYYY-MM-DD, default: today)")
    ap.add_argument("--fail-on-stale", action="store_true", help="exit non-zero when stale files exist")
    ap.add_argument("--write-report", action="store_true", help="write markdown report (requires --apply)")
    ap.add_argument("--report-dir", help="report output directory")
    ap.add_argument("--dry-run", action="store_true", default=None, help="do not write files (default)")
    ap.add_argument("--apply", action="store_true", help="allow file outputs (report write)")
    ap.add_argument(
        "--bootstrap-missing-review-date",
        action="store_true",
        help="auto-insert review date frontmatter when missing (only when --apply)",
    )
    ap.add_argument(
        "--strict-bootstrap",
        action="store_true",
        help="treat bootstrap-added review dates as stale (for leak prevention)",
    )
    ap.add_argument(
        "--bootstrap-review-source",
        default="knowledge_refresh_weekly",
        help="review_source value used when auto-inserting missing review metadata",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    ap = _build_parser()
    args = ap.parse_args(argv)

    raw = _read_json_input(args.input)
    out, code = _execute_audit(args, raw_input=raw)
    print(json.dumps(out, ensure_ascii=False))
    return code


def run() -> int:
    return main()


__all__ = ["_build_parser", "main", "run"]

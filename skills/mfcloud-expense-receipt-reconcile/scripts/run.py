#!/usr/bin/env python3
"""
Thin entrypoint for the runner.

The implementation lives in `run_core.py` to keep this file focused on
CLI compatibility and process-level error handling.
"""

from __future__ import annotations

import json
import os
import traceback

from run_core import main as run_main


def _debug_enabled() -> bool:
    return os.environ.get("AX_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":
    try:
        raise SystemExit(run_main())
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        err: dict[str, object] = {"status": "error", "error": {"type": type(exc).__name__, "message": str(exc)}}
        if _debug_enabled():
            error_obj = err.get("error")
            if isinstance(error_obj, dict):
                error_obj["traceback"] = traceback.format_exc()
        print(json.dumps(err, ensure_ascii=False, indent=2))
        raise SystemExit(1)

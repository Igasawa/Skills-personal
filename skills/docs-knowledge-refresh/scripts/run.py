#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import traceback

try:
    from .run_flow import main
except Exception:  # pragma: no cover - direct script execution fallback
    from run_flow import main  # type: ignore


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        out = {
            "status": "error",
            "error": {
                "type": type(e).__name__,
                "message": str(e),
            },
        }
        if os.environ.get("AX_DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
            out["error"]["traceback"] = traceback.format_exc()
        print(json.dumps(out, ensure_ascii=False))
        raise SystemExit(1)
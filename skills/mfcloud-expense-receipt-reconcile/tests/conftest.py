from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
DASHBOARD_DIR = SKILL_ROOT / "dashboard"

for path in (SKILL_ROOT, SCRIPTS_DIR, DASHBOARD_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


_orig_subprocess_run = subprocess.run


def _is_node_command(args: object) -> bool:
    if isinstance(args, (list, tuple)):
        if not args:
            return False
        first = str(args[0]).strip().lower()
        return first.endswith("\\node.exe") or first.endswith("/node") or first.endswith("/node.exe") or first == "node"
    return False


def _patched_subprocess_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    if _is_node_command(args[0] if args else None):  # type: ignore[arg-type]
        text_mode = bool(kwargs.get("text") or kwargs.get("universal_newlines"))
        if text_mode and kwargs.get("encoding") is None:
            kwargs["encoding"] = "utf-8"
    return _orig_subprocess_run(*args, **kwargs)  # type: ignore[arg-type]


subprocess.run = _patched_subprocess_run
if os.environ.get("PYTHONCOERCECLOCALE") != "0":
    os.environ["PYTHONCOERCECLOCALE"] = "0"

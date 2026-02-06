from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
DASHBOARD_DIR = SKILL_ROOT / "dashboard"

for path in (SKILL_ROOT, SCRIPTS_DIR, DASHBOARD_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

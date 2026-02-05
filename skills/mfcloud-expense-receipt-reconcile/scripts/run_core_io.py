#!/usr/bin/env python3

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from common import ax_home as _ax_home  # noqa: E402


def read_json_input(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)

    if sys.stdin and not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    default_path = _ax_home() / "configs" / "mfcloud-expense-receipt-reconcile.json"
    if default_path.exists():
        with open(default_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {}


def cleanup_archives(archive_root: Path, keep: int, label: str) -> None:
    if keep < 1:
        keep = 1
    if not archive_root.exists():
        return
    dirs = [d for d in archive_root.iterdir() if d.is_dir()]
    if len(dirs) <= keep:
        return
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    for old in dirs[keep:]:
        try:
            shutil.rmtree(old)
        except Exception:
            continue
    print(f"[run] Cleaned old {label} archives (keep {keep})", flush=True)


def archive_existing_pdfs(pdfs_dir: Path, label: str) -> None:
    if not pdfs_dir.exists():
        return
    pdfs = list(pdfs_dir.glob("*.pdf"))
    if not pdfs:
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = pdfs_dir.parent / "_archive" / ts
    archive_dir.mkdir(parents=True, exist_ok=True)
    for p in pdfs:
        dest = archive_dir / p.name
        if dest.exists():
            stem = p.stem
            suffix = p.suffix
            i = 1
            while True:
                candidate = archive_dir / f"{stem}_{i}{suffix}"
                if not candidate.exists():
                    dest = candidate
                    break
                i += 1
        shutil.move(str(p), str(dest))
    print(f"[run] Archived existing {label} PDFs to {archive_dir}", flush=True)
    cleanup_archives(pdfs_dir.parent / "_archive", keep=1, label=label)

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable


def format_archive_snapshot_label(name: str) -> str:
    text = str(name or "").strip()
    try:
        dt = datetime.strptime(text, "%Y%m%d_%H%M%S")
    except Exception:
        return text
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def scan_archive_history(
    *,
    artifact_root: Path,
    ym_matcher: Callable[[str], bool],
    archive_action_label: Callable[[str], str],
    limit: int = 30,
) -> list[dict[str, Any]]:
    if not artifact_root.exists():
        return []

    rows: list[dict[str, Any]] = []
    for path in artifact_root.iterdir():
        if not path.is_dir() or path.name == "_runs" or not ym_matcher(path.name):
            continue
        audit_path = path / "reports" / "audit_log.jsonl"
        if not audit_path.exists():
            continue
        for line in audit_path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = str(line or "").strip()
            if not text.startswith("{") or not text.endswith("}"):
                continue
            try:
                obj = json.loads(text)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if str(obj.get("event_type") or "").strip() != "archive":
                continue
            if str(obj.get("status") or "").strip() != "success":
                continue
            action = str(obj.get("action") or "").strip()
            if action not in {"manual_archive", "month_close"}:
                continue
            details = obj.get("details") if isinstance(obj.get("details"), dict) else {}
            ts = str(obj.get("ts") or "").strip()
            rows.append(
                {
                    "ym": path.name,
                    "ts": ts,
                    "action": action,
                    "action_label": archive_action_label(action),
                    "archived_to": str(details.get("archived_to") or "").strip(),
                    "archive_url": f"/runs/{path.name}/archived-receipts",
                }
            )
    rows.sort(key=lambda row: str(row.get("ts") or ""), reverse=True)
    if limit > 0:
        return rows[:limit]
    return rows


def scan_archived_receipts(
    root: Any,
    *,
    source_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    base = Path(root)
    archive_root = base / "archive"
    snapshots: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    labels = source_labels or {"amazon": "Amazon", "rakuten": "Rakuten"}

    if not archive_root.exists():
        return {
            "archive_root": str(archive_root),
            "snapshot_count": 0,
            "receipt_count": 0,
            "amazon_count": 0,
            "rakuten_count": 0,
            "snapshots": snapshots,
            "rows": rows,
        }

    for snap_dir in sorted((p for p in archive_root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        snapshot_name = snap_dir.name
        snapshot_label = format_archive_snapshot_label(snapshot_name)
        source_counts = {"amazon": 0, "rakuten": 0}
        for source in ("amazon", "rakuten"):
            pdf_dir = snap_dir / source / "pdfs"
            if not pdf_dir.exists():
                continue
            for pdf_path in sorted(pdf_dir.glob("*.pdf")):
                try:
                    size_kb = max(1, int(pdf_path.stat().st_size / 1024))
                except Exception:
                    size_kb = 0
                source_counts[source] += 1
                rows.append(
                    {
                        "snapshot": snapshot_name,
                        "snapshot_label": snapshot_label,
                        "source": source,
                        "source_label": labels.get(source) or source,
                        "pdf_name": pdf_path.name,
                        "pdf_size_kb": size_kb,
                    }
                )
        snapshots.append(
            {
                "snapshot": snapshot_name,
                "snapshot_label": snapshot_label,
                "path": str(snap_dir),
                "amazon_count": source_counts["amazon"],
                "rakuten_count": source_counts["rakuten"],
                "receipt_count": source_counts["amazon"] + source_counts["rakuten"],
            }
        )

    return {
        "archive_root": str(archive_root),
        "snapshot_count": len(snapshots),
        "receipt_count": len(rows),
        "amazon_count": sum(int(item.get("amazon_count") or 0) for item in snapshots),
        "rakuten_count": sum(int(item.get("rakuten_count") or 0) for item in snapshots),
        "snapshots": snapshots,
        "rows": rows,
    }

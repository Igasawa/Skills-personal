#!/usr/bin/env python3
"""Archive an incident as resolved or escalated."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from error_common import (
    ARCHIVE_RESULTS,
    ensure_error_dirs,
    normalize_incident_id,
    now_utc_iso,
    read_json,
    read_text,
    redact_text,
    resolve_reports_root,
    write_json,
    write_status,
    write_text,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive incident from inbox")
    parser.add_argument("--incident-id", required=True, help="Incident id")
    parser.add_argument("--result", required=True, choices=sorted(ARCHIVE_RESULTS), help="Archive bucket")
    parser.add_argument("--reason", default="", help="Archive reason summary")
    parser.add_argument("--note-file", default="", help="Path to additional note text")
    parser.add_argument("--root", default="", help="Reports root override")
    parser.add_argument("--force", action="store_true", help="Overwrite destination folder when it exists")
    return parser.parse_args()


def _read_note(note_file: str) -> str:
    note_path = Path(str(note_file or "").strip()).expanduser()
    if not str(note_file or "").strip():
        return ""
    if not note_path.exists():
        raise FileNotFoundError(f"note file not found: {note_path}")
    return note_path.read_text(encoding="utf-8", errors="ignore")


def main() -> int:
    args = parse_args()
    reports_root = resolve_reports_root(args.root)
    dirs = ensure_error_dirs(reports_root)

    incident_id = normalize_incident_id(args.incident_id)
    source_dir = dirs["inbox"] / incident_id
    if not source_dir.exists():
        raise SystemExit(f"incident not found in inbox: {source_dir}")

    destination_root = dirs["archive_resolved"] if args.result == "resolved" else dirs["archive_escalated"]
    destination_dir = destination_root / incident_id
    if destination_dir.exists():
        if not args.force:
            raise SystemExit(f"archive destination already exists: {destination_dir}")
        shutil.rmtree(destination_dir)

    payload = read_json(source_dir / "incident.json")
    payload = payload if isinstance(payload, dict) else {}
    now = now_utc_iso()
    reason = redact_text(str(args.reason or "").strip())
    extra_note = redact_text(_read_note(args.note_file))

    payload.update(
        {
            "status": args.result,
            "archive_result": args.result,
            "archive_reason": reason,
            "archived_at": now,
            "updated_at": now,
        }
    )

    write_json(source_dir / "incident.json", payload)
    write_status(source_dir, args.result)

    note_lines: list[str] = []
    if reason:
        note_lines.append(f"reason: {reason}")
    if extra_note:
        note_lines.append("")
        note_lines.append(extra_note)
    if note_lines:
        existing = read_text(source_dir / "resolution_note.md")
        body = "\n".join(note_lines).strip() + "\n"
        if existing:
            body = existing.rstrip() + "\n\n" + body
        write_text(source_dir / "resolution_note.md", body)

    shutil.move(str(source_dir), str(destination_dir))
    write_json(
        destination_dir / "archive_meta.json",
        {
            "incident_id": incident_id,
            "result": args.result,
            "archived_at": now,
            "reason": reason,
            "source": str(source_dir),
            "destination": str(destination_dir),
        },
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "incident_id": incident_id,
                "result": args.result,
                "path": str(destination_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


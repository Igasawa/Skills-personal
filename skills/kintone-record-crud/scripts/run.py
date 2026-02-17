#!/usr/bin/env python3
"""
Basic kintone record CRUD (add/update/upsert) via REST API.

This script follows the repository convention:
- default is dry-run (no writes)
- apply requires explicit flag
- do not print secret values
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from axkit.kintone_rest import KintoneAuth, KintoneClient, KintoneTarget


if hasattr(sys.stdout, "reconfigure"):
    # Prefer UTF-8 JSON output (Windows Terminal default).
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _blank_to_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _load_record_arg(*, record_json: Optional[str], record_file: Optional[str]) -> dict[str, Any]:
    if record_json and record_file:
        raise ValueError("Use either --record or --record-file (not both)")
    if record_file:
        # Windows PowerShell's Set-Content often writes UTF-8 with BOM.
        with open(record_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    elif record_json:
        data = json.loads(record_json)
    else:
        raise ValueError("Missing --record or --record-file")
    if not isinstance(data, dict):
        raise ValueError("record must be a JSON object")
    return data


def _to_kintone_record(simple: dict[str, Any]) -> dict[str, Any]:
    # Convert {code: value} to {code: {value: ...}}
    out: dict[str, Any] = {}
    for k, v in simple.items():
        out[str(k)] = {"value": v}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="kintone record CRUD")
    ap.add_argument("--subdomain", default="5atx9", help="kintone subdomain (default: 5atx9)")
    ap.add_argument("--guest-space-id", default=None, help="guest space id (optional)")
    ap.add_argument("--session-name", default="kintone", help="storage_state session name (default: kintone)")
    ap.add_argument("--storage-state", default=None, help="override storage_state path (optional)")

    ap.add_argument("--app-id", required=True, help="kintone app id")
    ap.add_argument(
        "--action",
        required=True,
        choices=["get-app", "get-fields", "add", "update", "upsert"],
        help="operation",
    )

    ap.add_argument("--record", default=None, help="record JSON string")
    ap.add_argument("--record-file", default=None, help="path to record JSON")
    ap.add_argument("--simple", action="store_true", help="treat record input as {fieldCode: value}")

    ap.add_argument("--record-id", default=None, help="record id for update")
    ap.add_argument("--update-key-field", default=None, help="unique key field code for update/upsert")
    ap.add_argument("--update-key-value", default=None, help="unique key value for update/upsert")
    ap.add_argument("--revision", default=None, help="expected revision (optional)")

    ap.add_argument("--dry-run", action="store_true", default=None, help="do not write (default)")
    ap.add_argument("--apply", action="store_true", help="perform write")
    args = ap.parse_args()

    dry_run = True if args.dry_run or not args.apply else False

    out: dict[str, Any] = {"status": "ok", "data": {}, "error": None}

    try:
        target = KintoneTarget(subdomain=str(args.subdomain).strip(), guest_space_id=_blank_to_none(args.guest_space_id))
        auth = KintoneAuth(
            allow_session_fallback=True,
            session_name=str(args.session_name).strip() or "kintone",
            storage_state_path=_blank_to_none(args.storage_state),
        )

        planned: dict[str, Any] = {
            "kintone": {"subdomain": target.subdomain, "guest_space_id": target.guest_space_id},
            "auth_mode": auth.mode(),
            "app_id": str(args.app_id),
            "action": args.action,
            "dry_run": dry_run,
        }

        # Read-only ops (no record required)
        if args.action in ("get-app", "get-fields"):
            if dry_run:
                out["data"] = {"planned": planned}
                print(json.dumps(out, ensure_ascii=False))
                return 0
            with KintoneClient(target=target, auth=auth) as kc:
                res = kc.get_app(args.app_id) if args.action == "get-app" else kc.get_form_fields(args.app_id)
            out["data"] = {"planned": planned, "result": res}
            print(json.dumps(out, ensure_ascii=False))
            return 0

        record_in = _load_record_arg(record_json=_blank_to_none(args.record), record_file=_blank_to_none(args.record_file))
        record = _to_kintone_record(record_in) if args.simple else record_in

        # Basic validation to prevent accidental huge payloads.
        if len(record) == 0:
            raise ValueError("record is empty")

        if args.action == "add":
            planned["request"] = {"app": str(args.app_id), "record": record}
        elif args.action == "update":
            planned["request"] = {"app": str(args.app_id), "record": record}
            if _blank_to_none(args.record_id):
                planned["request"]["id"] = str(args.record_id)
            else:
                f = _blank_to_none(args.update_key_field)
                v = _blank_to_none(args.update_key_value)
                if not (f and v is not None):
                    raise ValueError("update requires --record-id or (--update-key-field and --update-key-value)")
                planned["request"]["updateKey"] = {"field": f, "value": v}
            if _blank_to_none(args.revision):
                planned["request"]["revision"] = str(args.revision)
        elif args.action == "upsert":
            f = _blank_to_none(args.update_key_field)
            v = _blank_to_none(args.update_key_value)
            if not (f and v is not None):
                raise ValueError("upsert requires --update-key-field and --update-key-value")
            planned["request"] = {
                "app": str(args.app_id),
                "upsert": True,
                "records": [{"updateKey": {"field": f, "value": v}, "record": record}],
            }
            if _blank_to_none(args.revision):
                planned["request"]["records"][0]["revision"] = str(args.revision)
        else:
            raise ValueError("unsupported action")

        if dry_run:
            out["data"] = {"planned": planned}
            print(json.dumps(out, ensure_ascii=False))
            return 0

        with KintoneClient(target=target, auth=auth) as kc:
            if args.action == "add":
                res = kc.add_record(app_id=str(args.app_id), record=record)
            elif args.action == "update":
                res = kc.update_record(
                    app_id=str(args.app_id),
                    record=record,
                    record_id=_blank_to_none(args.record_id),
                    update_key_field=_blank_to_none(args.update_key_field),
                    update_key_value=_blank_to_none(args.update_key_value),
                    revision=_blank_to_none(args.revision),
                )
            else:  # upsert
                res = kc.upsert_record(
                    app_id=str(args.app_id),
                    record=record,
                    update_key_field=str(args.update_key_field),
                    update_key_value=str(args.update_key_value),
                    revision=_blank_to_none(args.revision),
                )

        out["data"] = {"planned": planned, "result": res}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception as e:
        out["status"] = "error"
        out["error"] = {"message": str(e)}
        print(json.dumps(out, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

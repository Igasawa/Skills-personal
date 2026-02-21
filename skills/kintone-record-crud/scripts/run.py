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
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING


REQUEST_TIMEOUT = 30
DEFAULT_SUBDOMAIN = "5atx9"
DEFAULT_SESSION_NAME = "kintone"


if TYPE_CHECKING:  # pragma: no cover
    import requests  # type: ignore


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _import_requests():
    try:
        import requests  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - runtime dependency
        raise ModuleNotFoundError(
            "Python module 'requests' is required. Install it with: python -m pip install requests"
        ) from exc
    return requests


def _blank_to_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _default_storage_state_path(session_name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in session_name)
    return _ax_home() / "sessions" / f"{safe}.storage.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _host_matches(cookie_domain: str, target_host: str) -> bool:
    left = cookie_domain.lstrip(".").lower()
    host = target_host.lower()
    return host == left or host.endswith(f".{left}")


def _attach_storage_cookies(sess: Any, storage_state: dict[str, Any], target_host: str) -> int:
    cookies = storage_state.get("cookies")
    if not isinstance(cookies, list):
        return 0
    attached = 0
    for row in cookies:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        value = row.get("value")
        domain = row.get("domain")
        path = row.get("path") or "/"
        if not isinstance(name, str) or not isinstance(value, str) or not isinstance(domain, str):
            continue
        if not _host_matches(domain, target_host):
            continue
        sess.cookies.set(name, value, domain=domain, path=path)
        attached += 1
    return attached


def _api_token_from_env() -> str | None:
    return _blank_to_none(os.environ.get("KINTONE_API_TOKEN"))


def _auth_headers_from_env() -> tuple[dict[str, str], str] | None:
    username = _blank_to_none(os.environ.get("KINTONE_USERNAME"))
    password = _blank_to_none(os.environ.get("KINTONE_PASSWORD"))
    api_token = _api_token_from_env()

    headers: dict[str, str] = {"X-Requested-With": "XMLHttpRequest"}
    if api_token:
        headers["X-Cybozu-API-Token"] = api_token

    if username and password:
        auth_base64 = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
        headers["X-Cybozu-Authorization"] = auth_base64
        return headers, "password"

    if api_token:
        return headers, "api_token"
    return None


def _session_from_storage_state(
    *,
    subdomain: str,
    session_name: str,
    storage_state_path: Optional[str],
) -> tuple[Any, dict[str, Any], dict[str, str]]:
    requests = _import_requests()
    target_host = f"{subdomain}.cybozu.com"
    state_path = Path(storage_state_path).expanduser() if storage_state_path else _default_storage_state_path(session_name)
    if not state_path.exists():
        raise ValueError(f"storage_state not found: {state_path}")
    state = _load_json(state_path)
    if not isinstance(state, dict):
        raise ValueError(f"Invalid storage_state JSON: {state_path}")

    sess = requests.Session()
    attached = _attach_storage_cookies(sess, state, target_host)
    if attached == 0:
        sess.close()
        raise ValueError(f"No cookies for target host in storage_state: host={target_host}, file={state_path}")

    headers: dict[str, str] = {"X-Requested-With": "XMLHttpRequest"}
    api_token = _api_token_from_env()
    if api_token:
        headers["X-Cybozu-API-Token"] = api_token

    meta = {"_auth": "session", "_session_name": session_name, "_storage_state": str(state_path)}
    return sess, meta, headers


def _api_base_url(*, subdomain: str, guest_space_id: str | None) -> str:
    guest_id = _blank_to_none(guest_space_id)
    if guest_id:
        return f"https://{subdomain}.cybozu.com/k/guest/{guest_id}/v1"
    return f"https://{subdomain}.cybozu.com/k/v1"


def _request_json(
    sess: Any,
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    requests = _import_requests()
    response = sess.request(
        method=method,
        url=url,
        headers=headers,
        params=params,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = f" code={body.get('code')} message={body.get('message')}"
        except Exception:
            detail = f" body={str(response.text or '')[:300]}"
        raise ValueError(f"kintone API error: status={response.status_code}.{detail}".strip()) from exc
    try:
        return response.json()
    except Exception as exc:
        raise ValueError("kintone API returned invalid JSON") from exc


def _load_record_arg(*, record_json: Optional[str], record_file: Optional[str]) -> dict[str, Any]:
    if record_json and record_file:
        raise ValueError("Use either --record or --record-file (not both)")
    if record_file:
        data = json.loads(Path(record_file).read_text(encoding="utf-8-sig"))
    elif record_json:
        data = json.loads(record_json)
    else:
        raise ValueError("Missing --record or --record-file")
    if not isinstance(data, dict):
        raise ValueError("record must be a JSON object")
    return data


def _to_kintone_record(simple: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in simple.items():
        out[str(k)] = {"value": v}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="kintone record CRUD")
    ap.add_argument("--subdomain", default=DEFAULT_SUBDOMAIN, help=f"kintone subdomain (default: {DEFAULT_SUBDOMAIN})")
    ap.add_argument("--guest-space-id", default=None, help="guest space id (optional)")
    ap.add_argument(
        "--session-name",
        default=DEFAULT_SESSION_NAME,
        help=f"storage_state session name (default: {DEFAULT_SESSION_NAME})",
    )
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

    sess = None
    try:
        subdomain = _blank_to_none(args.subdomain) or DEFAULT_SUBDOMAIN
        base_url = _api_base_url(subdomain=subdomain, guest_space_id=_blank_to_none(args.guest_space_id))

        requests = _import_requests()
        env_auth = _auth_headers_from_env()
        if env_auth is not None:
            headers, auth_mode = env_auth
            sess = requests.Session()
            auth_meta = {"_auth": auth_mode}
        else:
            try:
                sess, auth_meta, headers = _session_from_storage_state(
                    subdomain=subdomain,
                    session_name=_blank_to_none(args.session_name) or DEFAULT_SESSION_NAME,
                    storage_state_path=_blank_to_none(args.storage_state),
                )
            except ValueError as exc:
                raise ValueError(
                    "KINTONE_USERNAME/KINTONE_PASSWORD missing; session fallback failed. "
                    f"{exc}"
                ) from exc

        planned: dict[str, Any] = {
            "kintone": {
                "subdomain": subdomain,
                "guest_space_id": _blank_to_none(args.guest_space_id),
                "base_url": base_url,
            },
            "auth_mode": auth_meta.get("_auth"),
            "app_id": str(args.app_id),
            "action": args.action,
            "dry_run": dry_run,
        }

        if args.action in ("get-app", "get-fields"):
            if dry_run:
                out["data"] = {"planned": planned}
                print(json.dumps(out, ensure_ascii=False))
                return 0
            if args.action == "get-app":
                result = _request_json(
                    sess,
                    method="GET",
                    url=f"{base_url}/app.json",
                    headers=headers,
                    params={"id": str(args.app_id)},
                )
            else:
                result = _request_json(
                    sess,
                    method="GET",
                    url=f"{base_url}/app/form/fields.json",
                    headers=headers,
                    params={"app": str(args.app_id)},
                )
            out["data"] = {"planned": planned, "result": result}
            print(json.dumps(out, ensure_ascii=False))
            return 0

        record_in = _load_record_arg(record_json=_blank_to_none(args.record), record_file=_blank_to_none(args.record_file))
        record = _to_kintone_record(record_in) if args.simple else record_in

        if len(record) == 0:
            raise ValueError("record is empty")

        if args.action == "add":
            request_payload = {"app": str(args.app_id), "record": record}
        elif args.action == "update":
            request_payload = {"app": str(args.app_id), "record": record}
            if _blank_to_none(args.record_id):
                request_payload["id"] = str(args.record_id)
            else:
                f = _blank_to_none(args.update_key_field)
                v = _blank_to_none(args.update_key_value)
                if not (f and v is not None):
                    raise ValueError("update requires --record-id or (--update-key-field and --update-key-value)")
                request_payload["updateKey"] = {"field": f, "value": v}
            if _blank_to_none(args.revision):
                request_payload["revision"] = str(args.revision)
        else:  # upsert
            f = _blank_to_none(args.update_key_field)
            v = _blank_to_none(args.update_key_value)
            if not (f and v is not None):
                raise ValueError("upsert requires --update-key-field and --update-key-value")
            row: dict[str, Any] = {"updateKey": {"field": f, "value": v}, "record": record}
            if _blank_to_none(args.revision):
                row["revision"] = str(args.revision)
            request_payload = {"app": str(args.app_id), "upsert": True, "records": [row]}

        planned["request"] = request_payload
        if dry_run:
            out["data"] = {"planned": planned}
            print(json.dumps(out, ensure_ascii=False))
            return 0

        if args.action == "add":
            result = _request_json(
                sess,
                method="POST",
                url=f"{base_url}/record.json",
                headers=headers,
                payload=request_payload,
            )
        elif args.action == "update":
            result = _request_json(
                sess,
                method="PUT",
                url=f"{base_url}/record.json",
                headers=headers,
                payload=request_payload,
            )
        else:
            result = _request_json(
                sess,
                method="PUT",
                url=f"{base_url}/records.json",
                headers=headers,
                payload=request_payload,
            )

        out["data"] = {"planned": planned, "result": result}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception as exc:
        out["status"] = "error"
        out["error"] = {"message": str(exc)}
        print(json.dumps(out, ensure_ascii=False))
        return 1
    finally:
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())

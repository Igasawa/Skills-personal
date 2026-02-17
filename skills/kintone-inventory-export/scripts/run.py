#!/usr/bin/env python3
"""
Export kintone app list and (inferred) space details.

Auth priority:
1) KINTONE_USERNAME/KINTONE_PASSWORD (X-Cybozu-Authorization)
2) Playwright storage_state cookies (AX_HOME/sessions/<name>.storage.json)

Notes:
- Space list is inferred from app.spaceId; spaces without apps may be missing.
- Private spaces may fail to fetch if the session has no permission.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING


REQUEST_TIMEOUT = 30
DEFAULT_SUBDOMAIN = "5atx9"
DEFAULT_SESSION_NAME = "kintone"
DEFAULT_ACTIVE_WITHIN_DAYS = 180

if TYPE_CHECKING:  # pragma: no cover
    import requests  # type: ignore


def _import_requests():
    try:
        import requests  # type: ignore
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "Python module 'requests' is required. Install it with: python -m pip install requests"
        ) from e
    return requests


def _now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


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


def _reports_dir(*, ensure: bool) -> Path:
    p = _ax_home() / "reports" / "kintone_inventory"
    if ensure:
        p.mkdir(parents=True, exist_ok=True)
    return p


def _default_storage_state_path(session_name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in session_name)
    return _ax_home() / "sessions" / f"{safe}.storage.json"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _host_matches(cookie_domain: str, target_host: str) -> bool:
    left = cookie_domain.lstrip(".").lower()
    host = target_host.lower()
    return host == left or host.endswith(f".{left}")


def _attach_storage_cookies(sess: Any, storage_state: dict[str, Any], target_host: str) -> int:
    cookies = storage_state.get("cookies")
    if not isinstance(cookies, list):
        return 0
    attached = 0
    for c in cookies:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain")
        path = c.get("path") or "/"
        if not isinstance(name, str) or not isinstance(value, str) or not isinstance(domain, str):
            continue
        if not _host_matches(domain, target_host):
            continue
        sess.cookies.set(name, value, domain=domain, path=path)
        attached += 1
    return attached


def _auth_headers_from_env() -> Optional[dict[str, str]]:
    username = _blank_to_none(os.environ.get("KINTONE_USERNAME"))
    password = _blank_to_none(os.environ.get("KINTONE_PASSWORD"))
    if not (username and password):
        return None
    auth_base64 = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return {
        "X-Cybozu-Authorization": auth_base64,
        "X-Requested-With": "XMLHttpRequest",
    }


def _session_from_storage_state(*, subdomain: str, session_name: str, storage_state_path: Optional[str]) -> tuple[Any, dict[str, Any]]:
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

    meta = {"_auth": "session", "_session_name": session_name, "_storage_state": str(state_path)}
    return sess, meta


def _get_json(sess: Any, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None) -> Any:
    resp = sess.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_all_apps(
    *,
    base_url: str,
    sess: Any,
    headers: dict[str, str],
    limit: int = 100,
) -> list[dict[str, Any]]:
    apps: list[dict[str, Any]] = []
    offset = 0
    while True:
        data = _get_json(
            sess,
            f"{base_url}/k/v1/apps.json",
            headers=headers,
            params={"limit": limit, "offset": offset},
        )
        chunk = data.get("apps") if isinstance(data, dict) else None
        if not isinstance(chunk, list):
            raise ValueError("Unexpected response: missing 'apps'")
        for a in chunk:
            if isinstance(a, dict):
                apps.append(a)
        if len(chunk) < limit:
            break
        offset += limit
    return apps


def fetch_space(
    *,
    base_url: str,
    sess: Any,
    headers: dict[str, str],
    space_id: str,
) -> dict[str, Any]:
    data = _get_json(
        sess,
        f"{base_url}/k/v1/space.json",
        headers=headers,
        params={"id": space_id},
    )
    if not isinstance(data, dict):
        raise ValueError("Unexpected response for space.json")
    return data


def _parse_kintone_datetime(value: Any) -> Optional[dt.datetime]:
    """
    kintone datetime often looks like:
    - 2026-02-10T01:23:45.000Z
    - 2026-02-10T10:23:45+0900
    - 2026-02-10T10:23:45+09:00
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # +0900 -> +09:00
    if len(s) >= 5 and (s[-5] in ("+", "-")) and s[-4:].isdigit() and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def _extract_record_time(record: dict[str, Any], field_code: str) -> Optional[dt.datetime]:
    f = record.get(field_code)
    if not isinstance(f, dict):
        return None
    return _parse_kintone_datetime(f.get("value"))


def _extract_record_id(record: dict[str, Any]) -> Optional[str]:
    f = record.get("$id")
    if not isinstance(f, dict):
        return None
    v = f.get("value")
    return str(v) if v is not None else None


def fetch_last_record_activity(
    *,
    base_url: str,
    sess: Any,
    headers: dict[str, str],
    app_id: str,
) -> dict[str, Any]:
    """
    Determine "usage" by checking the most recently updated record.
    This is a heuristic; apps with no records will have no activity.
    """
    # kintone query for system fields is locale/app-setting dependent in practice.
    # Try multiple order fields; keep requests small (limit 1).
    url = f"{base_url}/k/v1/records.json"
    order_field_candidates = [
        "Updated_datetime",
        "更新日時",
        # Fallbacks if "updated" is not available/usable for ordering in a given app.
        "Created_datetime",
        "作成日時",
    ]

    last_error: Optional[dict[str, Any]] = None
    for order_field in order_field_candidates:
        params: list[tuple[str, str]] = [
            ("app", app_id),
            ("query", f"order by {order_field} desc limit 1"),
            ("fields[0]", "$id"),
            ("fields[1]", order_field),
        ]
        resp = sess.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 400:
            # Typical: field not found for this app's query language (try next candidate).
            try:
                body = resp.json()
            except Exception:
                body = None
            last_error = {
                "status_code": resp.status_code,
                "code": (body.get("code") if isinstance(body, dict) else None),
                "message": (body.get("message") if isinstance(body, dict) else None),
                "order_field": order_field,
            }
            continue

        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            raise ValueError("Unexpected response from records.json")
        records = data["records"]
        if not records:
            return {
                "has_records": False,
                "last_record_id": None,
                "last_updated_at": None,
                "order_field": order_field,
            }
        r0 = records[0]
        if not isinstance(r0, dict):
            return {
                "has_records": True,
                "last_record_id": None,
                "last_updated_at": None,
                "order_field": order_field,
            }

        last_dt = _extract_record_time(r0, order_field)
        return {
            "has_records": True,
            "last_record_id": _extract_record_id(r0),
            "last_updated_at": last_dt.isoformat() if isinstance(last_dt, dt.datetime) else None,
            "order_field": order_field,
        }

    # If we get here, all candidates failed (often permission/guest-space/app-type edge cases).
    return {"has_records": None, "last_record_id": None, "last_updated_at": None, "error": last_error}


def _write_report_json(payload: dict[str, Any], *, subdomain: str) -> str:
    out_dir = _reports_dir(ensure=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{subdomain}_{stamp}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out_path)


def main() -> int:
    ap = argparse.ArgumentParser(description="kintone inventory export (apps + inferred spaces)")
    ap.add_argument("--subdomain", default=None, help=f"kintone subdomain (default: {DEFAULT_SUBDOMAIN})")
    ap.add_argument("--session-name", default=None, help=f"storage_state session name (default: {DEFAULT_SESSION_NAME})")
    ap.add_argument("--storage-state", default=None, help="override storage_state file path (optional)")
    ap.add_argument("--no-write", action="store_true", help="do not write report JSON to AX_HOME")
    ap.add_argument("--limit", type=int, default=100, help="apps.json page size (default: 100)")
    ap.add_argument(
        "--active-within-days",
        type=int,
        default=DEFAULT_ACTIVE_WITHIN_DAYS,
        help=f"filter apps by last record Updated_datetime within N days (default: {DEFAULT_ACTIVE_WITHIN_DAYS})",
    )
    ap.add_argument(
        "--exclude-unknown-activity",
        action="store_true",
        help="exclude apps whose last-record activity cannot be determined (permission errors etc.)",
    )
    ap.add_argument(
        "--skip-activity-check",
        action="store_true",
        help="do not query records.json per app; export all apps (faster)",
    )
    ap.add_argument("--max-apps", type=int, default=0, help="cap number of apps to process (0 = no cap)")
    args = ap.parse_args()

    subdomain = _blank_to_none(args.subdomain) or DEFAULT_SUBDOMAIN
    session_name = _blank_to_none(args.session_name) or DEFAULT_SESSION_NAME
    base_url = f"https://{subdomain}.cybozu.com"

    out: dict[str, Any] = {
        "status": "ok",
        "data": {},
        "error": None,
    }

    try:
        headers = _auth_headers_from_env()
        requests = _import_requests()
        sess: Any
        auth_meta: dict[str, Any]
        if headers is not None:
            sess = requests.Session()
            auth_meta = {"_auth": "password"}
        else:
            sess, auth_meta = _session_from_storage_state(
                subdomain=subdomain,
                session_name=session_name,
                storage_state_path=_blank_to_none(args.storage_state),
            )
            headers = {"X-Requested-With": "XMLHttpRequest"}

        try:
            apps = fetch_all_apps(base_url=base_url, sess=sess, headers=headers, limit=max(1, int(args.limit)))
            if int(args.max_apps) > 0:
                apps = apps[: int(args.max_apps)]

            activity_days = max(0, int(args.active_within_days))
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=activity_days) if activity_days > 0 else None

            app_activity: dict[str, Any] = {}
            unknown_activity: list[dict[str, Any]] = []
            inactive_apps: list[str] = []
            active_apps: list[str] = []

            if not args.skip_activity_check:
                for a in apps:
                    app_id = a.get("appId")
                    if not isinstance(app_id, str) or not app_id.strip():
                        continue
                    aid = app_id.strip()
                    try:
                        act = fetch_last_record_activity(base_url=base_url, sess=sess, headers=headers, app_id=aid)
                        app_activity[aid] = act
                        has_records_raw = act.get("has_records", True)
                        has_records = bool(has_records_raw) if has_records_raw is not None else None
                        last_updated_at = _parse_kintone_datetime(act.get("last_updated_at"))
                        if cutoff is None:
                            active_apps.append(aid)
                        elif has_records is False:
                            # Apps with no records are effectively "unused" for this heuristic.
                            inactive_apps.append(aid)
                        elif has_records is None:
                            unknown_activity.append({"app_id": aid})
                        elif last_updated_at is None:
                            unknown_activity.append({"app_id": aid})
                        elif last_updated_at >= cutoff:
                            active_apps.append(aid)
                        else:
                            inactive_apps.append(aid)
                    except requests.HTTPError as e:
                        r = e.response
                        item = {
                            "app_id": aid,
                            "status_code": getattr(r, "status_code", None),
                            "reason": getattr(r, "reason", None),
                        }
                        unknown_activity.append(item)
                        app_activity[aid] = {"error": item}
                    except Exception as e:
                        unknown_activity.append({"app_id": aid, "error": str(e)})
                        app_activity[aid] = {"error": {"message": str(e)}}

            def _is_included_app(a: dict[str, Any]) -> bool:
                app_id = a.get("appId")
                if not isinstance(app_id, str) or not app_id.strip():
                    return False
                aid = app_id.strip()
                if args.skip_activity_check or cutoff is None:
                    return True
                if aid in active_apps:
                    return True
                if any(u.get("app_id") == aid for u in unknown_activity):
                    return not bool(args.exclude_unknown_activity)
                return False

            apps_included = [a for a in apps if _is_included_app(a)]
            apps_excluded = [a for a in apps if a not in apps_included]

            space_ids: set[str] = set()
            for a in apps_included:
                sid = a.get("spaceId")
                if isinstance(sid, str) and sid.strip():
                    space_ids.add(sid.strip())

            spaces: dict[str, Any] = {}
            space_errors: list[dict[str, Any]] = []
            for sid in sorted(space_ids, key=lambda x: int(x) if x.isdigit() else x):
                try:
                    spaces[sid] = fetch_space(base_url=base_url, sess=sess, headers=headers, space_id=sid)
                except requests.HTTPError as e:
                    r = e.response
                    space_errors.append(
                        {
                            "space_id": sid,
                            "status_code": getattr(r, "status_code", None),
                            "reason": getattr(r, "reason", None),
                        }
                    )
                except Exception as e:
                    space_errors.append({"space_id": sid, "error": str(e)})

            payload = {
                "generated_at": _now_utc_iso(),
                "kintone": {
                    "subdomain": subdomain,
                    "base_url": base_url,
                    **auth_meta,
                },
                "counts": {
                    "apps_total": len(apps),
                    "apps_included": len(apps_included),
                    "apps_excluded": len(apps_excluded),
                    "apps_activity_checked": (len(app_activity) if not args.skip_activity_check else 0),
                    "apps_unknown_activity": (len(unknown_activity) if not args.skip_activity_check else 0),
                    "apps_inactive_by_cutoff": (len(inactive_apps) if not args.skip_activity_check and cutoff is not None else 0),
                    "spaces_inferred_from_apps": len(space_ids),
                    "spaces_fetched": len(spaces),
                    "spaces_fetch_errors": len(space_errors),
                },
                "notes": {
                    "space_list_is_inferred": True,
                    "spaces_without_apps_may_be_missing": True,
                    "activity_filter": {
                        "enabled": not bool(args.skip_activity_check) and cutoff is not None,
                        "active_within_days": activity_days,
                        "exclude_unknown_activity": bool(args.exclude_unknown_activity),
                    "cutoff_utc": cutoff.isoformat() if cutoff is not None else None,
                        "heuristic": "last record order-by (Updated_datetime/更新日時/Created_datetime/作成日時)",
                    },
                },
                "apps": apps_included,
                "apps_excluded": [{"appId": a.get("appId"), "spaceId": a.get("spaceId")} for a in apps_excluded],
                "app_activity": app_activity if not args.skip_activity_check else None,
                "unknown_activity": unknown_activity if not args.skip_activity_check else None,
                "spaces": spaces,
                "space_errors": space_errors,
            }

            report_path = None
            if not args.no_write:
                report_path = _write_report_json(payload, subdomain=subdomain)

            out["data"] = {
                **payload["kintone"],
                "generated_at": payload["generated_at"],
                "counts": payload["counts"],
                "notes": payload["notes"],
                "report_path": report_path,
            }
        finally:
            sess.close()
    except Exception as e:
        out["status"] = "error"
        out["error"] = {"message": str(e)}

    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

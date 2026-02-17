#!/usr/bin/env python3
"""
Run the skill with a standardized JSON interface.

Input (stdin or --input):
{
  "config": {
    "kintone": {
      "subdomain": "5atx9",
      "space_id": 24,
      "thread_id": 36,
      "username": "...",  # optional (prefer env KINTONE_USERNAME)
      "password": "...",  # optional (prefer env KINTONE_PASSWORD)
      "allow_session_fallback": true,
      "session_name": "kintone",
      "storage_state_path": null
    },
    "preflight": {
      "enabled": true,
      "subdomain": "5atx9",
      "space_id": 81,
      "thread_id": 131
    },
    "interactive": false,
    "dry_run": true
  },
  "params": {
    "year": 2026,
    "month": 1,
    "day": 10,
    "fallback_days": 2,
    "price": 170.2  # optional override (skips fetch)
  }
}
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
import sys
import traceback
from typing import Any

from post_to_kintone import post_thread_comment


def _read_json_input(path: str | None) -> dict[str, Any]:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    if sys.stdin and not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    return {}


def _coalesce(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip()
    return cleaned or None


def _as_int(value: Any, *, name: str) -> int:
    if value is None:
        raise ValueError(f"Missing required integer: {name}")
    try:
        return int(value)
    except Exception as e:  # noqa: BLE001 - surface a clearer message
        raise ValueError(f"Invalid integer for {name}: {value!r}") from e


def _as_float(value: Any, *, name: str) -> float:
    if value is None:
        raise ValueError(f"Missing required number: {name}")
    try:
        return float(value)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid number for {name}: {value!r}") from e


def _format_comment(month: int, price: float) -> str:
    # Keep the template stable so other skills can reuse it.
    return (
        f"[{month}月ガソリン代]\n"
        f"お疲れ様です。{month}月ガソリン代の連絡です。よろしくお願いいたします。\n"
        f"ガソリン価格 {price}円"
    )


@dataclass(frozen=True)
class KintoneTarget:
    subdomain: str
    space_id: int
    thread_id: int


@dataclass(frozen=True)
class PreflightConfig:
    enabled: bool
    target: KintoneTarget


@dataclass(frozen=True)
class AuthConfig:
    allow_session_fallback: bool
    session_name: str
    storage_state_path: str | None


def _parse_target(config: dict[str, Any], args: argparse.Namespace) -> KintoneTarget:
    k = (config.get("kintone") or {}) if isinstance(config, dict) else {}

    subdomain = _coalesce(args.subdomain, k.get("subdomain"), "5atx9")
    space_id = _as_int(_coalesce(args.space_id, k.get("space_id"), 24), name="space_id")
    thread_id = _as_int(_coalesce(args.thread_id, k.get("thread_id"), 36), name="thread_id")

    if not isinstance(subdomain, str) or not subdomain.strip():
        raise ValueError("Invalid kintone subdomain")

    return KintoneTarget(subdomain=subdomain.strip(), space_id=space_id, thread_id=thread_id)


def _parse_preflight(
    config: dict[str, Any], args: argparse.Namespace, *, fallback_subdomain: str
) -> PreflightConfig:
    p = (config.get("preflight") or {}) if isinstance(config, dict) else {}
    enabled = bool(p.get("enabled", True)) and not bool(args.skip_preflight)

    subdomain = _coalesce(args.preflight_subdomain, p.get("subdomain"), fallback_subdomain, "5atx9")
    space_id = _as_int(
        _coalesce(args.preflight_space_id, p.get("space_id"), 81), name="preflight.space_id"
    )
    thread_id = _as_int(
        _coalesce(args.preflight_thread_id, p.get("thread_id"), 131), name="preflight.thread_id"
    )

    if not isinstance(subdomain, str) or not subdomain.strip():
        raise ValueError("Invalid preflight kintone subdomain")

    target = KintoneTarget(subdomain=subdomain.strip(), space_id=space_id, thread_id=thread_id)
    return PreflightConfig(enabled=enabled, target=target)


def _parse_auth_config(config: dict[str, Any], args: argparse.Namespace) -> AuthConfig:
    k = (config.get("kintone") or {}) if isinstance(config, dict) else {}

    allow_session_fallback = bool(k.get("allow_session_fallback", True))
    if args.disable_session_fallback:
        allow_session_fallback = False

    session_name_raw = _coalesce(args.session_name, k.get("session_name"), "kintone")
    session_name = _blank_to_none(session_name_raw)
    if session_name is None:
        raise ValueError("Invalid session_name")

    storage_state_path = _blank_to_none(_coalesce(args.storage_state, k.get("storage_state_path")))
    return AuthConfig(
        allow_session_fallback=allow_session_fallback,
        session_name=session_name,
        storage_state_path=storage_state_path,
    )


def _format_preflight_comment(year: int, month: int, day: int) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        "[AX preflight]\n"
        "本番投稿前の投稿確認です。\n"
        f"対象日: {year}年{month}月{day}日\n"
        f"実行時刻: {timestamp}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="kintone-gas-price-notification runner")
    ap.add_argument("--input", help="path to input JSON (otherwise stdin)")

    ap.add_argument("--year", type=int, help="default: current year")
    ap.add_argument("--month", type=int, help="default: current month")
    ap.add_argument("--day", type=int, default=None, help="default: 10")
    ap.add_argument(
        "--fallback-days",
        dest="fallback_days",
        type=int,
        default=None,
        help="if the report page is 404, try previous days (default: 2)",
    )
    ap.add_argument("--price", type=float, help="optional override; skips fetch")

    ap.add_argument("--subdomain", help="kintone subdomain (overrides config)")
    ap.add_argument("--space-id", dest="space_id", type=int, help="kintone space id (overrides config)")
    ap.add_argument("--thread-id", dest="thread_id", type=int, help="kintone thread id (overrides config)")
    ap.add_argument("--preflight-subdomain", help="preflight kintone subdomain (overrides config)")
    ap.add_argument(
        "--preflight-space-id",
        dest="preflight_space_id",
        type=int,
        help="preflight kintone space id (overrides config)",
    )
    ap.add_argument(
        "--preflight-thread-id",
        dest="preflight_thread_id",
        type=int,
        help="preflight kintone thread id (overrides config)",
    )
    ap.add_argument("--username", help="kintone username (avoid; prefer env/secrets)")
    ap.add_argument("--password", help="kintone password (avoid; prefer env/secrets)")
    ap.add_argument("--session-name", help="session fallback name (default: kintone)")
    ap.add_argument("--storage-state", help="session storage_state path (overrides config)")
    ap.add_argument(
        "--disable-session-fallback",
        action="store_true",
        help="disable storage_state fallback and require password auth",
    )

    ap.add_argument("--interactive", action="store_true", default=None, help="prompt for credentials if missing")
    ap.add_argument("--dry-run", action="store_true", default=None, help="do not post to kintone; only print JSON result")
    ap.add_argument("--post", action="store_true", help="actually post to kintone (overrides dry_run)")
    ap.add_argument("--skip-preflight", action="store_true", help="skip sandbox preflight check")

    args = ap.parse_args(argv)

    raw = _read_json_input(args.input)
    config = raw.get("config") if isinstance(raw, dict) else None
    params = raw.get("params") if isinstance(raw, dict) else None
    config = config if isinstance(config, dict) else {}
    params = params if isinstance(params, dict) else {}

    now = datetime.now()
    year = _as_int(_coalesce(args.year, params.get("year"), now.year), name="year")
    month = _as_int(_coalesce(args.month, params.get("month"), now.month), name="month")
    day_input = _as_int(_coalesce(args.day, params.get("day"), 10), name="day")
    fallback_days = _as_int(
        _coalesce(args.fallback_days, params.get("fallback_days"), 2), name="fallback_days"
    )
    if fallback_days < 0:
        raise ValueError("fallback_days must be >= 0")

    dry_run_cfg = bool(config.get("dry_run", True))
    dry_run = dry_run_cfg if args.dry_run is None else bool(args.dry_run)
    if args.post:
        dry_run = False

    interactive_cfg = bool(config.get("interactive", False))
    interactive = interactive_cfg if args.interactive is None else bool(args.interactive)

    target = _parse_target(config, args)
    preflight = _parse_preflight(config, args, fallback_subdomain=target.subdomain)
    auth = _parse_auth_config(config, args)

    # Price: allow override so tests don't rely on external site availability.
    price_override = _coalesce(args.price, params.get("price"))
    if price_override is not None:
        price = _as_float(price_override, name="price")
        resolved_day = day_input
        result = {"price": price, "date": f"{year}年{month}月{resolved_day}日", "url": None, "day": resolved_day}
    else:
        from fetch_gas_price import fetch_gas_price

        result = fetch_gas_price(year, month, day_input, fallback_days=fallback_days)
        price = float(result["price"])
        resolved_day = int(result.get("day") or day_input)

    comment = _format_comment(month, price)
    preflight_comment = _format_preflight_comment(year, month, resolved_day)

    posted = False
    comment_id = None
    auth_mode = None
    auth_storage_state_path = None
    preflight_executed = False
    preflight_comment_id = None
    preflight_auth_mode = None
    preflight_storage_state_path = None
    if not dry_run:
        k = (config.get("kintone") or {}) if isinstance(config, dict) else {}
        username = _blank_to_none(_coalesce(args.username, k.get("username"), os.environ.get("KINTONE_USERNAME")))
        password = _blank_to_none(_coalesce(args.password, k.get("password"), os.environ.get("KINTONE_PASSWORD")))

        if preflight.enabled:
            preflight_res = post_thread_comment(
                preflight.target.subdomain,
                preflight.target.space_id,
                preflight.target.thread_id,
                preflight_comment,
                username=username,
                password=password,
                interactive=interactive,
                allow_session_fallback=auth.allow_session_fallback,
                session_name=auth.session_name,
                storage_state_path=auth.storage_state_path,
            )
            preflight_executed = True
            preflight_comment_id = preflight_res.get("id")
            preflight_auth_mode = preflight_res.get("_auth")
            preflight_storage_state_path = preflight_res.get("_storage_state")

        # Prevent accidental password logging by not printing them anywhere.
        res = post_thread_comment(
            target.subdomain,
            target.space_id,
            target.thread_id,
            comment,
            username=username,
            password=password,
            interactive=interactive,
            allow_session_fallback=auth.allow_session_fallback,
            session_name=auth.session_name,
            storage_state_path=auth.storage_state_path,
        )
        posted = True
        comment_id = res.get("id")
        auth_mode = res.get("_auth")
        auth_storage_state_path = res.get("_storage_state")

    out = {
        "status": "success",
        "data": {
            "year": year,
            "month": month,
            "day": day_input,
            "resolved_day": resolved_day,
            "fallback_days": fallback_days,
            "fallback_used": resolved_day != day_input,
            "price": price,
            "date": result.get("date"),
            "source_url": result.get("url"),
            "comment": comment,
            "posted": posted,
            "preflight": {
                "enabled": preflight.enabled,
                "executed": preflight_executed,
                "comment_id": preflight_comment_id,
                "auth_mode": preflight_auth_mode,
                "storage_state_path": preflight_storage_state_path,
                "kintone": {
                    "subdomain": preflight.target.subdomain,
                    "space_id": preflight.target.space_id,
                    "thread_id": preflight.target.thread_id,
                },
            },
            "kintone": {
                "subdomain": target.subdomain,
                "space_id": target.space_id,
                "thread_id": target.thread_id,
                "comment_id": comment_id,
                "auth_mode": auth_mode,
                "allow_session_fallback": auth.allow_session_fallback,
                "session_name": auth.session_name,
                "storage_state_path": auth.storage_state_path,
                "storage_state_path_effective": auth_storage_state_path,
            },
        },
    }

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001 - CLI boundary
        debug = os.environ.get("AX_DEBUG", "").strip() in ("1", "true", "yes", "on")
        err = {"status": "error", "error": {"type": type(e).__name__, "message": str(e)}}
        if debug:
            err["error"]["traceback"] = traceback.format_exc()
        print(json.dumps(err, ensure_ascii=False, indent=2), file=sys.stdout)
        raise SystemExit(1)


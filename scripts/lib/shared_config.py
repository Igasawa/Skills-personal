from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ORG_PROFILE_FILE = "org-profile.json"


def resolve_ax_home(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def org_profile_path(*, ax_home: Path | None = None) -> Path:
    return resolve_ax_home(ax_home) / "configs" / ORG_PROFILE_FILE


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_optional_clean_str(value: Any) -> str | None:
    s = _as_clean_str(value)
    return s if s else None


def normalize_org_profile(raw: dict[str, Any]) -> dict[str, Any]:
    data = _as_dict(raw)
    org = _as_dict(data.get("organization"))
    receipt = _as_dict(org.get("receipt"))
    urls = _as_dict(data.get("urls"))

    profile_key = _as_clean_str(data.get("profile_key")) or "default"
    config_version = _as_clean_str(data.get("config_version"))
    tenant_name = _as_optional_clean_str(org.get("name"))
    receipt_name = _as_optional_clean_str(receipt.get("name"))
    receipt_name_fallback = _as_optional_clean_str(receipt.get("name_fallback"))
    locale = _as_optional_clean_str(org.get("locale"))
    timezone = _as_optional_clean_str(org.get("timezone"))

    mfcloud_expense_list = urls.get("mfcloud_expense_list")
    if mfcloud_expense_list is not None:
        mfcloud_expense_list = _as_clean_str(mfcloud_expense_list) or None

    return {
        "config_version": config_version,
        "profile_key": profile_key,
        "organization": {
            "name": tenant_name,
            "receipt": {
                "name": receipt_name,
                "name_fallback": receipt_name_fallback,
            },
            "locale": locale,
            "timezone": timezone,
        },
        "urls": {
            "amazon_orders": _as_optional_clean_str(urls.get("amazon_orders")),
            "rakuten_orders": _as_optional_clean_str(urls.get("rakuten_orders")),
            "mfcloud_accounts": _as_optional_clean_str(urls.get("mfcloud_accounts")),
            "mfcloud_expense_list": mfcloud_expense_list,
        },
    }


def load_org_profile(*, ax_home: Path | None = None, path: Path | None = None) -> tuple[dict[str, Any], Path]:
    target = path.expanduser() if path is not None else org_profile_path(ax_home=ax_home)
    raw = _read_json(target)
    if not raw:
        return {}, target
    return normalize_org_profile(raw), target

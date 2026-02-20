#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

DEFAULT_AMAZON_ORDERS_URL = "https://www.amazon.co.jp/gp/your-account/order-history"
DEFAULT_RAKUTEN_ORDERS_URL = "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order"
DEFAULT_MFCLOUD_ACCOUNTS_URL = "https://expense.moneyforward.com/accounts"
DEFAULT_SKILL_CONFIG_NAME = "mfcloud-expense-receipt-reconcile.json"
DEFAULT_ORG_PROFILE_NAME = "org-profile.json"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            if isinstance(value, str) and not value.strip():
                continue
            return value
    return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(encoded, encoding="utf-8")


def _resolve_ax_home(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _extract_org_profile_fragment(skill_payload: dict[str, Any]) -> dict[str, Any]:
    config = _as_dict(skill_payload.get("config"))
    tenant = _as_dict(config.get("tenant"))
    tenant_receipt = _as_dict(tenant.get("receipt"))
    tenant_urls = _as_dict(tenant.get("urls"))
    legacy_urls = _as_dict(config.get("urls"))
    legacy_rakuten = _as_dict(config.get("rakuten"))

    profile_key = _clean_str(_coalesce(tenant.get("key"), config.get("tenant_key"), "default")) or "default"
    receipt_name = _clean_str(_coalesce(tenant_receipt.get("name"), config.get("receipt_name")))
    receipt_name_fallback = _clean_str(_coalesce(tenant_receipt.get("name_fallback"), config.get("receipt_name_fallback")))
    org_name = _clean_str(_coalesce(tenant.get("name"), config.get("tenant_name"), receipt_name))

    amazon_orders = _clean_str(_coalesce(tenant_urls.get("amazon_orders"), legacy_urls.get("amazon_orders"), DEFAULT_AMAZON_ORDERS_URL))
    rakuten_orders = _clean_str(
        _coalesce(
            tenant_urls.get("rakuten_orders"),
            legacy_rakuten.get("orders_url"),
            legacy_urls.get("rakuten_orders"),
            DEFAULT_RAKUTEN_ORDERS_URL,
        )
    )
    mfcloud_accounts = _clean_str(
        _coalesce(tenant_urls.get("mfcloud_accounts"), legacy_urls.get("mfcloud_accounts"), DEFAULT_MFCLOUD_ACCOUNTS_URL)
    )
    mfcloud_expense_list = _coalesce(tenant_urls.get("mfcloud_expense_list"), legacy_urls.get("mfcloud_expense_list"))
    if isinstance(mfcloud_expense_list, str):
        mfcloud_expense_list = mfcloud_expense_list.strip() or None

    return {
        "config_version": "1",
        "profile_key": profile_key,
        "organization": {
            "name": org_name,
            "receipt": {
                "name": receipt_name,
                "name_fallback": receipt_name_fallback,
            },
        },
        "urls": {
            "amazon_orders": amazon_orders,
            "rakuten_orders": rakuten_orders,
            "mfcloud_accounts": mfcloud_accounts,
            "mfcloud_expense_list": mfcloud_expense_list,
        },
    }


def _merge_values(current: Any, incoming: Any, *, overwrite: bool) -> Any:
    if overwrite:
        return incoming
    if current is None:
        return incoming
    if isinstance(current, str) and not current.strip():
        return incoming
    return current


def _merge_org_profile(existing: dict[str, Any], incoming: dict[str, Any], *, overwrite: bool) -> dict[str, Any]:
    base = _as_dict(existing).copy()
    if not base:
        return incoming

    organization = _as_dict(base.get("organization")).copy()
    organization_receipt = _as_dict(organization.get("receipt")).copy()
    incoming_organization = _as_dict(incoming.get("organization"))
    incoming_receipt = _as_dict(incoming_organization.get("receipt"))

    organization["name"] = _merge_values(organization.get("name"), incoming_organization.get("name"), overwrite=overwrite)
    organization_receipt["name"] = _merge_values(organization_receipt.get("name"), incoming_receipt.get("name"), overwrite=overwrite)
    organization_receipt["name_fallback"] = _merge_values(
        organization_receipt.get("name_fallback"),
        incoming_receipt.get("name_fallback"),
        overwrite=overwrite,
    )
    organization["receipt"] = organization_receipt

    urls = _as_dict(base.get("urls")).copy()
    incoming_urls = _as_dict(incoming.get("urls"))
    for key in ("amazon_orders", "rakuten_orders", "mfcloud_accounts", "mfcloud_expense_list"):
        urls[key] = _merge_values(urls.get(key), incoming_urls.get(key), overwrite=overwrite)

    merged = base
    merged["config_version"] = _merge_values(merged.get("config_version"), incoming.get("config_version"), overwrite=overwrite)
    merged["profile_key"] = _merge_values(merged.get("profile_key"), incoming.get("profile_key"), overwrite=overwrite)
    merged["organization"] = organization
    merged["urls"] = urls
    return merged


def _as_non_empty_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _validate_org_profile_minimum(profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    data = _as_dict(profile)
    organization = _as_dict(data.get("organization"))
    receipt = _as_dict(organization.get("receipt"))
    urls = _as_dict(data.get("urls"))

    config_version = _as_non_empty_str(data.get("config_version"))
    if config_version != "1":
        errors.append("config_version must be '1'.")

    org_name = _as_non_empty_str(organization.get("name"))
    if org_name is None:
        errors.append("organization.name is required.")

    receipt_name = _as_non_empty_str(receipt.get("name"))
    if receipt_name is None:
        errors.append("organization.receipt.name is required.")

    receipt_name_fallback = _as_non_empty_str(receipt.get("name_fallback"))
    if receipt_name_fallback is None:
        errors.append("organization.receipt.name_fallback is required.")

    for key in ("amazon_orders", "rakuten_orders", "mfcloud_accounts"):
        raw = _as_non_empty_str(urls.get(key))
        if raw is None:
            errors.append(f"urls.{key} is required.")
            continue
        if not _looks_like_url(raw):
            errors.append(f"urls.{key} must be a valid absolute URL.")

    optional_expense_url = urls.get("mfcloud_expense_list")
    optional_expense_url_str = _as_non_empty_str(optional_expense_url)
    if optional_expense_url_str is not None and not _looks_like_url(optional_expense_url_str):
        errors.append("urls.mfcloud_expense_list must be a valid absolute URL when set.")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate skill config values to org-profile.json")
    parser.add_argument("--ax-home", help="override AX_HOME")
    parser.add_argument("--skill-config", help="override skill config file path")
    parser.add_argument("--org-profile", help="override org-profile file path")
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing org-profile values")
    parser.add_argument("--apply", action="store_true", help="write changes to org-profile.json")
    args = parser.parse_args(argv)

    ax_home = _resolve_ax_home(args.ax_home)
    skill_config_path = Path(args.skill_config).expanduser() if args.skill_config else ax_home / "configs" / DEFAULT_SKILL_CONFIG_NAME
    org_profile_path = Path(args.org_profile).expanduser() if args.org_profile else ax_home / "configs" / DEFAULT_ORG_PROFILE_NAME

    skill_payload = _read_json(skill_config_path)
    if not skill_payload:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": f"Skill config not found or invalid: {skill_config_path}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    incoming = _extract_org_profile_fragment(skill_payload)
    existing = _read_json(org_profile_path)
    merged = _merge_org_profile(existing, incoming, overwrite=args.overwrite)
    validation_errors = _validate_org_profile_minimum(merged)

    changed = merged != existing
    result = {
        "status": "error" if validation_errors else "success",
        "mode": "apply" if args.apply else "dry-run",
        "changed": changed,
        "paths": {
            "skill_config": str(skill_config_path),
            "org_profile": str(org_profile_path),
        },
        "overwrite": bool(args.overwrite),
        "validation_errors": validation_errors,
        "org_profile": merged,
    }

    if validation_errors:
        result["written"] = False
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    if args.apply and changed:
        _write_json(org_profile_path, merged)
        result["written"] = True
    else:
        result["written"] = False

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

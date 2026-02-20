from __future__ import annotations

import argparse
import pytest

from run_core import _parse_config, _validate_receipt_name_guard


def _base_args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "input": None,
        "year": 2026,
        "month": 1,
        "dry_run": False,
        "output_dir": None,
        "amazon_orders_url": None,
        "mfcloud_accounts_url": None,
        "mfcloud_expense_list_url": None,
        "amazon_storage_state": None,
        "mfcloud_storage_state": None,
        "rakuten_storage_state": None,
        "monthly_notes": None,
        "receipt_name": None,
        "receipt_name_fallback": None,
        "min_pdf_success_rate": None,
        "history_only_receipt_flow": None,
        "skip_receipt_name": False,
        "enable_rakuten": None,
        "rakuten_orders_url": None,
        "interactive": None,
        "headed": None,
        "slow_mo_ms": None,
        "date_window_days": None,
        "max_candidates_per_mf": None,
        "skip_amazon": False,
        "skip_rakuten": False,
        "skip_mfcloud": False,
        "skip_reconcile": False,
        "mf_draft_create": False,
        "print_list": False,
        "print_sources": None,
        "preflight": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_parse_config_prefers_tenant_fields_over_legacy() -> None:
    args = _base_args()
    raw = {
        "config": {
            "tenant": {
                "key": "corp-a",
                "name": "Tenant Name",
                "receipt": {"name": "Tenant Receipt", "name_fallback": "Tenant Fallback"},
                "urls": {
                    "amazon_orders": "https://tenant.example/amazon",
                    "rakuten_orders": "https://tenant.example/rakuten",
                    "mfcloud_accounts": "https://tenant.example/accounts",
                    "mfcloud_expense_list": "https://tenant.example/expenses",
                },
            },
            "receipt_name": "Legacy Receipt",
            "receipt_name_fallback": "Legacy Fallback",
            "urls": {
                "amazon_orders": "https://legacy.example/amazon",
                "mfcloud_accounts": "https://legacy.example/accounts",
                "mfcloud_expense_list": "https://legacy.example/expenses",
            },
            "rakuten": {"orders_url": "https://legacy.example/rakuten"},
        }
    }

    rc, year, month = _parse_config(args, raw)

    assert (year, month) == (2026, 1)
    assert rc.tenant_key == "corp-a"
    assert rc.tenant_name == "Tenant Name"
    assert rc.receipt_name == "Tenant Receipt"
    assert rc.receipt_name_fallback == "Tenant Fallback"
    assert rc.amazon_orders_url == "https://tenant.example/amazon"
    assert rc.rakuten_orders_url == "https://tenant.example/rakuten"
    assert rc.mfcloud_accounts_url == "https://tenant.example/accounts"
    assert rc.mfcloud_expense_list_url == "https://tenant.example/expenses"
    assert rc.resolved_sources["receipt_name"] == "config.tenant.receipt.name"
    assert rc.resolved_sources["amazon_orders_url"] == "config.tenant.urls.amazon_orders"
    assert rc.deprecation_warnings == []


def test_parse_config_keeps_legacy_compatibility() -> None:
    args = _base_args()
    raw = {
        "config": {
            "tenant_name": "Legacy Tenant Name",
            "tenant_key": "legacy-key",
            "receipt_name": "Legacy Receipt",
            "receipt_name_fallback": "Legacy Fallback",
            "urls": {
                "amazon_orders": "https://legacy.example/amazon",
                "mfcloud_accounts": "https://legacy.example/accounts",
                "mfcloud_expense_list": "https://legacy.example/expenses",
            },
            "rakuten": {"orders_url": "https://legacy.example/rakuten"},
        }
    }

    rc, _, _ = _parse_config(args, raw)

    assert rc.tenant_key == "legacy-key"
    assert rc.tenant_name == "Legacy Tenant Name"
    assert rc.receipt_name == "Legacy Receipt"
    assert rc.receipt_name_fallback == "Legacy Fallback"
    assert rc.amazon_orders_url == "https://legacy.example/amazon"
    assert rc.rakuten_orders_url == "https://legacy.example/rakuten"
    assert rc.mfcloud_accounts_url == "https://legacy.example/accounts"
    assert rc.mfcloud_expense_list_url == "https://legacy.example/expenses"
    assert rc.resolved_sources["receipt_name"] == "config.receipt_name"
    assert rc.resolved_sources["amazon_orders_url"] == "config.urls.amazon_orders"
    assert rc.resolved_sources["tenant_name"] == "config.tenant_name"
    assert any("config.receipt_name" in w for w in rc.deprecation_warnings)
    assert any("config.urls.amazon_orders" in w for w in rc.deprecation_warnings)


def test_parse_config_cli_overrides_tenant() -> None:
    args = _base_args(
        receipt_name="CLI Receipt",
        receipt_name_fallback="CLI Fallback",
        amazon_orders_url="https://cli.example/amazon",
        mfcloud_expense_list_url="https://cli.example/expenses",
    )
    raw = {
        "config": {
            "tenant": {
                "receipt": {"name": "Tenant Receipt", "name_fallback": "Tenant Fallback"},
                "urls": {
                    "amazon_orders": "https://tenant.example/amazon",
                    "mfcloud_expense_list": "https://tenant.example/expenses",
                },
            }
        }
    }

    rc, _, _ = _parse_config(args, raw)

    assert rc.receipt_name == "CLI Receipt"
    assert rc.receipt_name_fallback == "CLI Fallback"
    assert rc.amazon_orders_url == "https://cli.example/amazon"
    assert rc.mfcloud_expense_list_url == "https://cli.example/expenses"
    assert rc.resolved_sources["receipt_name"] == "cli.receipt_name"
    assert rc.resolved_sources["amazon_orders_url"] == "cli.amazon_orders_url"


def test_parse_config_amazon_threshold_prefers_cli_then_tenant() -> None:
    args = _base_args(min_pdf_success_rate=0.9)
    raw = {
        "config": {
            "tenant": {
                "urls": {"mfcloud_expense_list": "https://tenant.example/expenses"},
                "amazon": {"min_pdf_success_rate": 0.7},
            },
            "amazon": {"min_pdf_success_rate": 0.6},
        }
    }

    rc, _, _ = _parse_config(args, raw)
    assert rc.amazon_min_pdf_success_rate == 0.9
    assert rc.resolved_sources["amazon_min_pdf_success_rate"] == "cli.min_pdf_success_rate"


def test_parse_config_amazon_history_flow_defaults_true() -> None:
    args = _base_args()
    raw = {"config": {"urls": {"mfcloud_expense_list": "https://example/expenses"}}}

    rc, _, _ = _parse_config(args, raw)
    assert rc.history_only_receipt_flow is True
    assert rc.resolved_sources["history_only_receipt_flow"] == "default.history_only_receipt_flow"


def test_parse_config_receipt_defaults_use_placeholders() -> None:
    args = _base_args()
    raw = {"config": {"tenant": {"urls": {"mfcloud_expense_list": "https://example/expenses"}}}}

    rc, _, _ = _parse_config(args, raw)
    assert rc.receipt_name == "YOUR_COMPANY_NAME"
    assert rc.receipt_name_fallback == "YOUR_COMPANY_NAME_FALLBACK"
    assert rc.resolved_sources["receipt_name"] == "default.receipt_name"
    assert rc.resolved_sources["receipt_name_fallback"] == "default.receipt_name_fallback"
    assert rc.deprecation_warnings == []


def test_parse_config_uses_org_profile_when_skill_values_missing() -> None:
    args = _base_args()
    raw = {"config": {}}
    org_profile = {
        "config_version": "1",
        "profile_key": "corp-shared",
        "organization": {
            "name": "Org Tenant",
            "receipt": {"name": "Org Receipt", "name_fallback": "Org Fallback"},
        },
        "urls": {
            "amazon_orders": "https://org.example/amazon",
            "rakuten_orders": "https://org.example/rakuten",
            "mfcloud_accounts": "https://org.example/accounts",
            "mfcloud_expense_list": "https://org.example/expenses",
        },
    }

    rc, _, _ = _parse_config(args, raw, org_profile=org_profile)

    assert rc.receipt_name == "Org Receipt"
    assert rc.receipt_name_fallback == "Org Fallback"
    assert rc.amazon_orders_url == "https://org.example/amazon"
    assert rc.rakuten_orders_url == "https://org.example/rakuten"
    assert rc.mfcloud_accounts_url == "https://org.example/accounts"
    assert rc.mfcloud_expense_list_url == "https://org.example/expenses"
    assert rc.tenant_name == "Org Tenant"
    assert rc.tenant_key == "corp-shared"
    assert rc.resolved_sources["receipt_name"] == "org_profile.organization.receipt.name"
    assert rc.resolved_sources["amazon_orders_url"] == "org_profile.urls.amazon_orders"


def test_parse_config_ignores_blank_org_profile_values() -> None:
    args = _base_args()
    raw = {"config": {"tenant": {"urls": {"mfcloud_expense_list": "https://example/expenses"}}}}
    org_profile = {
        "profile_key": "default",
        "organization": {
            "name": "   ",
            "receipt": {"name": " ", "name_fallback": "  "},
        },
        "urls": {
            "amazon_orders": " ",
            "rakuten_orders": " ",
            "mfcloud_accounts": " ",
            "mfcloud_expense_list": None,
        },
    }

    rc, _, _ = _parse_config(args, raw, org_profile=org_profile)

    assert rc.receipt_name == "YOUR_COMPANY_NAME"
    assert rc.receipt_name_fallback == "YOUR_COMPANY_NAME_FALLBACK"
    assert rc.amazon_orders_url == "https://www.amazon.co.jp/gp/your-account/order-history"
    assert rc.rakuten_orders_url == "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order"
    assert rc.mfcloud_accounts_url == "https://expense.moneyforward.com/accounts"
    assert rc.resolved_sources["receipt_name"] == "default.receipt_name"
    assert rc.resolved_sources["amazon_orders_url"] == "default.amazon_orders_url"


def test_parse_config_skill_values_override_org_profile() -> None:
    args = _base_args()
    raw = {
        "config": {
            "tenant": {
                "key": "skill-tenant",
                "name": "Skill Tenant",
                "receipt": {"name": "Skill Receipt", "name_fallback": "Skill Fallback"},
                "urls": {
                    "amazon_orders": "https://skill.example/amazon",
                    "rakuten_orders": "https://skill.example/rakuten",
                    "mfcloud_accounts": "https://skill.example/accounts",
                    "mfcloud_expense_list": "https://skill.example/expenses",
                },
            }
        }
    }
    org_profile = {
        "profile_key": "corp-shared",
        "organization": {
            "name": "Org Tenant",
            "receipt": {"name": "Org Receipt", "name_fallback": "Org Fallback"},
        },
        "urls": {
            "amazon_orders": "https://org.example/amazon",
            "rakuten_orders": "https://org.example/rakuten",
            "mfcloud_accounts": "https://org.example/accounts",
            "mfcloud_expense_list": "https://org.example/expenses",
        },
    }

    rc, _, _ = _parse_config(args, raw, org_profile=org_profile)

    assert rc.receipt_name == "Skill Receipt"
    assert rc.receipt_name_fallback == "Skill Fallback"
    assert rc.amazon_orders_url == "https://skill.example/amazon"
    assert rc.rakuten_orders_url == "https://skill.example/rakuten"
    assert rc.mfcloud_accounts_url == "https://skill.example/accounts"
    assert rc.mfcloud_expense_list_url == "https://skill.example/expenses"
    assert rc.tenant_name == "Skill Tenant"
    assert rc.tenant_key == "skill-tenant"
    assert rc.resolved_sources["receipt_name"] == "config.tenant.receipt.name"
    assert rc.resolved_sources["amazon_orders_url"] == "config.tenant.urls.amazon_orders"


def test_receipt_name_guard_blocks_placeholder_on_download_run() -> None:
    args = _base_args()
    raw = {"config": {"tenant": {"urls": {"mfcloud_expense_list": "https://example/expenses"}}}}
    rc, _, _ = _parse_config(args, raw)

    with pytest.raises(ValueError, match="invalid receipt fields are still active"):
        _validate_receipt_name_guard(args, rc)


def test_receipt_name_guard_allows_placeholder_on_dry_run() -> None:
    args = _base_args(dry_run=True)
    raw = {"config": {"tenant": {"urls": {"mfcloud_expense_list": "https://example/expenses"}}}}
    rc, _, _ = _parse_config(args, raw)

    _validate_receipt_name_guard(args, rc)


def test_receipt_name_guard_allows_placeholder_when_skip_receipt_name() -> None:
    args = _base_args(skip_receipt_name=True)
    raw = {"config": {"tenant": {"urls": {"mfcloud_expense_list": "https://example/expenses"}}}}
    rc, _, _ = _parse_config(args, raw)

    _validate_receipt_name_guard(args, rc)

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_VALIDATE = REPO_ROOT / "scripts" / "validate_org_profile.py"
SCRIPT_MIGRATE = REPO_ROOT / "scripts" / "config_migrate.py"
SCHEMA_PATH = REPO_ROOT / "docs" / "shared-config-schema.json"


def _run_python(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_validate_org_profile_rejects_invalid_uri_and_datetime(tmp_path: Path) -> None:
    payload = {
        "config_version": "1",
        "profile_key": "default",
        "organization": {
            "name": "Example Corp",
            "receipt": {"name": "Example Corp", "name_fallback": "Example Corp"},
            "locale": "ja",
            "timezone": "Asia/Tokyo",
        },
        "urls": {
            "amazon_orders": "not-a-url",
            "rakuten_orders": "still-not-url",
            "mfcloud_accounts": "x",
            "mfcloud_expense_list": None,
        },
        "metadata": {
            "updated_by": "ops",
            "updated_at": "not-a-date",
        },
    }
    target = tmp_path / "org-profile.invalid.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    proc = _run_python(
        [
            str(SCRIPT_VALIDATE),
            "--schema",
            str(SCHEMA_PATH),
            "--file",
            str(target),
        ]
    )

    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out["status"] == "error"
    messages = [item.get("message", "") for item in out.get("schema_errors", [])]
    assert any("valid absolute URI" in msg for msg in messages)
    assert any("valid date-time" in msg for msg in messages)


def test_config_migrate_apply_rejects_invalid_profile(tmp_path: Path) -> None:
    skill_config_path = tmp_path / "mfcloud-expense-receipt-reconcile.json"
    org_profile_path = tmp_path / "org-profile.json"
    skill_config_path.write_text('{"config": {}}', encoding="utf-8")

    proc = _run_python(
        [
            str(SCRIPT_MIGRATE),
            "--skill-config",
            str(skill_config_path),
            "--org-profile",
            str(org_profile_path),
            "--apply",
        ]
    )

    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out["status"] == "error"
    assert out["written"] is False
    assert any("organization.name is required." in msg for msg in out.get("validation_errors", []))
    assert not org_profile_path.exists()


def test_validate_org_profile_rejects_forbidden_secret_like_values(tmp_path: Path) -> None:
    payload = {
        "config_version": "1",
        "profile_key": "default",
        "organization": {
            "name": "Example Corp",
            "receipt": {"name": "Example Corp", "name_fallback": "Example Corp"},
            "locale": "ja",
            "timezone": "Asia/Tokyo",
        },
        "urls": {
            "amazon_orders": "https://www.amazon.co.jp/gp/your-account/order-history",
            "rakuten_orders": "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order",
            "mfcloud_accounts": "https://expense.moneyforward.com/accounts",
            "mfcloud_expense_list": None,
        },
        "metadata": {
            "updated_by": "ops",
            "updated_at": "2026-02-20T00:00:00+09:00",
            "notes": "-----BEGIN PRIVATE KEY-----",
        },
    }
    target = tmp_path / "org-profile.secret-like.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    proc = _run_python(
        [
            str(SCRIPT_VALIDATE),
            "--schema",
            str(SCHEMA_PATH),
            "--file",
            str(target),
        ]
    )

    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out["status"] == "error"
    assert "$.metadata.notes" in out.get("forbidden_values", [])

#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

FORBIDDEN_KEY_PARTS = ("secret", "password", "token", "api_key", "apikey")
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _scan_forbidden_keys(value: Any, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                findings.append(f"{path}.{key}")
            findings.extend(_scan_forbidden_keys(child, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            findings.extend(_scan_forbidden_keys(child, path=f"{path}[{idx}]"))
    return findings


def _scan_forbidden_values(value: Any, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            findings.extend(_scan_forbidden_values(child, path=f"{path}.{key}"))
        return findings
    if isinstance(value, list):
        for idx, child in enumerate(value):
            findings.extend(_scan_forbidden_values(child, path=f"{path}[{idx}]"))
        return findings
    if not isinstance(value, str):
        return findings

    candidate = value.strip()
    if not candidate:
        return findings
    for pattern in FORBIDDEN_VALUE_PATTERNS:
        if pattern.search(candidate):
            findings.append(path)
            break
    return findings


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _looks_like_absolute_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _looks_like_datetime(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def _manual_format_checks(data: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    urls = _as_dict(_as_dict(data).get("urls"))
    metadata = _as_dict(_as_dict(data).get("metadata"))

    for key in ("amazon_orders", "rakuten_orders", "mfcloud_accounts"):
        raw = urls.get(key)
        if not isinstance(raw, str):
            continue
        if not _looks_like_absolute_url(raw):
            findings.append({"path": f"$[\"urls\"][\"{key}\"]", "message": "must be a valid absolute URI"})

    optional_expense = urls.get("mfcloud_expense_list")
    if isinstance(optional_expense, str) and optional_expense.strip() and not _looks_like_absolute_url(optional_expense):
        findings.append({"path": "$[\"urls\"][\"mfcloud_expense_list\"]", "message": "must be a valid absolute URI"})

    updated_at = metadata.get("updated_at")
    if isinstance(updated_at, str) and updated_at.strip() and not _looks_like_datetime(updated_at):
        findings.append({"path": "$[\"metadata\"][\"updated_at\"]", "message": "must be a valid date-time"})

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate org-profile JSON against schema and policy checks.")
    parser.add_argument("--schema", default="docs/shared-config-schema.json")
    parser.add_argument("--file", default="docs/org-profile.template.json")
    args = parser.parse_args(argv)

    schema_path = Path(args.schema).expanduser().resolve()
    file_path = Path(args.file).expanduser().resolve()
    if not schema_path.exists():
        print(json.dumps({"status": "error", "message": f"Schema file not found: {schema_path}"}, ensure_ascii=False, indent=2))
        return 1
    if not file_path.exists():
        print(json.dumps({"status": "error", "message": f"Target file not found: {file_path}"}, ensure_ascii=False, indent=2))
        return 1

    schema = _read_json(schema_path)
    data = _read_json(file_path)

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    manual_format_errors = _manual_format_checks(data)
    forbidden = _scan_forbidden_keys(data)
    forbidden_values = _scan_forbidden_values(data)

    result = {
        "status": "success" if not errors and not manual_format_errors and not forbidden and not forbidden_values else "error",
        "schema": str(schema_path),
        "file": str(file_path),
        "schema_errors": [
            {
                "path": "$" + "".join(f"[{json.dumps(p, ensure_ascii=False)}]" for p in err.absolute_path),
                "message": err.message,
            }
            for err in errors
        ]
        + manual_format_errors,
        "forbidden_keys": forbidden,
        "forbidden_values": forbidden_values,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

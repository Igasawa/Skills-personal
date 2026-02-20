#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

FORBIDDEN_KEY_PARTS = ("secret", "password", "token", "api_key", "apikey")


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

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    forbidden = _scan_forbidden_keys(data)

    result = {
        "status": "success" if not errors and not forbidden else "error",
        "schema": str(schema_path),
        "file": str(file_path),
        "schema_errors": [
            {
                "path": "$" + "".join(f"[{json.dumps(p, ensure_ascii=False)}]" for p in err.absolute_path),
                "message": err.message,
            }
            for err in errors
        ],
        "forbidden_keys": forbidden,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

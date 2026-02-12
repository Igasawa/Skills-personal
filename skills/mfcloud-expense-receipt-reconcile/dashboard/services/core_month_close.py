from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .core_shared import _artifact_root, _read_json

MONTH_CLOSE_CHECKLIST_KEYS: tuple[str, ...] = (
    "expense_submission",
    "document_printout",
    "mf_accounting_link",
)
MONTH_CLOSE_CHECKLIST_OPTIONAL_LEGACY_KEYS: tuple[str, ...] = ("transportation_expense",)


def _default_month_close_checklist() -> dict[str, bool]:
    return {
        "expense_submission": False,
        "document_printout": False,
        "mf_accounting_link": False,
    }


def _month_close_checklist_path_for_ym(ym: str):
    reports_dir = _artifact_root() / ym / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir / "month_close_checklist.json"


def _read_month_close_checklist_for_ym(ym: str) -> dict[str, Any]:
    checklist_path = _month_close_checklist_path_for_ym(ym)
    data = _read_json(checklist_path)
    if not isinstance(data, dict) or data.get("ym") != ym:
        return {
            "ym": ym,
            "checklist": _default_month_close_checklist(),
            "updated_at": None,
        }
    checklist_raw = data.get("checklist")
    if not isinstance(checklist_raw, dict):
        checklist_raw = {}
    normalized: dict[str, bool] = {}
    for key in MONTH_CLOSE_CHECKLIST_KEYS:
        normalized[key] = bool(checklist_raw.get(key) is True)
    return {
        "ym": ym,
        "checklist": normalized,
        "updated_at": data.get("updated_at"),
    }


def _validate_month_close_checklist_payload(payload: Any) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="checklist must be a dict.")
    payload_keys = set(payload.keys())
    expected_keys = set(MONTH_CLOSE_CHECKLIST_KEYS)
    optional_legacy_keys = set(MONTH_CLOSE_CHECKLIST_OPTIONAL_LEGACY_KEYS)
    missing_keys = expected_keys - payload_keys
    unknown_keys = payload_keys - expected_keys - optional_legacy_keys
    if missing_keys or unknown_keys:
        raise HTTPException(
            status_code=400,
            detail=(
                "checklist must contain required keys and no unknown keys. "
                f"required={sorted(expected_keys)} optional_legacy={sorted(optional_legacy_keys)} "
                f"missing={sorted(missing_keys)} unknown={sorted(unknown_keys)}"
            ),
        )
    normalized: dict[str, bool] = {}
    for key in MONTH_CLOSE_CHECKLIST_KEYS:
        value = payload.get(key)
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"checklist.{key} must be a boolean.")
        normalized[key] = value
    return normalized


def _incomplete_month_close_checklist_keys(checklist: Any) -> list[str]:
    if not isinstance(checklist, dict):
        checklist = {}
    return [key for key in MONTH_CLOSE_CHECKLIST_KEYS if checklist.get(key) is not True]


def _is_month_close_checklist_complete(checklist: Any) -> bool:
    return not _incomplete_month_close_checklist_keys(checklist)

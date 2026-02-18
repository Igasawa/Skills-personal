#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
from typing import Any

try:
    from .run_support_constants import BODY_DATE_PATTERNS, DATE_TOKEN_RE, FRONTMATTER_RE, REVIEW_KEY_CANDIDATES
except Exception:  # pragma: no cover - direct script execution fallback
    from run_support_constants import BODY_DATE_PATTERNS, DATE_TOKEN_RE, FRONTMATTER_RE, REVIEW_KEY_CANDIDATES


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _as_int(value: Any, *, name: str, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid integer for {name}: {value!r}") from e


def _as_string_list(value: Any, *, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else list(default)
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                out.append(s)
        return out or list(default)
    return list(default)


def _parse_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    s = str(value).strip().strip("'\"")
    if not s:
        return None
    m = DATE_TOKEN_RE.search(s)
    if not m:
        return None
    token = m.group(1)
    try:
        return dt.date.fromisoformat(token)
    except ValueError:
        return None


def _extract_frontmatter_date(text: str) -> tuple[dt.date | None, str | None, str | None]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, None, None
    frontmatter = m.group(1)
    review_source: str | None = None
    review_date: dt.date | None = None
    review_date_key: str | None = None
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = key.strip().lower()
        if normalized in REVIEW_KEY_CANDIDATES:
            d = _parse_date(value)
            if d:
                review_date = d
                review_date_key = key.strip()
        if normalized == "review_source" and review_source is None:
            candidate = _blank_to_none(value)
            if candidate:
                review_source = candidate
    if review_date is not None:
        return review_date, review_date_key, review_source
    return None, None, review_source


def _extract_body_date(text: str) -> tuple[dt.date | None, str | None]:
    for pat in BODY_DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        d = _parse_date(m.group(1))
        if d:
            return d, "body_marker"
    return None, None


def _prepend_review_frontmatter(
    text: str,
    review_date_iso: str,
    review_source: str | None = None,
) -> tuple[str, bool]:
    """
    Insert or update review-related frontmatter fields, then return the full text.

    If frontmatter already exists, updates `last_reviewed` and
    `review_source` in-place. If no frontmatter exists, a new block is
    prepended.
    """
    lines = _ensure_frontmatter_fields(
        text,
        review_date_iso=review_date_iso,
        review_source=review_source,
    )
    return lines, True


def _extract_review_date(text: str) -> tuple[dt.date | None, str | None, str | None]:
    d, src, src_value = _extract_frontmatter_date(text)
    if d:
        return d, src, src_value
    d_body, src_body = _extract_body_date(text)
    return d_body, src_body, None


def _ensure_frontmatter_fields(
    text: str,
    review_date_iso: str,
    review_source: str | None = None,
) -> str:
    linesep = "\r\n" if "\r\n" in text else "\n"
    m = FRONTMATTER_RE.match(text)
    if not m:
        lines = [
            "---",
            f"last_reviewed: {review_date_iso}",
            *( [f"review_source: {review_source}"] if review_source else []),
            "---",
            "",
        ]
        return f"{linesep.join(lines)}{text}"

    fm = m.group(1)
    rest = text[m.end() :]
    fm_lines = fm.splitlines()
    fm_lines = _upsert_frontmatter_field(fm_lines, "last_reviewed", review_date_iso)
    if review_source:
        fm_lines = _upsert_frontmatter_field(fm_lines, "review_source", review_source)

    new_fm = linesep.join(fm_lines)
    if rest and not rest.startswith(("\r", "\n")):
        rest = linesep + rest
    return f"{text[:m.start()]}---{linesep}{new_fm}{linesep}---{rest}"


def _upsert_frontmatter_field(lines: list[str], key: str, value: str) -> list[str]:
    target = key.strip().lower()
    out: list[str] = []
    inserted = False
    prefix = f"{key}:"
    for line in lines:
        if not line or ":" not in line:
            out.append(line)
            continue
        left, _ = line.split(":", 1)
        if left.strip().lower() == target:
            out.append(f"{prefix} {value}")
            inserted = True
        else:
            out.append(line)
    if not inserted:
        out.append(f"{prefix} {value}")
    return out


def _now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


__all__ = [
    "_coalesce",
    "_blank_to_none",
    "_as_bool",
    "_as_int",
    "_as_string_list",
    "_parse_date",
    "_extract_frontmatter_date",
    "_extract_body_date",
    "_prepend_review_frontmatter",
    "_extract_review_date",
    "_now_utc_iso",
]

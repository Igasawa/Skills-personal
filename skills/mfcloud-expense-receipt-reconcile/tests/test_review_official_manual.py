from __future__ import annotations

from scripts.review_official_manual import extract_iso_date


def test_extract_iso_date_supports_last_reviewed_formats() -> None:
    text = """
last_reviewed: 2026-02-15
last_reviewed = 2026/02/14
"""

    assert extract_iso_date(text) == "2026-02-15"


def test_extract_iso_date_supports_japanese_labels() -> None:
    text = """
最終更新: 2026-02-10
最終更新日: 2026/02/11
最終検証日=2026-02-12
"""

    assert extract_iso_date(text) == "2026-02-10"


def test_extract_iso_date_ignores_invalid_date() -> None:
    assert extract_iso_date("last_reviewed: 2026/99/99") is None

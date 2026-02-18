#!/usr/bin/env python3
from __future__ import annotations

import re


REVIEW_KEY_CANDIDATES = {
    "last_verified",
    "last_reviewed",
    "reviewed_at",
    "last_checked",
    "updated_at",
    "最終確認日",
    "最終更新日",
    "last_review",
    "review_date",
}

FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.DOTALL)
DATE_TOKEN_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
URL_RE = re.compile(r"https?://[^\s<>()\"']+")

BODY_DATE_PATTERNS = [
    re.compile(r"^\s*Last\s+Review(?:ed)?\s*[:：]\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*Review\s+Date\s*[:：]\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*最終確認日\s*[:：]\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE),
    re.compile(r"^\s*最終更新日\s*[:：]\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE),
    re.compile(r"^\s*Last\s+Verified\s*[:：]\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*Last\s+Reviewed\s*[:：]\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE | re.IGNORECASE),
]


__all__ = [
    "REVIEW_KEY_CANDIDATES",
    "FRONTMATTER_RE",
    "DATE_TOKEN_RE",
    "URL_RE",
    "BODY_DATE_PATTERNS",
]

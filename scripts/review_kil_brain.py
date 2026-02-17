#!/usr/bin/env python3
"""Review helper for KIL outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
BRAIN_INDEX = DOCS_DIR / "AGENT_BRAIN_INDEX.jsonl"
BRAIN_REVIEW = DOCS_DIR / "AGENT_BRAIN_REVIEW.jsonl"

REVIEW_SCORE_RANGES = {
    "high": 0.85,
    "medium": 0.65,
    "low": 0.0,
}


@dataclass
class ReviewResult:
    commit: str
    risk: str
    severity: str
    confidence: float
    needs_human_review: bool
    needs_soon: bool
    issues: List[str]
    recommendations: List[str]


def _load_latest_records() -> List[Dict[str, Any]]:
    if not BRAIN_INDEX.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in BRAIN_INDEX.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _infer_review_plan(record: Dict[str, Any]) -> ReviewResult:
    commit = str(record.get("commit", ""))
    risk = str(record.get("risk", "medium")).lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    confidence = float(record.get("confidence", 0.0) or 0.0)
    scope = record.get("scope", [])
    if not isinstance(scope, list):
        scope = []
    scope = [str(s).strip() for s in scope if str(s).strip()]

    deadlines = []
    dl = record.get("review_deadline")
    needs_soon = False
    if isinstance(dl, str) and dl.strip():
        deadlines = [dl.strip()]
        needs_soon = True

    issues: List[str] = []
    recommendations: List[str] = []

    needs_human_review = risk == "high" or confidence < REVIEW_SCORE_RANGES.get(risk, 0.0)
    if needs_human_review:
        issues.append("High review risk or low model confidence.")

    if needs_soon:
        recommendations.append("Review deadline exists. prioritize before next risky changes.")

    if "docs" in scope:
        recommendations.append("Check documentation impact and keep docs sync.")

    if "ci" in scope:
        recommendations.append("Run post-commit + test pipeline checks for CI-related touches.")

    severity = "low"
    if risk == "high":
        severity = "critical"
    elif risk == "medium":
        severity = "medium"
    else:
        severity = "low"

    return ReviewResult(
        commit=commit,
        risk=risk,
        severity=severity,
        confidence=confidence,
        needs_human_review=needs_human_review,
        needs_soon=needs_soon,
        issues=issues,
        recommendations=recommendations,
    )


def _append_review(record: ReviewResult) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "commit": record.commit,
        "risk": record.risk,
        "severity": record.severity,
        "confidence": record.confidence,
        "needs_human_review": record.needs_human_review,
        "needs_soon": record.needs_soon,
        "issues": record.issues,
        "recommendations": record.recommendations,
    }
    with BRAIN_REVIEW.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def review_kil_brain(commit_hash: Optional[str] = None) -> int:
    records = _load_latest_records()
    if not records:
        return 0

    target: Optional[Dict[str, Any]] = None
    if commit_hash:
        for rec in reversed(records):
            if str(rec.get("commit")) == str(commit_hash):
                target = rec
                break
    if target is None:
        target = records[-1]

    if not target:
        return 0

    result = _infer_review_plan(target)
    _append_review(result)
    return 0


def _main() -> int:
    return review_kil_brain()


if __name__ == "__main__":
    raise SystemExit(_main())

#!/usr/bin/env python3
"""Generate a remediation plan from an incident bundle."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from error_common import (
    ensure_error_dirs,
    normalize_incident_id,
    now_utc_iso,
    read_json,
    read_text,
    redact_text,
    resolve_reports_root,
    write_json,
    write_status,
    write_text,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

try:
    from dashboard.services import ai_chat
except Exception:  # pragma: no cover - optional runtime dependency
    ai_chat = None  # type: ignore[assignment]


PLAN_SKILL_NAME = "error-plan"
DEFAULT_CONFIDENCE = 0.55
MAX_EVIDENCE_ITEMS = 12
MAX_EVIDENCE_EXCERPT_CHARS = 220
NULLISH_EVIDENCE_VALUES = {"", "-", "none", "null", "nil", "n/a", "na", "unknown"}
LOW_CONFIDENCE_THRESHOLD = 0.60
NO_SIGNAL_CONFIDENCE_CAP = 0.55

EVIDENCE_HINT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("auth", r"AUTH_REQUIRED|auth_required|login|signin|storage_state"),
    ("timeout", r"timeout|timed out|network"),
    ("selector", r"selector|not found|locator|dom"),
    ("worker", r"worker_exit|process_ended_without_final_status|returncode"),
    ("exception", r"RuntimeError|Exception|Traceback|Error:"),
)


TARGET_HINTS = {
    "preflight": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/run.py",
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core.py",
    ],
    "preflight_mf": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core.py",
        "skills/mfcloud-expense-receipt-reconcile/scripts/mfcloud_extract.mjs",
    ],
    "amazon_download": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/amazon_download.mjs",
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core_pipeline.py",
    ],
    "rakuten_download": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/rakuten_download.mjs",
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core_pipeline.py",
    ],
    "amazon_print": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/collect_print.py",
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core_pipeline.py",
    ],
    "rakuten_print": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/collect_print.py",
        "skills/mfcloud-expense-receipt-reconcile/scripts/run_core_pipeline.py",
    ],
    "mf_reconcile": [
        "skills/mfcloud-expense-receipt-reconcile/scripts/reconcile.py",
        "skills/mfcloud-expense-receipt-reconcile/scripts/mfcloud_extract.mjs",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate error remediation plan")
    parser.add_argument("--incident-id", required=True, help="Incident id in error_inbox")
    parser.add_argument("--root", default="", help="Reports root override")
    parser.add_argument("--force", action="store_true", help="Overwrite existing plan files")
    return parser.parse_args()


def _default_verification_commands(step: str, year: int | None, month: int | None) -> list[str]:
    step_value = str(step or "").strip()
    commands: list[str] = []
    if step_value in {"amazon_download", "rakuten_download", "amazon_print", "rakuten_print"}:
        commands.append("python -m pytest -q tests/test_run_core_pipeline.py")
    elif step_value == "mf_reconcile":
        commands.append("python -m pytest -q tests/test_reconcile.py")
    else:
        commands.append("python -m pytest -q tests/test_run_smoke.py")

    if year is not None and month is not None:
        commands.append(
            f"python scripts/run.py --year {year} --month {month} --dry-run --skip-rakuten --skip-mfcloud"
        )
    return commands


def _compact_text(value: str, *, max_chars: int = MAX_EVIDENCE_EXCERPT_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _as_text_set(rows: list[Any]) -> set[str]:
    return {str(row).strip().lower() for row in rows if str(row).strip()}


def _is_nullish_evidence_value(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return text.lower() in NULLISH_EVIDENCE_VALUES


def _classify_log_line(line: str) -> str:
    text = str(line or "").strip()
    if not text:
        return ""
    for _, pattern in EVIDENCE_HINT_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "log_signal"
    return "log_context"


def _collect_incident_evidence(
    *,
    incident: dict[str, Any],
    message: str,
    log_excerpt: str,
    context_excerpt: str,
) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    seen: set[str] = set()

    def _append(*, source: str, path: str, kind: str, excerpt: str) -> None:
        compact = _compact_text(excerpt)
        if not compact:
            return
        dedupe_key = f"{source}|{path}|{kind}|{compact}".lower()
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        evidence.append(
            {
                "id": f"E{len(evidence) + 1}",
                "source": source,
                "path": path,
                "kind": kind,
                "excerpt": compact,
            }
        )

    incident_message = str(message or "").strip()
    if incident_message:
        _append(
            source="incident",
            path="incident.json:message",
            kind="summary_message",
            excerpt=incident_message,
        )

    signature = str(incident.get("error_signature") or "").strip()
    if signature:
        signature_excerpt = signature
        if incident_message and incident_message in signature:
            signature_excerpt = signature.split(incident_message, maxsplit=1)[0].strip(" |")
        _append(
            source="incident",
            path="incident.json:error_signature",
            kind="error_signature",
            excerpt=signature_excerpt,
        )

    context_payload: dict[str, Any] = {}
    try:
        parsed = json.loads(str(context_excerpt or ""))
        if isinstance(parsed, dict):
            context_payload = parsed
    except Exception:
        context_payload = {}

    for key in ("reason", "inferred_from", "mode", "returncode", "source"):
        if key not in context_payload:
            continue
        value = context_payload.get(key)
        if _is_nullish_evidence_value(value):
            continue
        text = str(value).strip()
        _append(
            source="context",
            path=f"context.json:{key}",
            kind="context_signal",
            excerpt=f"{key}={text}",
        )

    log_lines = [line.strip() for line in str(log_excerpt or "").splitlines() if line.strip()]
    classified_lines: list[tuple[str, str]] = []
    for line in log_lines:
        kind = _classify_log_line(line)
        if not kind:
            continue
        classified_lines.append((kind, line))
    signal_lines = [line for kind, line in classified_lines if kind == "log_signal"]
    context_lines = [line for kind, line in classified_lines if kind == "log_context"]

    selected_lines: list[tuple[str, str]] = []
    for line in signal_lines[:MAX_EVIDENCE_ITEMS]:
        selected_lines.append(("log_signal", line))
    if not selected_lines and context_lines:
        selected_lines.append(("log_context", context_lines[-1]))

    for kind, line in selected_lines:
        _append(
            source="log_tail",
            path="log_tail.txt",
            kind=kind,
            excerpt=line,
        )

    return evidence[:MAX_EVIDENCE_ITEMS]


def _build_unknowns(*, evidence: list[dict[str, str]], failure_class: str, step: str) -> list[str]:
    unknowns: list[str] = []
    has_log_context = any(str(row.get("source") or "") == "log_tail" for row in evidence if isinstance(row, dict))
    has_log_signal = any(
        str(row.get("source") or "") == "log_tail" and str(row.get("kind") or "") == "log_signal"
        for row in evidence
        if isinstance(row, dict)
    )
    if not has_log_signal:
        if has_log_context:
            unknowns.append("log_tail は開始/進行ログのみで失敗シグナルがないため、フルログ確認が必要です。")
        else:
            unknowns.append("log_tail に明確な失敗スタックがないため、フルログ確認が必要です。")
    if str(failure_class).strip() == "run_failed":
        unknowns.append("run_failed は失敗分類が広いため、再現実行で失敗境界の特定が必要です。")
    if str(step).strip() in {"amazon_download", "rakuten_download"}:
        unknowns.append("認証状態・セッション有効期限・サイトUI変更の切り分けが未完了です。")

    deduped: list[str] = []
    seen = set()
    for row in unknowns:
        key = str(row).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped[:6]


def _estimate_evidence_score(reason_text: str, evidence_text: str) -> int:
    reason = str(reason_text or "").lower()
    evidence = str(evidence_text or "").lower()
    if not reason or not evidence:
        return 0

    score = 0
    token_groups = (
        ("auth", ("auth", "login", "signin", "session", "cookie")),
        ("selector", ("selector", "locator", "dom", "not found")),
        ("timeout", ("timeout", "timed out", "network")),
        ("worker", ("worker_exit", "process_ended_without_final_status", "returncode", "exit")),
        ("exception", ("runtimeerror", "exception", "traceback", "error")),
    )
    for _, words in token_groups:
        reason_hit = any(word in reason for word in words)
        evidence_hit = any(word in evidence for word in words)
        if reason_hit and evidence_hit:
            score += 2

    reason_tokens = {tok for tok in re.findall(r"[a-z0-9_]+", reason) if len(tok) >= 4}
    evidence_tokens = {tok for tok in re.findall(r"[a-z0-9_]+", evidence) if len(tok) >= 4}
    score += len(reason_tokens & evidence_tokens)
    return score


def _select_evidence_ids_for_reason(reason: str, evidence: list[dict[str, str]]) -> list[str]:
    scored: list[tuple[int, str]] = []
    rows_by_id: dict[str, dict[str, str]] = {}
    for row in evidence:
        if not isinstance(row, dict):
            continue
        evidence_id = str(row.get("id") or "").strip()
        excerpt = str(row.get("excerpt") or "").strip()
        if not evidence_id or not excerpt:
            continue
        rows_by_id[evidence_id] = row
        score = _estimate_evidence_score(reason, excerpt)
        path = str(row.get("path") or "").lower()
        kind = str(row.get("kind") or "").lower()
        if path == "context.json:reason":
            score += 2
        elif path == "context.json:returncode":
            score += 1
        if kind == "log_signal":
            score += 1
        elif kind in {"summary_message", "error_signature", "log_context"}:
            score -= 1
        if score > 0:
            scored.append((score, evidence_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if scored:
        selected = [item[1] for item in scored[:2]]
        preferred_context_id = ""
        for row in evidence:
            if not isinstance(row, dict):
                continue
            if str(row.get("path") or "").lower() == "context.json:reason":
                preferred_context_id = str(row.get("id") or "").strip()
                if preferred_context_id:
                    break
        if preferred_context_id and preferred_context_id not in selected:
            if len(selected) == 1:
                selected.append(preferred_context_id)
            elif len(selected) >= 2:
                second = rows_by_id.get(selected[1], {})
                second_kind = str(second.get("kind") or "").lower()
                if second_kind in {"summary_message", "error_signature", "log_context"}:
                    selected[1] = preferred_context_id
        deduped: list[str] = []
        for evidence_id in selected:
            if evidence_id and evidence_id not in deduped:
                deduped.append(evidence_id)
        return deduped[:2]

    for preferred_path in ("context.json:reason", "context.json:returncode", "incident.json:message", "log_tail.txt"):
        for row in evidence:
            if not isinstance(row, dict):
                continue
            evidence_id = str(row.get("id") or "").strip()
            path = str(row.get("path") or "").strip().lower()
            if not evidence_id:
                continue
            if path == preferred_path:
                return [evidence_id]
    for row in evidence:
        evidence_id = str(row.get("id") or "").strip()
        if evidence_id:
            return [evidence_id]
    return []


def _attach_evidence_to_hypotheses(
    hypotheses: list[dict[str, Any]],
    evidence: list[dict[str, str]],
) -> list[dict[str, Any]]:
    valid_ids = _as_text_set([row.get("id") for row in evidence if isinstance(row, dict)])
    out: list[dict[str, Any]] = []
    for row in hypotheses:
        if not isinstance(row, dict):
            continue
        hypothesis_id = str(row.get("id") or "").strip()
        reason = str(row.get("reason") or "").strip()
        confidence = str(row.get("confidence") or "low").strip() or "low"
        if not hypothesis_id or not reason:
            continue
        provided_ids_raw = row.get("evidence_ids")
        provided_ids = []
        if isinstance(provided_ids_raw, list):
            for evidence_id in provided_ids_raw:
                text = str(evidence_id or "").strip()
                if not text:
                    continue
                if valid_ids and text.lower() not in valid_ids:
                    continue
                provided_ids.append(text)
        evidence_ids = provided_ids or _select_evidence_ids_for_reason(reason, evidence)
        out.append(
            {
                "id": hypothesis_id,
                "confidence": confidence,
                "reason": reason,
                "evidence_ids": evidence_ids,
            }
        )
    return out


def _build_hypothesis_evidence_map(hypotheses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in hypotheses:
        if not isinstance(row, dict):
            continue
        hypothesis_id = str(row.get("id") or "").strip()
        evidence_ids_raw = row.get("evidence_ids")
        if not hypothesis_id or not isinstance(evidence_ids_raw, list):
            continue
        evidence_ids = [str(value or "").strip() for value in evidence_ids_raw if str(value or "").strip()]
        out.append({"hypothesis_id": hypothesis_id, "evidence_ids": evidence_ids})
    return out


def _next_hypothesis_id(hypotheses: list[dict[str, Any]]) -> str:
    max_number = 0
    for row in hypotheses:
        if not isinstance(row, dict):
            continue
        hypothesis_id = str(row.get("id") or "").strip().upper()
        match = re.fullmatch(r"H(\d+)", hypothesis_id)
        if not match:
            continue
        max_number = max(max_number, int(match.group(1)))
    return f"H{max_number + 1 if max_number else 2}"


def _assess_evidence_quality(evidence: list[dict[str, str]]) -> dict[str, Any]:
    total_count = len(evidence)
    signal_count = 0
    strong_signal_count = 0
    weak_signal_count = 0
    strongest_rows: list[tuple[int, str]] = []

    for row in evidence:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").lower()
        kind = str(row.get("kind") or "").lower()
        evidence_id = str(row.get("id") or "").strip()
        row_score = 0

        if kind in {"log_signal", "context_signal"}:
            signal_count += 1
            row_score += 2
        else:
            weak_signal_count += 1
            row_score += 1

        if path == "context.json:reason":
            row_score += 5
            strong_signal_count += 1
        elif path == "context.json:returncode":
            row_score += 3
            strong_signal_count += 1
        elif kind == "log_signal":
            row_score += 4
            strong_signal_count += 1
        elif kind in {"summary_message", "error_signature", "log_context"}:
            row_score -= 1

        if evidence_id:
            strongest_rows.append((row_score, evidence_id))

    strongest_rows.sort(key=lambda item: (-item[0], item[1]))
    strongest_evidence_ids = [item[1] for item in strongest_rows[:3]]

    if total_count <= 0:
        score = 0.0
    else:
        raw_score = (strong_signal_count * 3 + signal_count * 2 + weak_signal_count) / max(1, total_count * 5)
        score = round(min(1.0, max(0.0, raw_score)), 2)

    has_failure_signal = bool(strong_signal_count > 0)
    if has_failure_signal and score >= 0.75:
        assessment = "strong"
    elif score >= 0.45:
        assessment = "medium"
    else:
        assessment = "weak"

    return {
        "total_count": total_count,
        "signal_count": signal_count,
        "strong_signal_count": strong_signal_count,
        "weak_signal_count": weak_signal_count,
        "has_failure_signal": has_failure_signal,
        "score": score,
        "assessment": assessment,
        "strongest_evidence_ids": strongest_evidence_ids,
    }


def _apply_confidence_guardrail(raw_confidence: float, evidence_quality: dict[str, Any]) -> float:
    confidence = round(max(0.0, min(1.0, float(raw_confidence))), 2)
    evidence_score = float(evidence_quality.get("score") or 0.0)
    has_failure_signal = bool(evidence_quality.get("has_failure_signal"))

    if not has_failure_signal:
        if evidence_score < 0.30:
            return round(min(confidence, 0.45), 2)
        return round(min(confidence, NO_SIGNAL_CONFIDENCE_CAP), 2)
    if evidence_score < 0.45:
        return round(min(confidence, LOW_CONFIDENCE_THRESHOLD), 2)
    return confidence


def _ensure_alternative_hypothesis(
    hypotheses: list[dict[str, Any]],
    *,
    step: str,
    failure_class: str,
    evidence: list[dict[str, str]],
    confidence_score: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in hypotheses:
        if isinstance(row, dict):
            out.append(dict(row))

    if confidence_score >= LOW_CONFIDENCE_THRESHOLD or len(out) >= 2:
        return out

    existing_reasons = " ".join(str(row.get("reason") or "") for row in out).lower()
    candidate_reasons: list[str] = []
    step_value = str(step or "").strip()
    failure_value = str(failure_class or "").strip()
    if step_value in {"amazon_download", "rakuten_download"}:
        candidate_reasons.append("認証セッション切れ、ログイン導線変更、または認証要求ページ遷移の可能性。")
    if failure_value == "run_failed":
        candidate_reasons.append("ワーカー実行環境や依存関係の不整合により process 終了している可能性。")
    candidate_reasons.append("エラーハンドリング境界の欠落により本来の例外情報が失われた可能性。")

    selected_reason = ""
    for reason in candidate_reasons:
        probe = str(reason or "").strip().lower()
        if not probe:
            continue
        if probe not in existing_reasons:
            selected_reason = reason
            break
    if not selected_reason:
        return out

    evidence_ids = _select_evidence_ids_for_reason(selected_reason, evidence)
    out.append(
        {
            "id": _next_hypothesis_id(out),
            "confidence": "low",
            "reason": selected_reason,
            "evidence_ids": evidence_ids,
        }
    )
    return out


def _build_cause_analysis(
    hypotheses: list[dict[str, Any]],
    evidence: list[dict[str, str]],
    evidence_quality: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence_by_id: dict[str, dict[str, str]] = {}
    for row in evidence:
        if not isinstance(row, dict):
            continue
        evidence_id = str(row.get("id") or "").strip()
        if evidence_id:
            evidence_by_id[evidence_id] = row

    has_failure_signal = bool(evidence_quality.get("has_failure_signal"))
    out: list[dict[str, Any]] = []
    for row in hypotheses:
        if not isinstance(row, dict):
            continue
        hypothesis_id = str(row.get("id") or "").strip()
        if not hypothesis_id:
            continue
        reason = str(row.get("reason") or "").strip()
        confidence = str(row.get("confidence") or "").strip() or "low"
        evidence_ids_raw = row.get("evidence_ids") if isinstance(row.get("evidence_ids"), list) else []
        evidence_ids = [str(value or "").strip() for value in evidence_ids_raw if str(value or "").strip()]

        supporting_evidence: list[dict[str, str]] = []
        has_strong_link = False
        has_medium_link = False
        for evidence_id in evidence_ids:
            evidence_row = evidence_by_id.get(evidence_id)
            if not isinstance(evidence_row, dict):
                continue
            path = str(evidence_row.get("path") or "")
            kind = str(evidence_row.get("kind") or "")
            excerpt = str(evidence_row.get("excerpt") or "")
            supporting_evidence.append(
                {
                    "id": evidence_id,
                    "path": path,
                    "kind": kind,
                    "excerpt": excerpt,
                }
            )
            path_lower = path.lower()
            kind_lower = kind.lower()
            if path_lower in {"context.json:reason", "context.json:returncode"} or kind_lower == "log_signal":
                has_strong_link = True
            elif kind_lower in {"context_signal", "summary_message", "error_signature"}:
                has_medium_link = True

        if has_strong_link:
            support_strength = "strong"
        elif has_medium_link:
            support_strength = "medium"
        else:
            support_strength = "weak"

        gaps: list[str] = []
        if not supporting_evidence:
            gaps.append("根拠IDが紐付いていないため、追加ログ取得が必要。")
        elif support_strength != "strong":
            gaps.append("直接的な失敗シグナル根拠が不足しているため、stderr/stacktrace確認が必要。")
        if not has_failure_signal:
            gaps.append("現在の証拠は失敗シグナル不足のため、仮説の確定には再現実行が必要。")

        out.append(
            {
                "hypothesis_id": hypothesis_id,
                "reason": reason,
                "confidence": confidence,
                "support_strength": support_strength,
                "evidence_ids": evidence_ids,
                "supporting_evidence": supporting_evidence[:3],
                "gaps": gaps[:3],
            }
        )
    return out


def _build_hypotheses(failure_class: str, step: str, message: str, log_excerpt: str) -> list[dict[str, str]]:
    low_message = " ".join((message + " " + log_excerpt).lower().split())
    items: list[dict[str, str]] = []
    if "timeout" in low_message or "network" in low_message:
        items.append(
            {
                "id": "H1",
                "confidence": "medium",
                "reason": "Network instability or timeout likely interrupted browser/script flow.",
            }
        )
    if "selector" in low_message or "not found" in low_message:
        items.append(
            {
                "id": "H2",
                "confidence": "medium",
                "reason": "UI selector drift likely broke element lookup during automation.",
            }
        )
    if str(failure_class).strip() == "run_failed" and not items:
        items.append(
            {
                "id": "H1",
                "confidence": "low",
                "reason": "Run failed without clear class-specific signal; inspect logs and replay mode.",
            }
        )
    if not items:
        items.append(
            {
                "id": "H1",
                "confidence": "low",
                "reason": "Insufficient evidence for direct cause; start with reproducible dry-run.",
            }
        )
    return items


def _build_actions(
    *,
    step: str,
    failure_class: str,
    verification_commands: list[str],
) -> list[dict[str, Any]]:
    step_text = str(step or "").strip()
    target_paths = TARGET_HINTS.get(step_text, [])
    actions: list[dict[str, Any]] = [
        {
            "id": "A1",
            "title": "Confirm reproduction path and isolate failure boundary",
            "priority": "P0",
            "risk": "low",
            "target_paths": target_paths,
            "verification": verification_commands[:1],
        },
        {
            "id": "A2",
            "title": "Apply minimal fix in the most likely target files",
            "priority": "P0",
            "risk": "medium",
            "target_paths": target_paths,
            "verification": verification_commands[:1],
        },
        {
            "id": "A3",
            "title": "Run verification suite and confirm non-regression",
            "priority": "P1",
            "risk": "low",
            "target_paths": [],
            "verification": verification_commands,
        },
    ]
    if str(failure_class).strip() == "auth_expired":
        actions.insert(
            1,
            {
                "id": "A1b",
                "title": "Refresh auth/session prerequisites",
                "priority": "P0",
                "risk": "low",
                "target_paths": [
                    "skills/mfcloud-expense-receipt-reconcile/scripts/run.py",
                    "skills/mfcloud-expense-receipt-reconcile/scripts/run_core.py",
                ],
                "verification": verification_commands[:1],
            },
        )
    return actions


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(raw[start : end + 1])
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _safe_string_list(value: Any, *, max_items: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for row in value:
        text = str(row or "").strip()
        if not text:
            continue
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _normalize_confidence(value: Any, *, default: float = DEFAULT_CONFIDENCE) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    if parsed < 0:
        return 0.0
    if parsed > 1:
        return 1.0
    return round(parsed, 2)


def _normalize_hypotheses(value: Any, *, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return fallback
    out: list[dict[str, Any]] = []
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            continue
        reason = str(row.get("reason") or row.get("statement") or "").strip()
        if not reason:
            continue
        evidence_ids: list[str] = []
        if isinstance(row.get("evidence_ids"), list):
            for evidence_id in row.get("evidence_ids"):
                text = str(evidence_id or "").strip()
                if text:
                    evidence_ids.append(text)
        out.append(
            {
                "id": str(row.get("id") or f"H{index}").strip() or f"H{index}",
                "confidence": str(row.get("confidence") or "low").strip().lower() or "low",
                "reason": reason,
                "evidence_ids": evidence_ids,
            }
        )
    return out or fallback


def _normalize_actions(
    value: Any,
    *,
    fallback: list[dict[str, Any]],
    verification_commands: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return fallback
    out: list[dict[str, Any]] = []
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("action") or "").strip()
        if not title:
            continue
        target_paths = _safe_string_list(row.get("target_paths"), max_items=10)
        verification = _safe_string_list(row.get("verification"), max_items=10)
        if not verification:
            verification = verification_commands[:1]
        try:
            estimated_minutes = int(row.get("estimated_minutes") or 20)
        except Exception:
            estimated_minutes = 20
        if estimated_minutes <= 0:
            estimated_minutes = 20
        out.append(
            {
                "id": str(row.get("id") or f"A{index}").strip() or f"A{index}",
                "title": title,
                "priority": str(row.get("priority") or "P1").strip().upper() or "P1",
                "risk": str(row.get("risk") or "medium").strip().lower() or "medium",
                "target_paths": target_paths,
                "verification": verification,
                "estimated_minutes": estimated_minutes,
            }
        )
    return out or fallback


def _build_default_card_summary(
    *,
    summary: str,
    actions: list[dict[str, Any]],
    confidence_score: float,
    risk_summary: str,
) -> dict[str, Any]:
    first_step = ""
    if actions:
        first = actions[0]
        first_step = str(first.get("title") or "").strip()
    eta = 0
    for row in actions:
        try:
            eta += int(row.get("estimated_minutes") or 0)
        except Exception:
            continue
    if eta <= 0:
        eta = max(20, len(actions) * 20)
    approval_required = bool(confidence_score < 0.8)
    return {
        "plan": summary,
        "first_step": first_step or "Inspect latest logs and reproduce safely",
        "eta_minutes": eta,
        "risk": risk_summary or "Medium: requires human review before execution.",
        "approval": "required" if approval_required else "optional",
    }


def _normalize_card_summary(
    value: Any,
    *,
    summary: str,
    actions: list[dict[str, Any]],
    confidence_score: float,
    risk_summary: str,
) -> dict[str, Any]:
    fallback = _build_default_card_summary(
        summary=summary,
        actions=actions,
        confidence_score=confidence_score,
        risk_summary=risk_summary,
    )
    if not isinstance(value, dict):
        return fallback
    plan = str(value.get("plan") or fallback["plan"]).strip() or fallback["plan"]
    first_step = str(value.get("first_step") or fallback["first_step"]).strip() or fallback["first_step"]
    try:
        eta_minutes = int(value.get("eta_minutes") or fallback["eta_minutes"])
    except Exception:
        eta_minutes = int(fallback["eta_minutes"])
    eta_minutes = eta_minutes if eta_minutes > 0 else int(fallback["eta_minutes"])
    risk = str(value.get("risk") or fallback["risk"]).strip() or fallback["risk"]
    approval = str(value.get("approval") or fallback["approval"]).strip().lower()
    if approval not in {"required", "optional"}:
        approval = str(fallback["approval"])
    return {
        "plan": plan,
        "first_step": first_step,
        "eta_minutes": eta_minutes,
        "risk": risk,
        "approval": approval,
    }


def _prompt_for_ai_plan(
    *,
    incident_id: str,
    incident: dict[str, Any],
    verification_commands: list[str],
    fallback_actions: list[dict[str, Any]],
    evidence: list[dict[str, str]],
    log_excerpt: str,
    context_excerpt: str,
) -> str:
    prompt_payload = {
        "incident_id": incident_id,
        "status": incident.get("status"),
        "step": incident.get("step"),
        "failure_class": incident.get("failure_class"),
        "message": incident.get("message"),
        "error_signature": incident.get("error_signature"),
        "verification_commands": verification_commands,
        "fallback_actions": fallback_actions,
        "evidence": evidence,
        "log_excerpt": log_excerpt,
        "context_excerpt": context_excerpt,
    }
    return (
        "You are an incident-planning assistant for unresolved incidents. "
        "Return only one JSON object (no markdown). "
        "Use concise actionable content and preserve safety-first ordering.\n"
        "Required fields:\n"
        "- summary: string\n"
        "- confidence_score: number between 0 and 1\n"
        "- risk_summary: string\n"
        "- root_cause_hypotheses: array of {id, confidence, reason, evidence_ids}\n"
        "- evidence: array of {id, source, path, kind, excerpt}\n"
        "- evidence_quality: {total_count, signal_count, strong_signal_count, weak_signal_count, has_failure_signal, score, assessment, strongest_evidence_ids}\n"
        "- hypothesis_evidence_map: array of {hypothesis_id, evidence_ids}\n"
        "- cause_analysis: array of {hypothesis_id, reason, confidence, support_strength, evidence_ids, supporting_evidence, gaps}\n"
        "- unknowns: string[]\n"
        "- actions: array of {id, title, priority, risk, target_paths, verification, estimated_minutes}\n"
        "- verification_commands: string[]\n"
        "- done_criteria: string[]\n"
        "- rollback: string\n"
        "- card_summary: {plan, first_step, eta_minutes, risk, approval}\n"
        "- antigravity_handoff: {executor, intent, notes, required_approval}\n"
        "If uncertain, keep confidence low and emphasize safe diagnostics first.\n"
        f"Incident context JSON:\n{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
    )


def _generate_ai_plan_payload(
    *,
    incident_id: str,
    incident: dict[str, Any],
    verification_commands: list[str],
    fallback_actions: list[dict[str, Any]],
    evidence: list[dict[str, str]],
    log_excerpt: str,
    context_excerpt: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    planner_meta: dict[str, Any] = {
        "mode": "heuristic",
        "skill": PLAN_SKILL_NAME,
    }
    if ai_chat is None:
        planner_meta["fallback_reason"] = "ai_chat module unavailable"
        return None, planner_meta

    try:
        status = ai_chat.get_chat_status()
    except Exception as exc:
        planner_meta["fallback_reason"] = f"ai status check failed: {exc}"
        return None, planner_meta

    if not bool(status.get("ready")):
        planner_meta["fallback_reason"] = str(status.get("reason") or "ai api key is not configured")
        return None, planner_meta

    prompt = _prompt_for_ai_plan(
        incident_id=incident_id,
        incident=incident,
        verification_commands=verification_commands,
        fallback_actions=fallback_actions,
        evidence=evidence,
        log_excerpt=log_excerpt,
        context_excerpt=context_excerpt,
    )
    try:
        response = ai_chat.chat(
            messages=[{"role": "user", "content": prompt}],
            page_context={"path": "/errors", "active_tab": "incidents", "title": "管理センター"},
            policy_profile=ai_chat.POLICY_PROFILE_STRUCTURED_JSON,
        )
    except Exception as exc:
        planner_meta["fallback_reason"] = f"ai chat failed: {exc}"
        return None, planner_meta

    reply = response.get("reply") if isinstance(response.get("reply"), dict) else {}
    content = str(reply.get("content") or "").strip()
    parsed = _extract_json_object(content)
    if not isinstance(parsed, dict):
        planner_meta["fallback_reason"] = "ai output was not valid json object"
        return None, planner_meta

    planner_meta.update(
        {
            "mode": "ai",
            "provider": str(response.get("provider") or "unknown"),
            "model": str(response.get("model") or status.get("model") or ""),
            "fallback_reason": "",
        }
    )
    return parsed, planner_meta


def _build_plan_markdown(plan: dict[str, Any], incident: dict[str, Any]) -> str:
    hypotheses = plan.get("root_cause_hypotheses") if isinstance(plan.get("root_cause_hypotheses"), list) else []
    evidence_rows = plan.get("evidence") if isinstance(plan.get("evidence"), list) else []
    evidence_quality = plan.get("evidence_quality") if isinstance(plan.get("evidence_quality"), dict) else {}
    hypothesis_map = plan.get("hypothesis_evidence_map") if isinstance(plan.get("hypothesis_evidence_map"), list) else []
    cause_analysis = plan.get("cause_analysis") if isinstance(plan.get("cause_analysis"), list) else []
    unknowns = plan.get("unknowns") if isinstance(plan.get("unknowns"), list) else []
    actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
    verification = plan.get("verification_commands") if isinstance(plan.get("verification_commands"), list) else []
    done = plan.get("done_criteria") if isinstance(plan.get("done_criteria"), list) else []
    card_summary = plan.get("card_summary") if isinstance(plan.get("card_summary"), dict) else {}
    execution = plan.get("execution") if isinstance(plan.get("execution"), dict) else {}
    lines: list[str] = [
        f"# Incident Plan: {plan.get('incident_id')}",
        "",
        "## Summary",
        f"- Failure class: {incident.get('failure_class') or '-'}",
        f"- Step: {incident.get('step') or '-'}",
        f"- Error signature: {incident.get('error_signature') or '-'}",
        f"- Message: {incident.get('message') or '-'}",
        f"- Planner: {plan.get('planner', {}).get('mode', '-') if isinstance(plan.get('planner'), dict) else '-'}",
        f"- Confidence: {plan.get('confidence_score') if plan.get('confidence_score') is not None else '-'}",
        f"- Risk: {plan.get('risk_summary') or '-'}",
        "",
        "## Card Summary",
        f"- Plan: {card_summary.get('plan') or '-'}",
        f"- First Step: {card_summary.get('first_step') or '-'}",
        f"- ETA (minutes): {card_summary.get('eta_minutes') if card_summary else '-'}",
        f"- Risk: {card_summary.get('risk') or '-'}",
        f"- Approval: {card_summary.get('approval') or '-'}",
        "",
        "## Root Cause Hypotheses",
    ]
    for item in hypotheses:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('id')}: {item.get('reason')} (confidence: {item.get('confidence')}, evidence: {', '.join(item.get('evidence_ids') or []) or '-'})"
        )
    lines += ["", "## Evidence"]
    for item in evidence_rows:
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("id") or "-")
        source = str(item.get("source") or "-")
        path = str(item.get("path") or "-")
        excerpt = str(item.get("excerpt") or "-")
        lines.append(f"- {evidence_id} [{source} / {path}]: {excerpt}")
    lines += ["", "## Evidence Quality"]
    lines.append(f"- Assessment: {evidence_quality.get('assessment') or '-'}")
    lines.append(f"- Score: {evidence_quality.get('score') if evidence_quality else '-'}")
    lines.append(f"- Has failure signal: {evidence_quality.get('has_failure_signal') if evidence_quality else '-'}")
    lines.append(f"- Evidence counts: total={evidence_quality.get('total_count', '-')}, signal={evidence_quality.get('signal_count', '-')}, strong={evidence_quality.get('strong_signal_count', '-')}, weak={evidence_quality.get('weak_signal_count', '-')}")
    strongest_ids = evidence_quality.get("strongest_evidence_ids") if isinstance(evidence_quality.get("strongest_evidence_ids"), list) else []
    lines.append(f"- Strongest evidence IDs: {', '.join(str(v) for v in strongest_ids) or '-'}")
    lines += ["", "## Hypothesis-Evidence Map"]
    for row in hypothesis_map:
        if not isinstance(row, dict):
            continue
        evidence_ids = row.get("evidence_ids") if isinstance(row.get("evidence_ids"), list) else []
        lines.append(f"- {row.get('hypothesis_id')}: {', '.join(str(v) for v in evidence_ids) or '-'}")
    lines += ["", "## Cause Analysis"]
    for row in cause_analysis:
        if not isinstance(row, dict):
            continue
        hypothesis_id = str(row.get("hypothesis_id") or "-")
        reason = str(row.get("reason") or "-")
        confidence = str(row.get("confidence") or "-")
        strength = str(row.get("support_strength") or "-")
        evidence_ids = row.get("evidence_ids") if isinstance(row.get("evidence_ids"), list) else []
        lines.append(
            f"- {hypothesis_id}: {reason} (confidence: {confidence}, support: {strength}, evidence: {', '.join(str(v) for v in evidence_ids) or '-'})"
        )
        supporting = row.get("supporting_evidence") if isinstance(row.get("supporting_evidence"), list) else []
        for support in supporting:
            if not isinstance(support, dict):
                continue
            lines.append(
                f"  - {support.get('id') or '-'} [{support.get('path') or '-'} / {support.get('kind') or '-'}]: {support.get('excerpt') or '-'}"
            )
        gaps = row.get("gaps") if isinstance(row.get("gaps"), list) else []
        for gap in gaps:
            lines.append(f"  - gap: {gap}")
    lines += ["", "## Unknowns"]
    for row in unknowns:
        lines.append(f"- {row}")
    lines += ["", "## Action Plan"]
    for item in actions:
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('id')} [{item.get('priority')}] {item.get('title')}")
        targets = item.get("target_paths") if isinstance(item.get("target_paths"), list) else []
        if targets:
            lines.append("  - target paths:")
            for path in targets:
                lines.append(f"    - {path}")
        checks = item.get("verification") if isinstance(item.get("verification"), list) else []
        if checks:
            lines.append("  - verification:")
            for cmd in checks:
                lines.append(f"    - `{cmd}`")
    lines += ["", "## Verification Commands"]
    for cmd in verification:
        lines.append(f"- `{cmd}`")
    lines += ["", "## Done Criteria"]
    for row in done:
        lines.append(f"- {row}")
    lines += [
        "",
        "## Rollback",
        f"- {plan.get('rollback') or 'Revert modified files and rerun verification.'}",
        "",
        "## Antigravity Handoff",
        f"- Executor: {execution.get('executor') or 'antigravity'}",
        f"- Requires approval: {execution.get('requires_approval')}",
        f"- Intent: {execution.get('intent') or 'Apply approved remediation plan'}",
    ]
    notes = execution.get("notes")
    if isinstance(notes, list):
        for note in notes:
            lines.append(f"- Note: {note}")
    lines += [""]
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    reports_root = resolve_reports_root(args.root)
    dirs = ensure_error_dirs(reports_root)
    incident_id = normalize_incident_id(args.incident_id)

    incident_dir = dirs["inbox"] / incident_id
    if not incident_dir.exists():
        raise SystemExit(f"incident not found in inbox: {incident_dir}")

    incident = read_json(incident_dir / "incident.json")
    if not isinstance(incident, dict):
        raise SystemExit(f"incident payload missing: {incident_dir / 'incident.json'}")

    plan_dir = dirs["plans"] / incident_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_json_path = plan_dir / "plan.json"
    plan_md_path = plan_dir / "plan.md"
    if (plan_json_path.exists() or plan_md_path.exists()) and not args.force:
        raise SystemExit("plan already exists; use --force to overwrite")

    year = incident.get("year")
    month = incident.get("month")
    year_value = int(year) if isinstance(year, int) else None
    month_value = int(month) if isinstance(month, int) else None
    step = str(incident.get("step") or "").strip()
    failure_class = str(incident.get("failure_class") or "unknown").strip()
    message = redact_text(str(incident.get("message") or "").strip())
    log_excerpt = read_text(incident_dir / "log_tail.txt")[:1500]
    context_excerpt = read_text(incident_dir / "context.json")[:2000]
    evidence = _collect_incident_evidence(
        incident=incident,
        message=message,
        log_excerpt=log_excerpt,
        context_excerpt=context_excerpt,
    )
    unknowns = _build_unknowns(
        evidence=evidence,
        failure_class=failure_class,
        step=step,
    )

    verification_commands = _default_verification_commands(step, year_value, month_value)
    hypotheses = _build_hypotheses(failure_class, step, message, log_excerpt)
    hypotheses = _attach_evidence_to_hypotheses(hypotheses, evidence)
    hypothesis_evidence_map = _build_hypothesis_evidence_map(hypotheses)
    actions = _build_actions(
        step=step,
        failure_class=failure_class,
        verification_commands=verification_commands,
    )
    summary = f"Remediation plan for {failure_class or 'unknown'} failure in {step or 'unknown step'}"
    done_criteria = [
        "Target error no longer reproduces in the same mode.",
        "Verification commands pass with no regression on critical path.",
    ]
    rollback = "Revert the modified files and re-run baseline verification."
    risk_summary = "Medium: update only the likely failure boundary first and verify before wider changes."

    ai_payload, planner_meta = _generate_ai_plan_payload(
        incident_id=incident_id,
        incident=incident,
        verification_commands=verification_commands,
        fallback_actions=actions,
        evidence=evidence,
        log_excerpt=log_excerpt,
        context_excerpt=context_excerpt,
    )
    if isinstance(ai_payload, dict):
        summary = str(ai_payload.get("summary") or summary).strip() or summary
        hypotheses = _normalize_hypotheses(
            ai_payload.get("root_cause_hypotheses"),
            fallback=hypotheses,
        )
        actions = _normalize_actions(
            ai_payload.get("actions"),
            fallback=actions,
            verification_commands=verification_commands,
        )
        unknowns = _safe_string_list(ai_payload.get("unknowns"), max_items=10) or unknowns
        ai_evidence = ai_payload.get("evidence")
        if isinstance(ai_evidence, list):
            normalized_ai_evidence: list[dict[str, str]] = []
            for index, row in enumerate(ai_evidence, start=1):
                if not isinstance(row, dict):
                    continue
                excerpt = _compact_text(str(row.get("excerpt") or ""))
                if not excerpt:
                    continue
                evidence_id = str(row.get("id") or f"E{index}").strip() or f"E{index}"
                normalized_ai_evidence.append(
                    {
                        "id": evidence_id,
                        "source": str(row.get("source") or "ai").strip() or "ai",
                        "path": str(row.get("path") or "").strip(),
                        "kind": str(row.get("kind") or "ai_inferred").strip() or "ai_inferred",
                        "excerpt": excerpt,
                    }
                )
            if normalized_ai_evidence:
                evidence = normalized_ai_evidence[:MAX_EVIDENCE_ITEMS]
        verification_commands = _safe_string_list(ai_payload.get("verification_commands"), max_items=20) or verification_commands
        done_criteria = _safe_string_list(ai_payload.get("done_criteria"), max_items=20) or done_criteria
        rollback = str(ai_payload.get("rollback") or rollback).strip() or rollback
        risk_summary = str(ai_payload.get("risk_summary") or risk_summary).strip() or risk_summary

    evidence_quality = _assess_evidence_quality(evidence)
    raw_confidence = _normalize_confidence(
        ai_payload.get("confidence_score") if isinstance(ai_payload, dict) else None,
        default=DEFAULT_CONFIDENCE,
    )
    confidence_score = _apply_confidence_guardrail(raw_confidence, evidence_quality)

    if not bool(evidence_quality.get("has_failure_signal")):
        weak_signal_note = "Current evidence lacks explicit failure signal, so full log/stderr confirmation is required."
        if weak_signal_note.lower() not in str(risk_summary).lower():
            risk_summary = f"{risk_summary} {weak_signal_note}".strip()

    hypotheses = _ensure_alternative_hypothesis(
        hypotheses,
        step=step,
        failure_class=failure_class,
        evidence=evidence,
        confidence_score=confidence_score,
    )
    hypotheses = _attach_evidence_to_hypotheses(hypotheses, evidence)
    hypothesis_evidence_map = _build_hypothesis_evidence_map(hypotheses)
    cause_analysis = _build_cause_analysis(hypotheses, evidence, evidence_quality)

    low_signal_unknown = "明示的な失敗シグナル根拠が不足しているため、stderr/フルログで最終確認が必要です。"
    if not bool(evidence_quality.get("has_failure_signal")) and low_signal_unknown not in unknowns:
        unknowns.append(low_signal_unknown)

    card_summary = _normalize_card_summary(
        ai_payload.get("card_summary") if isinstance(ai_payload, dict) else None,
        summary=summary,
        actions=actions,
        confidence_score=confidence_score,
        risk_summary=risk_summary,
    )
    handoff_raw = ai_payload.get("antigravity_handoff") if isinstance(ai_payload, dict) else None
    handoff_payload = handoff_raw if isinstance(handoff_raw, dict) else {}
    guardrail_requires_approval = bool(
        confidence_score < LOW_CONFIDENCE_THRESHOLD or not bool(evidence_quality.get("has_failure_signal"))
    )
    if guardrail_requires_approval:
        card_summary["approval"] = "required"
    requested_approval = handoff_payload.get("required_approval")
    if isinstance(requested_approval, bool):
        requires_approval = bool(requested_approval or guardrail_requires_approval)
    else:
        requires_approval = bool(card_summary.get("approval") != "optional" or guardrail_requires_approval)

    plan_payload: dict[str, Any] = {
        "incident_id": incident_id,
        "generated_at": now_utc_iso(),
        "summary": summary,
        "confidence_score": confidence_score,
        "risk_summary": risk_summary,
        "card_summary": card_summary,
        "root_cause_hypotheses": hypotheses,
        "hypothesis_evidence_map": hypothesis_evidence_map,
        "evidence": evidence,
        "evidence_quality": evidence_quality,
        "cause_analysis": cause_analysis,
        "unknowns": unknowns,
        "actions": actions,
        "verification_commands": verification_commands,
        "done_criteria": done_criteria,
        "rollback": rollback,
        "planner": planner_meta,
        "execution": {
            "target_engine": "antigravity",
            "executor": str(handoff_payload.get("executor") or "antigravity"),
            "intent": str(handoff_payload.get("intent") or "Implement approved remediation plan for this incident."),
            "requires_approval": requires_approval,
            "notes": _safe_string_list(handoff_payload.get("notes"), max_items=10),
        },
        "lifecycle": {
            "from": "unresolved",
            "plan_generated": "plan_proposed",
            "after_approval": "approved",
            "after_handoff": "handed_off",
        },
        "policy": {
            "max_loops": 8,
            "max_runtime_minutes": 45,
            "same_error_limit": 3,
            "scope": "skills/mfcloud-expense-receipt-reconcile/**",
        },
        "source_incident_path": str(incident_dir),
    }

    plan_markdown = _build_plan_markdown(plan_payload, incident)
    write_json(plan_json_path, plan_payload)
    write_text(plan_md_path, plan_markdown + ("\n" if not plan_markdown.endswith("\n") else ""))

    planned_at = now_utc_iso()
    incident["status"] = "plan_proposed"
    incident["plan_state"] = "plan_proposed"
    incident["plan_path"] = str(plan_json_path)
    incident["planned_at"] = planned_at
    incident["updated_at"] = planned_at
    incident["execution_owner"] = "antigravity"
    incident["approval_required"] = requires_approval
    incident["planner"] = planner_meta
    write_json(incident_dir / "incident.json", incident)
    write_status(incident_dir, "plan_proposed")

    print(
        json.dumps(
            {
                "status": "ok",
                "incident_id": incident_id,
                "plan_json": str(plan_json_path),
                "plan_md": str(plan_md_path),
                "year": year_value,
                "month": month_value,
                "planner_mode": str(planner_meta.get("mode") or "heuristic"),
                "plan_state": "plan_proposed",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

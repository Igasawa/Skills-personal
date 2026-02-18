from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any
import subprocess

from fastapi.responses import JSONResponse

from services import core
def api_get_kil_review_payload(
    source: str = "auto",
    limit: int = 20,
    only_review: bool = False,
) -> JSONResponse:
    requested = str(source or "auto").strip().lower()
    requested_source = requested if requested in {"auto", "index", "markdown", "all", "fallback"} else "auto"
    requested = "all" if requested_source == "fallback" else requested_source

    requested_limit = max(1, min(int(limit), 200))
    def _resolve_kil_docs_dir() -> tuple[Path, list[dict[str, Any]]]:
        candidate_defs: list[tuple[str, Path]] = [
            ("skill_root/docs", core.SKILL_ROOT / "docs"),
            ("skills/docs", core.SKILL_ROOT.parent / "docs"),
            ("repo_root/docs", core.SKILL_ROOT.parent.parent / "docs"),
            ("repo_parent/docs", core.SKILL_ROOT.parent.parent.parent / "docs"),
            ("cwd/docs", Path.cwd() / "docs"),
        ]

        diagnostics: list[dict[str, Any]] = []
        selected_dir: Path | None = None
        first_existing_dir: Path | None = None

        for label, candidate in candidate_defs:
            exists = candidate.exists()
            is_dir = candidate.is_dir() if exists else False
            contains_index = False
            contains_markdown = False
            contains_review = False

            if exists and is_dir:
                if first_existing_dir is None:
                    first_existing_dir = candidate
                contains_index = (candidate / "AGENT_BRAIN_INDEX.jsonl").exists()
                contains_markdown = (candidate / "AGENT_BRAIN.md").exists()
                contains_review = (candidate / "AGENT_BRAIN_REVIEW.jsonl").exists()
                has_kil_files = contains_index or contains_markdown
                status = "has_kil_documents" if has_kil_files else "empty_directory"
                if has_kil_files and selected_dir is None:
                    selected_dir = candidate
            else:
                status = "missing" if not exists else "not_directory"

            diagnostics.append(
                {
                    "label": label,
                    "path": str(candidate),
                    "exists": bool(exists),
                    "is_dir": bool(is_dir),
                    "status": status,
                    "contains_index": bool(contains_index),
                    "contains_markdown": bool(contains_markdown),
                    "contains_review": bool(contains_review),
                }
            )

        if selected_dir is None:
            selected_dir = first_existing_dir or candidate_defs[-1][1]

        resolved = str(selected_dir)
        for entry in diagnostics:
            if entry["path"] == resolved:
                if entry["status"] == "missing":
                    entry["status"] = "selected_fallback"
                elif entry["status"] == "not_directory":
                    entry["status"] = "selected_non_directory_fallback"
                elif entry["status"] == "empty_directory":
                    entry["status"] = "selected_empty_directory"
                else:
                    entry["status"] = "selected_kil_documents"
                entry["selected"] = True
            else:
                entry["selected"] = False

        return selected_dir, diagnostics

    docs_dir, docs_dir_diagnostics = _resolve_kil_docs_dir()
    docs_dir_candidates = [row["path"] for row in docs_dir_diagnostics]
    index_path = docs_dir / "AGENT_BRAIN_INDEX.jsonl"
    markdown_path = docs_dir / "AGENT_BRAIN.md"
    review_path = docs_dir / "AGENT_BRAIN_REVIEW.jsonl"
    today = datetime.now().date()

    def _read_file_iso_mtime(path: Path) -> str | None:
        if not path.exists():
            return None
        try:
            return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        except Exception:
            return None

    def _safe_read_text(path: Path) -> str:
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return path.read_text(encoding="utf-8", errors="ignore")

    def _as_str(value: object) -> str:
        text = str(value or "").strip()
        return text

    def _to_date(value: object) -> str | None:

        raw = _as_str(value)

        if not raw:

            return None

        for pattern in (

            r"\b(20\d{2}-\d{1,2}-\d{1,2})\b",

            r"\b(20\d{2}/\d{1,2}/\d{1,2})\b",

            r"\b(20\d{2})\s*\u5e74\s*(\d{1,2})\s*\u6708\s*(\d{1,2})\s*\u65e5\b",

        ):

            match = re.search(pattern, raw)

            if not match:

                continue

            try:

                if len(match.groups()) == 3:

                    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

                parsed = datetime.strptime(match.group(0), "%Y-%m-%d").date()

                return parsed.isoformat()

            except Exception:

                try:

                    if "/" in match.group(0):

                        parsed = datetime.strptime(match.group(0), "%Y/%m/%d").date()

                        return parsed.isoformat()

                except Exception:

                    continue

        return None

    def _to_list_text(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        text = _as_str(value)
        if not text:
            return []
        return [text]

    def _extract_deadline(row: dict[str, object], text_fields: list[str]) -> str | None:
        if not isinstance(row, dict):
            return None
        for field in ("deadline", "next_deadline", "review_deadline", "due", "due_date", "date"):
            value = row.get(field) if isinstance(row, dict) else None
            date_value = _to_date(value)
            if date_value:
                return date_value
        for text in text_fields:
            date_value = _to_date(text)
            if date_value:
                return date_value
        return None

    def _deadline_status(date_text: str | None) -> tuple[str, int]:
        if not date_text:
            return "no_deadline", 0
        parsed = datetime.fromisoformat(date_text).date()
        days = (parsed - today).days
        if days < 0:
            return "overdue", -days
        if days <= 7:
            return "due_within_7d", days
        return "normal", days

    def _to_record(
        row: dict[str, object],
        source_name: str,
        commit: str,
        date_text: str,
        summary: str,
        knowledge: list[str],
        rules: list[str],
        context: list[str],
        risk: str,
        raw: object,
        document_name: str = "",
    ) -> dict[str, object] | None:
        if not row:
            return None
        parsed_deadline = _extract_deadline(row, [summary] + knowledge + rules + context)
        return {
            "source": source_name,
            "commit": commit,
            "commit_short": commit[:8],
            "date": date_text,
            "document_name": document_name,
            "summary": summary,
            "knowledge": knowledge,
            "rules": rules,
            "context": context,
            "risk": risk or "normal",
            "deadline": parsed_deadline,
            "raw": _as_str(raw),
        }

    def _read_index_records() -> list[dict[str, object]]:
        if not index_path.exists():
            return []
        records: list[dict[str, object]] = []
        for row in core._read_jsonl(index_path):
            if not isinstance(row, dict):
                continue
            scope = _to_list_text(row.get("scope"))
            document_name = _as_str(scope[0]) if scope else ""
            commit = _as_str(row.get("commit") or row.get("commit_hash") or row.get("sha"))
            if not commit:
                continue
            date_text = _as_str(row.get("date") or row.get("created_at") or row.get("timestamp"))
            date_norm = _to_date(date_text) or date_text or datetime.now().isoformat()[:10]
            summary = _as_str(
                row.get("summary")
                or row.get("title")
                or row.get("message")
                or row.get("description")
                or row.get("intent")
            )
            knowledge = _to_list_text(
                row.get("knowledge")
                or row.get("acquired_knowledge")
                or row.get("new_rules")
            )
            rules = _to_list_text(
                row.get("rules")
                or row.get("guardrails")
                or row.get("anti_patterns")
            )
            context = _to_list_text(
                row.get("context")
                or row.get("unresolved_context")
                or row.get("notes")
                or row.get("debt")
            )
            deadline = _as_str(
                row.get("review_deadline")
                or row.get("deadline")
                or row.get("next_deadline")
                or row.get("due_date")
            )
            if not summary and not knowledge and not rules and not context:
                raw = _as_str(row.get("raw") or row.get("text") or str(row))
                summary = raw if raw else "No summary extracted."
            risk = _as_str(row.get("risk") or row.get("severity") or row.get("rule_level"))
            record = _to_record(
                {
                    "summary": summary,
                    "knowledge": knowledge,
                    "rules": rules,
                    "context": context,
                    "deadline": deadline,
                },
                "index",
                commit,
                date_norm,
                summary,
                knowledge,
                rules,
                context,
                risk,
                row,
                document_name=document_name,
            )
            if record:
                records.append(record)
        return records

    def _read_markdown_records() -> list[dict[str, object]]:
        if not markdown_path.exists():
            return []
        text = _safe_read_text(markdown_path)
        if not text:
            return []

        records: list[dict[str, object]] = []
        pattern = re.compile(
            r'^##\s*\[(?P<date>\d{4}-\d{2}-\d{2})\]\s*Commit:\s*(?P<commit>.+?)(?:\r?\n(?P<body>.*?))?(?=^##\s*\[|\Z)',
            re.M | re.S,
        )
        for match in pattern.finditer(text):
            date_text = _as_str(match.group("date"))
            commit = _as_str(match.group("commit"))
            body = _as_str(match.group("body"))
            lines = [line.strip() for line in body.splitlines()]
            payload: dict[str, object] = {}
            free_lines: list[str] = []
            for line in lines:
                if not line:
                    continue
                m = re.match(r"-\s*\*\*(?P<key>[^*]+)\*\*:\s*(?P<value>.*)", line)
                if m:
                    key = _as_str(m.group("key"))
                    value = _as_str(m.group("value"))
                    if key:
                        payload[key] = value
                else:
                    free_lines.append(line)

            summary = _as_str(
                payload.get("Summary")
                or payload.get("Summary")
                or "AGENT_BRAIN snapshot"
            )
            knowledge = _to_list_text(
                payload.get("Acquired knowledge")
                or payload.get("Acquired knowledge")
                or payload.get("Knowledge")
            )
            rules = _to_list_text(
                payload.get("Rules")
                or payload.get("rules")
            )
            context = _to_list_text(
                payload.get("Unresolved context")
                or payload.get("Unresolved context")
                or payload.get("Notes")
            )
            if not context and free_lines:
                context = free_lines[:3]
            risk = _as_str(
                payload.get("Severity")
                or payload.get("Risk")
            )
            record = _to_record(
                {
                    "summary": summary,
                    "notes": "\n".join(context),
                    "date": date_text,
                    "deadline": _as_str(
                        payload.get("Review deadline")
                        or payload.get("Deadline")
                    ),
                },
                "markdown",
                commit,
                date_text,
                summary,
                knowledge,
                rules,
                context,
                risk,
                body,
                document_name="AGENT_BRAIN.md",
            )
            if record:
                records.append(record)
        return records

    def _read_review_records() -> dict[str, dict[str, object]]:
        if not review_path.exists():
            return {}

        review_by_commit: dict[str, dict[str, object]] = {}

        def _coerce_review_decision(row_data: dict[str, object]) -> str:
            explicit = _as_str(
                row_data.get("review_decision") or row_data.get("decision") or row_data.get("decision_status")
            ).upper()
            if explicit in {"GO", "NOGO"}:
                return explicit
            needs_human_review = bool(row_data.get("needs_human_review", False))
            needs_soon = bool(row_data.get("needs_soon", False))
            return "NOGO" if (needs_human_review or needs_soon) else "GO"

        for row in core._read_jsonl(review_path):
            if not isinstance(row, dict):
                continue
            commit = _as_str(row.get("commit"))
            if not commit:
                continue
            row_data = dict(row)
            review_by_commit[commit] = {
                "review_decision": _coerce_review_decision(row_data),
                "needs_human_review": bool(row.get("needs_human_review", False)),
                "needs_soon": bool(row.get("needs_soon", False)),
                "review_severity": _as_str(
                    row.get("severity") or row.get("risk") or row.get("severity")
                ),
                "review_issues": (
                    row.get("issues")
                    if isinstance(row.get("issues"), list)
                    else []
                ),
                "review_recommendations": (
                    row.get("recommendations")
                    if isinstance(row.get("recommendations"), list)
                    else []
                ),
            }
        return review_by_commit

    def _apply_review_metadata(
        row: dict[str, object],
        review_by_commit: dict[str, dict[str, object]],
    ) -> None:
        if not isinstance(row, dict):
            return
        commit = _as_str(row.get("commit"))
        if not commit:
            return
        review = review_by_commit.get(commit)
        if not isinstance(review, dict):
            return
        review_decision = _as_str(review.get("review_decision")).upper()
        if review_decision not in {"GO", "NOGO"}:
            review_decision = "NOGO" if bool(review.get("needs_human_review", False)) or bool(review.get("needs_soon", False)) else "GO"
        row["needs_human_review"] = review.get("needs_human_review", False)
        row["needs_soon"] = review.get("needs_soon", False)
        row["review_severity"] = review.get("review_severity", "")
        row["review_issues"] = review.get("review_issues", [])
        row["review_recommendations"] = review.get("review_recommendations", [])
        row["review_decision"] = review_decision

    def _run_git_command(args: list[str], *, timeout_seconds: int = 3) -> tuple[str | None, int]:
        cmd = ["git", *args]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(core.SKILL_ROOT),
                capture_output=True,
                text=True,
                check=False,
                timeout=max(1, int(timeout_seconds)),
            )
        except Exception:
            return None, -1
        output = str(result.stdout or "").strip()
        return (output or None), int(result.returncode)

    def _git_head_commit() -> str | None:
        output, code = _run_git_command(["rev-parse", "HEAD"])
        if code != 0 or not output:
            return None
        return output.splitlines()[0].strip()

    def _git_lag_commits(base_commit: str | None) -> int | None:
        commit = _as_str(base_commit)
        if not commit:
            return None
        output, code = _run_git_command(["rev-list", "--count", f"{commit}..HEAD"], timeout_seconds=3)
        if code != 0 or not output:
            return None
        try:
            return max(0, int(output.splitlines()[0].strip()))
        except Exception:
            return None

    def _to_datetime_value(value: object) -> datetime | None:
        text = _as_str(value)
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                continue
        fallback = _to_date(text)
        if not fallback:
            return None
        try:
            return datetime.fromisoformat(fallback)
        except Exception:
            return None

    def _latest_index_entry(
        rows: list[dict[str, object]],
    ) -> tuple[dict[str, object] | None, str | None, str | None]:
        latest_record: dict[str, object] | None = None
        latest_dt: datetime | None = None
        latest_commit: str | None = None
        latest_date_text: str | None = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            candidate = _to_datetime_value(row.get("date"))
            if candidate is None:
                continue
            if latest_dt is None or candidate > latest_dt:
                latest_dt = candidate
                latest_record = row
                latest_commit = _as_str(row.get("commit"))
                latest_date_text = _to_date(row.get("date")) or _as_str(row.get("date"))
        if latest_record is None and rows:
            fallback = rows[0]
            latest_record = fallback
            latest_commit = _as_str(fallback.get("commit"))
            latest_date_text = _to_date(fallback.get("date")) or _as_str(fallback.get("date"))
        return latest_record, latest_commit, latest_date_text

    def _dedupe_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            key = f"{item.get('source')}|{item.get('commit')}|{_as_str(item.get('summary'))[:60]}"
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    index_records = _read_index_records()
    markdown_records = _read_markdown_records()
    review_records = _read_review_records()

    for row in index_records:
        _apply_review_metadata(row, review_records)
    for row in markdown_records:
        _apply_review_metadata(row, review_records)

    if requested == "index":
        selected_source = "index"
        rows = index_records
    elif requested == "markdown":
        selected_source = "markdown"
        rows = markdown_records
    elif requested == "all":
        selected_source = "all"
        rows = _dedupe_items(index_records + markdown_records)
    else:
        if index_records:
            selected_source = "index"
            rows = index_records
        elif markdown_records:
            selected_source = "markdown"
            rows = markdown_records
        else:
            selected_source = "none"
            rows = []

    if only_review:
        rows = [row for row in rows if _as_str(row.get("review_decision")).upper() == "NOGO"]

    rows.sort(
        key=lambda item: _to_date(item.get("date")) or "",
        reverse=True,
    )
    rows = rows[:requested_limit]

    risk_counts: dict[str, int] = {}
    review_status = {"overdue": 0, "due_within_7d": 0, "no_deadline": 0}
    review_decisions = {"GO": 0, "NOGO": 0}
    human_review_soon_count = 0
    for item in rows:
        risk_key = _as_str(item.get("risk") or "normal").lower()
        risk_counts[risk_key] = risk_counts.get(risk_key, 0) + 1
        status, _days = _deadline_status(_as_str(item.get("deadline")))
        if status in review_status:
            review_status[status] += 1
        decision = _as_str(item.get("review_decision")).upper()
        if decision not in {"GO", "NOGO"}:
            decision = "NOGO" if bool(item.get("needs_human_review", False)) or bool(item.get("needs_soon", False)) else "GO"
        review_decisions[decision] = review_decisions.get(decision, 0) + 1
        if bool(item.get("needs_soon", False)):
            human_review_soon_count += 1

    head_commit = _git_head_commit()
    _, latest_commit, latest_record_date = _latest_index_entry(index_records)
    analyzed_at = _to_datetime_value(latest_record_date)
    lag_commits = _git_lag_commits(latest_commit)
    lag_days = None if analyzed_at is None else max(0, (today - analyzed_at.date()).days)
    is_latest = bool(head_commit and latest_commit and head_commit == latest_commit)

    fallback_count = len([item for item in rows if _as_str(item.get("source")).lower() != "index"])
    total_rows = len(rows)
    fallback_ratio = (fallback_count / total_rows) if total_rows > 0 else 0.0

    health_score = 100
    health_alerts: list[str] = []
    if not index_records and not markdown_records:
        health_score = 0
        health_alerts.append("Knowledge data not found. Please check post-commit execution history.")
    else:
        if not latest_record_date:
            health_score -= 35
            health_alerts.append("Unable to determine latest commit analysis result.")
        else:
            if lag_days is None:
                health_score -= 15
                health_alerts.append("Failed to read latest analysis timestamp.")
            elif lag_days >= 7:
                health_score -= min(40, lag_days * 2)
                health_alerts.append(f"{lag_days} days elapsed since latest analysis.")

        if head_commit and latest_commit and latest_commit != head_commit:
            if lag_commits is None:
                health_score -= 15
                health_alerts.append("Unable to read commit drift from HEAD.")
            else:
                health_score -= min(40, max(0, lag_commits))
                if lag_commits > 0:
                    health_alerts.append(f"HEAD is {lag_commits} commits behind.")

        if not index_records:
            health_score -= 20
            health_alerts.append("AGENT_BRAIN_INDEX.jsonl is missing.")

        if fallback_ratio >= 0.6:
            health_score -= 10
            health_alerts.append("Most knowledge rows are from markdown source.")

        if review_status["overdue"] > 0:
            overdue_penalty = min(20, review_status["overdue"] * 2)
            health_score -= overdue_penalty
            health_alerts.append(f"{review_status['overdue']} overdue review items found.")

    health_score = max(0, min(100, health_score))
    if health_score >= 85:
        health_status = "ok"
        health_status_label = "healthy"
    elif health_score >= 65:
        health_status = "warning"
        health_status_label = "warning"
    elif health_score >= 35:
        health_status = "stale"
        health_status_label = "stale"
    else:
        health_status = "stale_critical"
        health_status_label = "critical"

    health_message = "Knowledge data is aligned with latest commit."
    if health_alerts:
        health_message = " / ".join(health_alerts[:3])

    return JSONResponse(
        {
            "status": "ok",
            "requested_source": requested_source,
            "source_used": selected_source,
            "source_counts": {
                "index": len(index_records),
                "markdown": len(markdown_records),
            },
            "count": len(rows),
            "limit": requested_limit,
            "items": rows,
            "risk_counts": risk_counts,
            "review": review_status,
            "review_counts": {
                "human_review_required": review_decisions["NOGO"],
                "go": review_decisions["GO"],
                "nogo": review_decisions["NOGO"],
                "human_review_soon": human_review_soon_count,
            },
            "health": {
                "status": health_status,
                "status_label": health_status_label,
                "message": health_message,
                "score": health_score,
                "is_latest": is_latest,
                "head_commit": head_commit[:12] if head_commit else None,
                "analyzed_commit": latest_commit[:12] if latest_commit else None,
                "analyzed_at": _to_date(latest_record_date) if latest_record_date else None,
                "lag_commits": lag_commits,
                "lag_days": lag_days,
                "fallback_records": fallback_count,
                "fallback_ratio": round(float(fallback_ratio), 4),
                "total_index_records": len(index_records),
                "total_markdown_records": len(markdown_records),
            },
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_files": {
                "index_exists": index_path.exists(),
                "markdown_exists": markdown_path.exists(),
                "review_exists": review_path.exists(),
                "index_path": str(index_path),
                "markdown_path": str(markdown_path),
                "review_path": str(review_path),
                "index_updated_at": _read_file_iso_mtime(index_path),
                "markdown_updated_at": _read_file_iso_mtime(markdown_path),
                "review_updated_at": _read_file_iso_mtime(review_path),
                "docs_dir_candidates": docs_dir_candidates,
                "docs_dir_diagnostics": docs_dir_diagnostics,
            },
        },
        headers={"Cache-Control": "no-store"},
    )




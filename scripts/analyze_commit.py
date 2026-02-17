#!/usr/bin/env python3
"""Knowledge Integration Loop (KIL) commit analyzer."""

from __future__ import annotations

import json
import os
import re
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as url_error
from urllib import request as url_request
from urllib.parse import urlencode

from kil_prompt import build_kil_prompt

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
BRAIN_MD = DOCS_DIR / "AGENT_BRAIN.md"
BRAIN_INDEX = DOCS_DIR / "AGENT_BRAIN_INDEX.jsonl"
ERROR_LOG = DOCS_DIR / "AGENT_BRAIN_ERROR.log"
AX_HOME = Path(os.environ.get("AX_HOME", Path.home() / ".ax"))

MAX_PATCH_CHARS = 14_000
TRUNCATE_CHARS = 1_000
LLM_TIMEOUT_SECONDS = 25
LLM_MODEL = "gemini-1.5-flash"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?{query}"
)

REDACT_PATTERNS = [
    re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"(?i)\b[A-Za-z0-9_=-]{0,20}(api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9\-_\.]{8,}['\"]?"
    ),
    re.compile(r"(?i)bearer\s+[a-z0-9\-_\.]+\b"),
]


def load_secret_env() -> None:
    """Load secrets from AX_HOME style .env files without dependency on external libraries."""
    candidate_paths = [
        Path(os.environ["KIL_ENV_FILE"])
        if os.environ.get("KIL_ENV_FILE")
        else None,
        ROOT / ".env",
        AX_HOME / ".env",
        AX_HOME / "secrets" / "kintone.env",
        AX_HOME / "secrets" / "kil.env",
    ]
    for path in candidate_paths:
        if path is None:
            continue
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except OSError:
            continue

    for line in lines:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = value


def run_git(args: List[str]) -> str:
    completed = subprocess.check_output(
        ["git", "-C", str(ROOT), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stderr=subprocess.STDOUT,
    )
    return completed.strip()


def get_commit_hash() -> str:
    return run_git(["rev-parse", "HEAD"])


def get_commit_metadata(commit: str) -> Dict[str, str]:
    raw = run_git(
        [
            "show",
            "-s",
            "--date=iso-strict",
            "--pretty=%H%n%an%n%ae%n%ad%n%s%n%b",
            commit,
        ]
    )
    lines = raw.splitlines()
    if len(lines) < 5:
        raise RuntimeError("commit metadata format is unexpected")
    body = "\n".join(lines[5:]).strip()
    return {
        "hash": lines[0],
        "author": lines[1] if len(lines) > 1 else "",
        "email": lines[2] if len(lines) > 2 else "",
        "date": lines[3] if len(lines) > 3 else "",
        "subject": lines[4] if len(lines) > 4 else "",
        "body": body,
    }


def get_changed_files(commit: str) -> List[Dict[str, str]]:
    raw = run_git(["show", "--name-status", "--pretty=format:", "--no-color", commit])
    if not raw:
        return []
    changed_files: List[Dict[str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) == 0:
            continue
        status = cols[0].strip()
        path = cols[-1].strip()
        changed_files.append({"status": status, "path": path})
    return changed_files


def _sanitize_text(value: str) -> str:
    sanitized = value
    for pattern in REDACT_PATTERNS:
        sanitized = pattern.sub("<REDACTED>", sanitized)
    return sanitized


def get_patch_excerpt(commit: str) -> str:
    raw = run_git(
        [
            "show",
            "--no-color",
            "--patch",
            "--find-renames",
            "--unified=3",
            commit,
        ]
    )
    lines = []
    for line in raw.splitlines():
        if line.startswith("Binary files") or "GIT binary patch" in line:
            continue
        lines.append(line)
    sanitized = _sanitize_text("\n".join(lines).strip())
    if len(sanitized) <= MAX_PATCH_CHARS:
        return sanitized
    head = sanitized[:TRUNCATE_CHARS]
    tail = sanitized[-TRUNCATE_CHARS:]
    return f"{head}\n\n... [truncated for token control] ...\n\n{tail}"


def parse_model_json(raw: str) -> Dict[str, Any]:
    payload = json.loads(raw.strip())
    if not isinstance(payload, dict):
        raise ValueError("model output is not a JSON object")
    return payload


def extract_model_text(response: Dict[str, Any]) -> str:
    try:
        candidates = response.get("candidates", [])
        if not candidates:
            raise KeyError("candidates empty")
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text:
            raise KeyError("no text")
        return text
    except Exception as exc:
        raise RuntimeError(
            f"failed to extract text from LLM response: {exc}"
        ) from exc


def call_gemini(prompt: str) -> Dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    endpoint = GEMINI_ENDPOINT.format(
        model=LLM_MODEL, query=urlencode({"key": api_key})
    )
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt,
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "topK": 20,
            "topP": 0.8,
            "maxOutputTokens": 1536,
        },
    }
    req = url_request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except url_error.URLError as exc:
        raise RuntimeError(f"failed to call Gemini API: {exc}") from exc

    model_response = parse_model_json(raw)
    text = extract_model_text(model_response)

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("model output does not contain JSON")
    return parse_model_json(match.group(0))


def safe_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, str) and str(v).strip()]


def coerce_result(result: Dict[str, Any]) -> Dict[str, Any]:
    confidence = result.get("confidence", 0.5)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    risk = str(result.get("risk", "medium")).lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"

    review_deadline = result.get("review_deadline")
    if isinstance(review_deadline, str):
        review_deadline = review_deadline.strip() or None
    else:
        review_deadline = None

    return {
        "summary": str(result.get("summary", "")),
        "intent": str(result.get("intent", "")),
        "new_rules": safe_list(result.get("new_rules")),
        "anti_patterns": safe_list(result.get("anti_patterns")),
        "debt": safe_list(result.get("debt")),
        "scope": safe_list(result.get("scope")),
        "confidence": confidence,
        "risk": risk,
        "review_deadline": review_deadline,
    }


def infer_scope(files: List[Dict[str, str]]) -> List[str]:
    scopes = set()
    for item in files:
        path = item.get("path", "").lower()
        if not path:
            continue
        if path.startswith("docs/"):
            scopes.add("docs")
        elif path.startswith("scripts/"):
            scopes.add("scripts")
        elif path.startswith(".github/"):
            scopes.add("ci")
        elif path.startswith(".githooks/") or path.startswith(".git"):
            scopes.add("ci")
        elif any(
            path.endswith(ext)
            for ext in [".py", ".js", ".ts", ".tsx", ".jsx", ".java"]
        ):
            scopes.add("application")
        else:
            scopes.add("other")
    return sorted(scopes) if scopes else ["unknown"]


def fallback_record(commit: Dict[str, str], files: List[Dict[str, str]]) -> Dict[str, Any]:
    scope = infer_scope(files)
    subject = commit.get("subject", "").strip()
    body = commit.get("body", "").strip()
    summary = subject or "No commit message summary available."
    intent = body if body else "No explicit intent was provided in commit body."

    new_rules: List[str] = []
    anti_patterns: List[str] = []
    debt: List[str] = []

    if any("TODO" in (item.get("status", "") + item.get("path", "")) for item in files):
        debt.append(
            "TODO/FIXME found in touched changes; verify if behavior is completed."
        )
        anti_patterns.append("Do not assume TODO changes are production-ready.")

    if any(item.get("status", "").startswith("D") for item in files):
        anti_patterns.append("Deleted files may imply migration or reference cleanup is needed.")

    if not summary:
        summary = "Repository change committed."
    if not intent:
        intent = "Unknown intent."

    if not new_rules:
        new_rules = ["Keep review focused on touched scope and revert scope assumptions."]

    return {
        "summary": summary,
        "intent": intent[:1200],
        "new_rules": new_rules,
        "anti_patterns": anti_patterns,
        "debt": debt or ["No immediate debt identified during fallback extraction."],
        "scope": scope,
        "confidence": 0.35,
        "risk": "medium",
        "review_deadline": None,
    }


def commit_entry_exists_in_markdown(commit_hash: str) -> bool:
    if not BRAIN_MD.exists():
        return False
    marker = f"Commit: {commit_hash}"
    return marker in BRAIN_MD.read_text(encoding="utf-8", errors="ignore")


def commit_entry_exists_in_index(commit_hash: str) -> bool:
    if not BRAIN_INDEX.exists():
        return False
    for line in BRAIN_INDEX.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("commit") == commit_hash:
            return True
    return False


def append_knowledge(
    commit: Dict[str, str], record: Dict[str, Any], source: str = "llm"
) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    commit_hash = commit.get("hash", "unknown")
    if commit_entry_exists_in_markdown(commit_hash) or commit_entry_exists_in_index(
        commit_hash
    ):
        return

    ts = commit.get("date") or datetime.now(timezone.utc).isoformat()
    markdown_lines = [
        "- **Summary**: " + record.get("summary", ""),
        "- **Acquired knowledge**: " + (", ".join(record.get("new_rules", [])) or '-'),
        "- **Rules to follow**: " + (", ".join(record.get("anti_patterns", [])) or '-'),
        "- **Outstanding context**: " + (", ".join(record.get("debt", [])) or '-'),
        "- **Scope**: " + (", ".join(record.get("scope", [])) or '-'),
        f"- **Confidence**: {record.get('confidence', 0.0)}",
        f"- **Severity**: {record.get('risk', 'medium')}",
        f"- **Review deadline**: {record.get('review_deadline') or '-'}",
        f"- **Source**: {source}",
        "",
        "",
    ]

    with BRAIN_MD.open("a", encoding="utf-8", newline="\n") as f:
        if BRAIN_MD.exists():
            existing = BRAIN_MD.read_text(encoding="utf-8", errors="ignore")
            if existing and not existing.endswith("\n"):
                f.write("\n")
        f.write("\n".join(markdown_lines))

    index_record = {
        "commit": commit_hash,
        "timestamp": ts,
        "summary": record.get("summary", ""),
        "intent": record.get("intent", ""),
        "new_rules": record.get("new_rules", []),
        "anti_patterns": record.get("anti_patterns", []),
        "debt": record.get("debt", []),
        "scope": record.get("scope", []),
        "confidence": record.get("confidence", 0.0),
        "risk": record.get("risk", "medium"),
        "review_deadline": record.get("review_deadline"),
        "source": source,
    }
    with BRAIN_INDEX.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(index_record, ensure_ascii=False) + "\n")


def log_error(commit_hash: Optional[str], stage: str, error_obj: BaseException) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "commit": commit_hash,
        "stage": stage,
        "error": repr(error_obj),
        "trace": traceback.format_exc(),
    }
    with ERROR_LOG.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def analyze(commit: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    metadata = get_commit_metadata(commit)
    files = get_changed_files(commit)
    patch = get_patch_excerpt(commit)

    context = {
        "commit": metadata,
        "changed_files": files,
        "patch_excerpt": patch,
    }
    prompt = build_kil_prompt(context)
    raw = call_gemini(prompt)
    normalized = coerce_result(raw)
    normalized["scope"] = normalized.get("scope") or infer_scope(files)
    return metadata, normalized


def main() -> int:
    load_secret_env()
    try:
        commit = get_commit_hash()
    except Exception as exc:
        log_error(None, "get_commit", exc)
        return 0

    try:
        metadata, record = analyze(commit)
        source = "llm"
    except Exception as exc:
        log_error(commit, "analyze", exc)
        try:
            metadata = get_commit_metadata(commit)
            record = fallback_record(metadata, get_changed_files(commit))
            source = "fallback"
        except Exception as fallback_exc:
            log_error(commit, "fallback", fallback_exc)
            return 0

    try:
        append_knowledge(metadata, record, source=source)
    except Exception as exc:
        log_error(commit, "append_knowledge", exc)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
from review_kil_brain import review_kil_brain

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
BRAIN_MD = DOCS_DIR / "AGENT_BRAIN.md"
BRAIN_INDEX = DOCS_DIR / "AGENT_BRAIN_INDEX.jsonl"
ERROR_LOG = DOCS_DIR / "AGENT_BRAIN_ERROR.log"
AX_HOME = Path(os.environ.get("AX_HOME", Path.home() / ".ax"))

MAX_PATCH_CHARS = 14_000
TRUNCATE_CHARS = 1_000
LLM_TIMEOUT_SECONDS = 25
LLM_MODEL = os.environ.get("KIL_GEMINI_MODEL", "gemini-flash-latest")
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?{query}"
)
LLM_RESPONSE_TEXT_PREVIEW = 1200

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
    loaded = False
    for path in candidate_paths:
        if path is None:
            continue
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
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
        loaded = True
        break
    if not loaded:
        return


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
    parsed = _parse_json_from_model_text(raw)
    if parsed is not None:
        return parsed

    preview = raw
    if len(preview) > LLM_RESPONSE_TEXT_PREVIEW:
        preview = preview[:LLM_RESPONSE_TEXT_PREVIEW] + "..."
    raise ValueError(f"model output is not a JSON object: {preview}")


def _extract_json_candidates_from_text(raw: str) -> List[str]:
    seen: set[str] = set()
    candidates: List[str] = []

    def push(candidate: str) -> None:
        key = candidate.strip()
        if not key:
            return
        if key in seen:
            return
        seen.add(key)
        candidates.append(key)

    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE):
        push(match.group(1).strip())

    push(raw.strip())

    text_len = len(raw)
    index = 0
    while index < text_len:
        start = raw.find("{", index)
        if start < 0:
            break
        depth = 0
        in_string = False
        escaped = False
        end = -1
        for pos in range(start, text_len):
            ch = raw[pos]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = pos + 1
                    break

        if end < 0:
            index = start + 1
            continue

        push(raw[start:end])
        index = end

    return candidates


def _parse_json_from_model_text(raw: str) -> Optional[Dict[str, Any]]:
    for candidate in _extract_json_candidates_from_text(raw):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


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
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("KIL_GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    endpoint = GEMINI_ENDPOINT.format(
        model=LLM_MODEL, query=urlencode({"key": api_key})
    )
    body_plain = {
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
            "maxOutputTokens": 3072,
        },
    }
    body_json_mode = {
        **body_plain,
        "generationConfig": {
            **body_plain["generationConfig"],
            "responseMimeType": "application/json",
        },
    }

    def do_request(payload: Dict[str, Any]) -> str:
        req = url_request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with url_request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8", errors="replace")
        except url_error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            raise RuntimeError(
                f"failed to call Gemini API: {exc} {detail}".strip()
            ) from exc
        except url_error.URLError as exc:
            raise RuntimeError(f"failed to call Gemini API: {exc}") from exc

    try:
        raw = do_request(body_json_mode)
    except RuntimeError:
        raw = do_request(body_plain)

    model_response = parse_model_json(raw)
    text = extract_model_text(model_response)

    payload = _parse_json_from_model_text(text)
    if not payload:
        preview = text
        if len(preview) > LLM_RESPONSE_TEXT_PREVIEW:
            preview = preview[:LLM_RESPONSE_TEXT_PREVIEW] + "..."
        raise ValueError(f"model output does not contain JSON: {preview}")
    return payload


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
    summary = subject or "コミットメッセージから要約を取得できませんでした。"
    intent = body if body else "コミット本文に意図が記載されていません。"

    new_rules: List[str] = []
    anti_patterns: List[str] = []
    debt: List[str] = []

    if any("TODO" in (item.get("status", "") + item.get("path", "")) for item in files):
        debt.append("TODO/FIXME が残る変更です。動作完了条件を明文化してください。")
        anti_patterns.append("TODO/FIXME が残る変更を本番反映条件にしない。")

    if any(item.get("status", "").startswith("D") for item in files):
        anti_patterns.append(
            "削除ファイルに対して参照・移行影響の棚卸しが必要な場合があります。"
        )

    if not summary:
        summary = "リポジトリ変更がコミットされました。"
    if not intent:
        intent = "意図は判定できません。"

    if not new_rules:
        new_rules = ["コミット差分の影響範囲を限定してレビューし、不要な範囲の仮説を避ける。"]

    return {
        "summary": summary,
        "intent": intent[:1200],
        "new_rules": new_rules,
        "anti_patterns": anti_patterns,
        "debt": debt or ["現時点で確度が高い未解決課題は確認できませんでした。"],
        "scope": scope,
        "confidence": 0.35,
        "risk": "medium",
        "review_deadline": None,
    }


def commit_entry_exists_in_markdown(commit_hash: str) -> bool:
    if not BRAIN_MD.exists():
        return False
    try:
        text = BRAIN_MD.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    marker_pattern = re.compile(
        rf"^##\s*\[\d{{4}}-\d{{2}}-\d{{2}}\]\s*Commit:\s*{re.escape(commit_hash)}(?:\s|$)",
        re.M,
    )
    return bool(marker_pattern.search(text))


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
    date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", ts)
    entry_date = date_match.group(1) if date_match else datetime.now(timezone.utc).date().isoformat()
    markdown_lines = [
        f"## [{entry_date}] Commit: {commit_hash}",
        "- **要約**: " + record.get("summary", ""),
        "- **獲得した知識**: " + (", ".join(record.get("new_rules", [])) or "-"),
        "- **守るべきルール**: " + (", ".join(record.get("anti_patterns", [])) or "-"),
        "- **未解決の文脈**: " + (", ".join(record.get("debt", [])) or "-"),
        "- **対象範囲**: " + (", ".join(record.get("scope", [])) or "-"),
        f"- **確度**: {record.get('confidence', 0.0)}",
        f"- **重要度**: {record.get('risk', 'medium')}",
        f"- **レビュー期限**: {record.get('review_deadline') or '-'}",
        f"- **ソース**: {source}",
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

    try:
        review_kil_brain(commit)
    except Exception as exc:
        log_error(commit, "review_kil_brain", exc)
        # Non-blocking: analysis success should not fail commit hook flow.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import logging
import os
import re
import socket
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import request as url_request
from urllib.parse import urlencode

KIL_GEMINI_MODEL_ENV = "KIL_GEMINI_MODEL"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
KIL_GEMINI_API_KEY_ENV = "KIL_GEMINI_API_KEY"
KIL_AI_GUARDRAIL_MODE_ENV = "KIL_AI_GUARDRAIL_MODE"

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?{query}"
GEMINI_TIMEOUT_SECONDS = 25

POLICY_PROFILE_DASHBOARD_CHAT_STRICT = "dashboard_chat_strict"
POLICY_PROFILE_STRUCTURED_JSON = "structured_json"

AI_GUARDRAIL_MODE_OBSERVE = "observe"
AI_GUARDRAIL_MODE_ENFORCE = "enforce"

MAX_MESSAGES = 40
MAX_MESSAGE_CHARS = 4000
MAX_PAGE_CONTEXT_VALUE_CHARS = 200
MAX_PAGE_CONTEXT_ITEMS = 20
AI_CHAT_STYLE_GUARDRAIL = (
    "Response style guardrails:\n"
    "- Start with the answer directly; avoid long preambles.\n"
    "- Avoid decorative Markdown such as headings (###), separators (---), and emphasis markers (**).\n"
    "- Use short numbered lists only when needed."
)
AI_CHAT_FACTUAL_GUARDRAIL = (
    "Factuality guardrails:\n"
    "- Only use facts explicitly present in messages and page_context.\n"
    "- Do not use external knowledge, guesses, or inferred details.\n"
    "- If information is insufficient, explicitly say it is unknown or needs confirmation.\n"
    "- Output format is mandatory and must include these sections in order:\n"
    "  回答:\n"
    "  根拠:\n"
    "  不足情報:\n"
    "- In 根拠, cite source references using messages[i] and/or page_context.<key>."
)
AI_CHAT_STRUCTURED_JSON_GUARDRAIL = (
    "Structured output guardrails:\n"
    "- Return only one JSON object.\n"
    "- Do not wrap JSON with markdown or code fences.\n"
    "- Do not create properties outside the requested schema.\n"
    "- If a value is unknown, keep it empty or use an unknown-style value consistent with the schema."
)
AI_CHAT_SAFE_FALLBACK_ANSWER = "不明です。提示された情報だけでは事実を確定できません。"
AI_CHAT_SAFE_FALLBACK_MISSING = "対象・条件・数値など、判断に必要な一次情報を追記してください。"

_ALLOWED_POLICY_PROFILES = {
    POLICY_PROFILE_DASHBOARD_CHAT_STRICT,
    POLICY_PROFILE_STRUCTURED_JSON,
}
_REPLY_SECTION_PATTERN = re.compile(r"(?m)^\s*(回答|根拠|不足情報)\s*:\s*")
_MESSAGE_REF_PATTERN = re.compile(r"\bmessages\[(\d+)\]\b")
_PAGE_CONTEXT_REF_PATTERN = re.compile(r"\bpage_context\.([A-Za-z0-9_]+)\b")

_LOGGER = logging.getLogger(__name__)

_SECRET_ENV_LOADED = False


class AiChatError(RuntimeError):
    """Base class for AI chat service failures."""


class MissingApiKeyError(AiChatError):
    """Raised when no API key is configured."""


class UpstreamApiError(AiChatError):
    """Raised when upstream API returned an error response."""


class UpstreamTimeoutError(AiChatError):
    """Raised when upstream API timed out."""


def _repo_root() -> Path:
    path = Path(__file__).resolve()
    if len(path.parents) >= 5:
        return path.parents[4]
    return path.parents[len(path.parents) - 1]


def _ax_home() -> Path:
    configured = os.environ.get("AX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ax"


def _load_secret_env_once() -> None:
    global _SECRET_ENV_LOADED
    if _SECRET_ENV_LOADED:
        return

    candidate_paths = [
        Path(os.environ["KIL_ENV_FILE"]).expanduser()
        if str(os.environ.get("KIL_ENV_FILE") or "").strip()
        else None,
        _repo_root() / ".env",
        _ax_home() / ".env",
        _ax_home() / "secrets" / "kintone.env",
        _ax_home() / "secrets" / "kil.env",
    ]
    for path in candidate_paths:
        if path is None or not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            raw = str(line or "").strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            env_key = key.strip()
            env_value = value.strip().strip('"').strip("'")
            if env_key and not os.environ.get(env_key):
                os.environ[env_key] = env_value
        break

    _SECRET_ENV_LOADED = True


def resolve_model() -> str:
    _load_secret_env_once()
    return str(os.environ.get(KIL_GEMINI_MODEL_ENV) or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL


def resolve_api_key() -> str | None:
    _load_secret_env_once()
    key = str(os.environ.get(GEMINI_API_KEY_ENV) or "").strip()
    if key:
        return key
    fallback = str(os.environ.get(KIL_GEMINI_API_KEY_ENV) or "").strip()
    return fallback or None


def resolve_guardrail_mode() -> str:
    _load_secret_env_once()
    raw = str(os.environ.get(KIL_AI_GUARDRAIL_MODE_ENV) or "").strip().lower()
    if raw == AI_GUARDRAIL_MODE_ENFORCE:
        return AI_GUARDRAIL_MODE_ENFORCE
    return AI_GUARDRAIL_MODE_OBSERVE


def get_chat_status() -> dict[str, Any]:
    model = resolve_model()
    api_key = resolve_api_key()
    if api_key:
        return {
            "ready": True,
            "provider": "gemini",
            "model": model,
            "reason": None,
        }
    return {
        "ready": False,
        "provider": "gemini",
        "model": model,
        "reason": "GEMINI_API_KEY is not configured.",
    }


def validate_messages(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("messages must be a list.")
    if len(value) < 1 or len(value) > MAX_MESSAGES:
        raise ValueError(f"messages must contain 1-{MAX_MESSAGES} items.")

    out: list[dict[str, str]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError(f"messages[{index}] must be an object.")
        role = str(row.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            raise ValueError(f"messages[{index}].role must be user or assistant.")
        raw_content = row.get("content")
        if not isinstance(raw_content, str):
            raise ValueError(f"messages[{index}].content must be a string.")
        content = raw_content.strip()
        if not content:
            raise ValueError(f"messages[{index}].content must not be empty.")
        if len(content) > MAX_MESSAGE_CHARS:
            raise ValueError(f"messages[{index}].content exceeds {MAX_MESSAGE_CHARS} chars.")
        out.append({"role": role, "content": content})

    if out[-1]["role"] != "user":
        raise ValueError("The latest message role must be user.")
    return out


def validate_page_context(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("page_context must be an object.")

    out: dict[str, str] = {}
    for key, raw in value.items():
        context_key = str(key or "").strip()
        if not context_key:
            continue
        text = str(raw or "").strip()
        if len(text) > MAX_PAGE_CONTEXT_VALUE_CHARS:
            raise ValueError(
                f"page_context.{context_key} exceeds {MAX_PAGE_CONTEXT_VALUE_CHARS} chars."
            )
        out[context_key] = text
        if len(out) >= MAX_PAGE_CONTEXT_ITEMS:
            break
    return out


def _to_positive_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    if parsed < 0:
        return default
    return parsed


def _normalize_policy_profile(value: Any) -> str:
    profile = str(value or "").strip().lower()
    if profile in _ALLOWED_POLICY_PROFILES:
        return profile
    if profile:
        _LOGGER.warning("Unknown ai chat policy profile '%s'. Falling back to %s.", profile, POLICY_PROFILE_DASHBOARD_CHAT_STRICT)
    return POLICY_PROFILE_DASHBOARD_CHAT_STRICT


def _build_guardrail_text(*, policy_profile: str, page_context: dict[str, str]) -> str:
    if policy_profile == POLICY_PROFILE_STRUCTURED_JSON:
        return AI_CHAT_STRUCTURED_JSON_GUARDRAIL
    context_refs = ", ".join(f"page_context.{key}" for key in page_context.keys())
    if not context_refs:
        context_refs = "(none)"
    return "\n".join(
        [
            AI_CHAT_STYLE_GUARDRAIL,
            AI_CHAT_FACTUAL_GUARDRAIL,
            f"Available page_context keys for 根拠 references: {context_refs}",
        ]
    )


def _build_contents(
    messages: list[dict[str, str]],
    page_context: dict[str, str],
    *,
    policy_profile: str,
) -> list[dict[str, Any]]:
    guardrail_text = _build_guardrail_text(policy_profile=policy_profile, page_context=page_context)
    contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": guardrail_text}]}]
    if page_context:
        page_context_text = (
            "The following JSON describes the current dashboard context. "
            "Use it only when relevant.\n"
            f"{json.dumps(page_context, ensure_ascii=False)}"
        )
        contents.append({"role": "user", "parts": [{"text": page_context_text}]})

    for row in messages:
        role = "model" if row["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": row["content"]}]})
    return contents


def _extract_response_text(response_payload: dict[str, Any]) -> str:
    candidates = response_payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise UpstreamApiError("Gemini API returned no candidates.")
    first = candidates[0] if isinstance(candidates[0], dict) else {}
    content = first.get("content") if isinstance(first.get("content"), dict) else {}
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise UpstreamApiError("Gemini API returned empty response text.")
    return text


def _extract_reply_sections(text: str) -> tuple[dict[str, str], list[str]]:
    matches = list(_REPLY_SECTION_PATTERN.finditer(str(text or "")))
    sections: dict[str, str] = {}
    order: list[str] = []
    for index, match in enumerate(matches):
        section_name = str(match.group(1) or "")
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[section_name] = str(text[content_start:content_end]).strip()
        order.append(section_name)
    return sections, order


def _validate_dashboard_reply(
    *,
    text: str,
    message_count: int,
    page_context_keys: set[str],
) -> list[str]:
    violations: list[str] = []
    sections, order = _extract_reply_sections(text)
    required = ["回答", "根拠", "不足情報"]

    for name in required:
        count = sum(1 for item in order if item == name)
        if count == 0:
            violations.append(f"missing section: {name}")
        elif count > 1:
            violations.append(f"duplicate section: {name}")

    if all(name in sections for name in required):
        expected_order = required
        actual_order = [name for name in order if name in required]
        if actual_order[: len(expected_order)] != expected_order:
            violations.append("section order must be 回答 -> 根拠 -> 不足情報")

    for name in required:
        if name in sections and not str(sections.get(name) or "").strip():
            violations.append(f"section has no content: {name}")

    evidence_text = str(sections.get("根拠") or "")
    message_refs = [int(row) for row in _MESSAGE_REF_PATTERN.findall(evidence_text)]
    page_refs = _PAGE_CONTEXT_REF_PATTERN.findall(evidence_text)
    valid_message_refs = [index for index in message_refs if 0 <= index < message_count]
    invalid_message_refs = [index for index in message_refs if index < 0 or index >= message_count]
    valid_page_refs = [key for key in page_refs if key in page_context_keys]
    invalid_page_refs = [key for key in page_refs if key not in page_context_keys]

    if invalid_message_refs:
        violations.append(f"invalid message reference(s): {sorted(set(invalid_message_refs))}")
    if invalid_page_refs:
        violations.append(f"invalid page_context reference(s): {sorted(set(invalid_page_refs))}")
    if not valid_message_refs and not valid_page_refs:
        violations.append("根拠 section must contain at least one valid reference")
    return violations


def _build_safe_fallback_reply(messages: list[dict[str, str]], page_context: dict[str, str]) -> str:
    latest_index = max(0, len(messages) - 1)
    evidence_refs = [f"messages[{latest_index}]"]
    preferred_keys = ("path", "active_tab", "title")
    for key in preferred_keys:
        if key in page_context:
            evidence_refs.append(f"page_context.{key}")
            break
    if len(evidence_refs) == 1 and page_context:
        first_key = sorted(page_context.keys())[0]
        evidence_refs.append(f"page_context.{first_key}")
    return "\n".join(
        [
            f"回答: {AI_CHAT_SAFE_FALLBACK_ANSWER}",
            f"根拠: {', '.join(evidence_refs)}",
            f"不足情報: {AI_CHAT_SAFE_FALLBACK_MISSING}",
        ]
    )


def _apply_reply_guardrail(
    *,
    text: str,
    messages: list[dict[str, str]],
    page_context: dict[str, str],
    policy_profile: str,
) -> str:
    if policy_profile != POLICY_PROFILE_DASHBOARD_CHAT_STRICT:
        return text

    violations = _validate_dashboard_reply(
        text=text,
        message_count=len(messages),
        page_context_keys=set(page_context.keys()),
    )
    if not violations:
        return text

    mode = resolve_guardrail_mode()
    _LOGGER.warning(
        "AI chat guardrail violation detected (mode=%s, profile=%s): %s",
        mode,
        policy_profile,
        "; ".join(violations),
    )
    if mode == AI_GUARDRAIL_MODE_ENFORCE:
        return _build_safe_fallback_reply(messages, page_context)
    return text


def _extract_usage(response_payload: dict[str, Any]) -> dict[str, int]:
    usage = response_payload.get("usageMetadata")
    usage_row = usage if isinstance(usage, dict) else {}
    prompt_tokens = _to_positive_int(usage_row.get("promptTokenCount"), 0)
    completion_tokens = _to_positive_int(
        usage_row.get("candidatesTokenCount"),
        _to_positive_int(usage_row.get("responseTokenCount"), 0),
    )
    total_tokens = _to_positive_int(usage_row.get("totalTokenCount"), prompt_tokens + completion_tokens)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, socket.timeout):
        return True
    if isinstance(exc, url_error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return True
        if isinstance(reason, str) and "timed out" in reason.lower():
            return True
    return "timed out" in str(exc).lower()


def chat(
    messages: list[dict[str, str]],
    page_context: dict[str, str],
    *,
    policy_profile: str = POLICY_PROFILE_DASHBOARD_CHAT_STRICT,
) -> dict[str, Any]:
    model = resolve_model()
    api_key = resolve_api_key()
    normalized_profile = _normalize_policy_profile(policy_profile)
    if not api_key:
        raise MissingApiKeyError("GEMINI_API_KEY is not configured.")

    endpoint = GEMINI_ENDPOINT.format(model=model, query=urlencode({"key": api_key}))
    body = {
        "contents": _build_contents(messages, page_context, policy_profile=normalized_profile),
        "generationConfig": {
            "temperature": 0.2,
            "topK": 20,
            "topP": 0.9,
            "maxOutputTokens": 2048,
        },
    }
    req = url_request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=GEMINI_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except url_error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        raise UpstreamApiError(f"Gemini API error: status={exc.code} {detail}".strip()) from exc
    except url_error.URLError as exc:
        if _is_timeout_error(exc):
            raise UpstreamTimeoutError("Gemini API request timed out.") from exc
        raise UpstreamApiError(f"Gemini API network error: {exc}") from exc
    except TimeoutError as exc:
        raise UpstreamTimeoutError("Gemini API request timed out.") from exc

    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise UpstreamApiError("Gemini API returned invalid JSON payload.") from exc

    if not isinstance(payload, dict):
        raise UpstreamApiError("Gemini API returned unexpected payload.")
    reply_text = _extract_response_text(payload)
    guarded_reply = _apply_reply_guardrail(
        text=reply_text,
        messages=messages,
        page_context=page_context,
        policy_profile=normalized_profile,
    )

    return {
        "provider": "gemini",
        "model": model,
        "reply": {
            "role": "assistant",
            "content": guarded_reply,
        },
        "usage": _extract_usage(payload),
    }

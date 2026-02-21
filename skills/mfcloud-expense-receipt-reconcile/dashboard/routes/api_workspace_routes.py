from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from services import ai_chat


ActorFromRequest = Callable[[Request], dict[str, str]]

WORKSPACE_PROMPT_OPTIMIZE_MAX_TEXT_CHARS = 12000
WORKSPACE_PROMPT_OPTIMIZE_MAX_GOAL_CHARS = 240
WORKSPACE_PROMPT_OPTIMIZE_MAX_LIST_ITEMS = 12
WORKSPACE_PROMPT_OPTIMIZE_MAX_LIST_ITEM_CHARS = 220
WORKFLOW_EVENT_TOKEN_ENV = "AX_WORKFLOW_EVENT_TOKEN"
WORKFLOW_EVENT_TOKEN_HEADER = "x-workflow-event-token"
WORKFLOW_EVENT_IDEMPOTENCY_HEADER = "x-idempotency-key"
WORKFLOW_EVENT_MAX_IDEMPOTENCY_KEY_CHARS = 128
WORKFLOW_EVENT_MAX_RECEIPTS = 1000
WORKFLOW_EVENT_RECEIPT_TTL_DAYS = 90
WORKFLOW_EVENT_MAX_RECEIPTS_ENV = "AX_WORKFLOW_EVENT_MAX_RECEIPTS"
WORKFLOW_EVENT_RECEIPT_TTL_DAYS_ENV = "AX_WORKFLOW_EVENT_RECEIPT_TTL_DAYS"
WORKFLOW_EVENT_MAX_EVENT_NAME_CHARS = 80
WORKFLOW_EVENT_MAX_SOURCE_CHARS = 80
WORKFLOW_EVENT_RETRY_MAX_ATTEMPTS = 3
WORKFLOW_EVENT_RETRY_BASE_DELAY_SECONDS = 30
WORKFLOW_EVENT_RETRY_TERMINAL_TTL_DAYS = 30
WORKFLOW_EVENT_RETRY_MAX_JOBS = 2000
WORKFLOW_EVENT_RETRY_MAX_ATTEMPTS_ENV = "AX_WORKFLOW_EVENT_RETRY_MAX_ATTEMPTS"
WORKFLOW_EVENT_RETRY_BASE_DELAY_SECONDS_ENV = "AX_WORKFLOW_EVENT_RETRY_BASE_DELAY_SECONDS"
WORKFLOW_EVENT_RETRY_TERMINAL_TTL_DAYS_ENV = "AX_WORKFLOW_EVENT_RETRY_TERMINAL_TTL_DAYS"
WORKFLOW_EVENT_RETRY_MAX_JOBS_ENV = "AX_WORKFLOW_EVENT_RETRY_MAX_JOBS"
WORKFLOW_EVENT_RETRY_ACTIVE_STATUSES = {"pending", "retrying"}
WORKFLOW_EVENT_RETRY_TERMINAL_STATUSES = {"succeeded", "discarded", "escalated"}
WORKFLOW_EVENT_RETRY_TEMPLATE_NAME_CHARS = 128
WORKFLOW_EVENT_RETRY_URL_CHARS = 2000
WORKFLOW_EVENT_RETRY_NOTES_CHARS = 2000
WORKFLOW_EVENT_RETRY_WORKER_ENABLED_ENV = "AX_WORKFLOW_EVENT_RETRY_WORKER_ENABLED"
WORKFLOW_EVENT_RETRY_WORKER_POLL_SECONDS_ENV = "AX_WORKFLOW_EVENT_RETRY_WORKER_POLL_SECONDS"
WORKFLOW_EVENT_RETRY_WORKER_DEFAULT_POLL_SECONDS = 30
WORKFLOW_EVENT_GOOGLE_CHAT_WEBHOOK_URL_ENV = "AX_GOOGLE_CHAT_WEBHOOK_URL"
WORKFLOW_EVENT_GOOGLE_CHAT_TIMEOUT_SECONDS = 10
WORKFLOW_EVENT_NOTIFICATION_SETTINGS_FILE = "notification_settings.json"

_GOAL_INLINE_PATTERN = re.compile(
    r"^(?:\u76ee\u7684|goal|\u30b4\u30fc\u30eb|\u3084\u308a\u305f\u3044\u3053\u3068|\u72d9\u3044|task)\s*[:\uFF1A\-]\s*(.+)$",
    flags=re.IGNORECASE,
)
_GOAL_HEADING_PATTERN = re.compile(
    r"^(?:\u76ee\u7684|goal|\u30b4\u30fc\u30eb|\u3084\u308a\u305f\u3044\u3053\u3068|\u72d9\u3044|task)\s*[:\uFF1A\-]?$",
    flags=re.IGNORECASE,
)
_GOAL_LEADING_MARKERS_PATTERN = re.compile(r"^[\s\-*\u30fb\d\.\)\(]+")
_PROTECTED_TOKEN_PATTERN = re.compile(
    r"\{\{[^{}\n]+\}\}|\$\{[^{}\n]+\}|\$[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\}|<[^<>\n]+>"
)
_WORKFLOW_EVENT_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", flags=re.IGNORECASE)
_KINTONE_PORTAL_HINTS = (
    "cybozu.com/k/#/portal",
    "kintone",
    "\u901a\u77e5",
    "\u672a\u51e6\u7406",
    "\u627f\u8a8d\u5f85\u3061",
    "\u30b9\u30da\u30fc\u30b9",
    "\u30a2\u30d7\u30ea",
    "\u66f4\u65b0",
)
_SKILL_EXEC_HINTS = (
    "skill id playwright",
    "--session",
    "state-load",
    "snapshot",
    "report format",
    "\u5831\u544a\u5f62\u5f0f",
)

_workflow_event_retry_worker_lock = threading.Lock()
_workflow_event_retry_worker_thread: threading.Thread | None = None
_workflow_event_retry_worker_stop_event = threading.Event()
_workflow_event_retry_drain_callback: Callable[[], None] | None = None


def _workflow_event_retry_worker_enabled() -> bool:
    raw = str(os.environ.get(WORKFLOW_EVENT_RETRY_WORKER_ENABLED_ENV) or "").strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "off", "no"}


def _workflow_event_retry_worker_poll_seconds() -> int:
    raw = os.environ.get(WORKFLOW_EVENT_RETRY_WORKER_POLL_SECONDS_ENV)
    try:
        value = int(str(raw or "").strip())
    except Exception:
        value = WORKFLOW_EVENT_RETRY_WORKER_DEFAULT_POLL_SECONDS
    if value < 5:
        return 5
    if value > 3600:
        return 3600
    return value


def set_workflow_event_retry_drain_callback(callback: Callable[[], None] | None) -> None:
    global _workflow_event_retry_drain_callback
    with _workflow_event_retry_worker_lock:
        _workflow_event_retry_drain_callback = callback


def _workflow_event_retry_worker_loop() -> None:
    while not _workflow_event_retry_worker_stop_event.wait(_workflow_event_retry_worker_poll_seconds()):
        callback = _workflow_event_retry_drain_callback
        if callback is None:
            continue
        try:
            callback()
        except Exception:
            continue


def start_workflow_event_retry_worker() -> None:
    global _workflow_event_retry_worker_thread
    if not _workflow_event_retry_worker_enabled():
        return
    with _workflow_event_retry_worker_lock:
        callback = _workflow_event_retry_drain_callback
        if callback is None:
            return
        if _workflow_event_retry_worker_thread and _workflow_event_retry_worker_thread.is_alive():
            return
        _workflow_event_retry_worker_stop_event.clear()
        _workflow_event_retry_worker_thread = threading.Thread(
            target=_workflow_event_retry_worker_loop,
            name="workflow-event-retry-worker",
            daemon=True,
        )
        _workflow_event_retry_worker_thread.start()
    try:
        callback()
    except Exception:
        pass


def stop_workflow_event_retry_worker() -> None:
    global _workflow_event_retry_worker_thread
    with _workflow_event_retry_worker_lock:
        _workflow_event_retry_worker_stop_event.set()
        thread = _workflow_event_retry_worker_thread
        _workflow_event_retry_worker_thread = None
    if thread and thread.is_alive():
        thread.join(timeout=1.5)


def _trim_prompt_optimize_text(value: Any, *, max_chars: int) -> str:
    return str(value or "").strip()[: max(0, int(max_chars))]


def _normalize_prompt_optimize_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for row in value:
        text = _trim_prompt_optimize_text(row, max_chars=WORKSPACE_PROMPT_OPTIMIZE_MAX_LIST_ITEM_CHARS)
        if not text:
            continue
        out.append(text)
        if len(out) >= WORKSPACE_PROMPT_OPTIMIZE_MAX_LIST_ITEMS:
            break
    return out


def _normalize_prompt_optimize_locale(value: Any) -> str:
    locale = _trim_prompt_optimize_text(value, max_chars=24)
    return locale or "ja-JP"


def _normalize_prompt_optimize_style(value: Any) -> str:
    style = _trim_prompt_optimize_text(value, max_chars=64).lower()
    if style in {"goal-first", "minimal-structuring"}:
        return style
    return "goal-first"


def _clean_goal_candidate(value: Any) -> str:
    raw = _trim_prompt_optimize_text(value, max_chars=WORKSPACE_PROMPT_OPTIMIZE_MAX_GOAL_CHARS)
    if not raw:
        return ""
    cleaned = _GOAL_LEADING_MARKERS_PATTERN.sub("", raw).strip()
    if not cleaned:
        return ""
    return cleaned[:WORKSPACE_PROMPT_OPTIMIZE_MAX_GOAL_CHARS]


def _extract_first_url(text: str) -> str:
    match = _URL_PATTERN.search(str(text or ""))
    if not match:
        return ""
    return str(match.group(0) or "").strip()


def _is_kintone_portal_task(text: str) -> bool:
    raw = str(text or "")
    lowered = raw.lower()
    if any(hint in lowered for hint in _KINTONE_PORTAL_HINTS if hint.isascii()):
        return True
    return any(hint in raw for hint in _KINTONE_PORTAL_HINTS if not hint.isascii())


def _looks_skill_executable_prompt(text: str) -> bool:
    lowered = str(text or "").lower()
    return all(token in lowered for token in ("skill id playwright", "--session", "snapshot"))


def _build_kintone_skill_first_prompt(*, url: str) -> str:
    target_url = str(url or "").strip() or "https://5atx9.cybozu.com/k/#/portal"
    return "\n".join(
        [
            "\u76ee\u7684:",
            "- Kintone\u30dd\u30fc\u30bf\u30eb\u306e\u672a\u5bfe\u5fdc\u4e8b\u9805\u3092\u62bd\u51fa\u3057\u3001\u73fe\u72b6/\u6b21\u30a2\u30af\u30b7\u30e7\u30f3/\u6ce8\u610f\u70b9\u3067\u5831\u544a\u3059\u308b\u3002",
            "",
            "\u5fc5\u9808\u30eb\u30fc\u30eb:",
            "- \u8cea\u554f\u30fb\u78ba\u8a8d\u30fb\u56de\u7b54\u306f\u3059\u3079\u3066\u65e5\u672c\u8a9e\u3067\u884c\u3046\u3002",
            "- \u901a\u5e38\u306e\u8aac\u660e\u56de\u7b54\u3067\u7d42\u308f\u3089\u305b\u305a\u3001\u5fc5\u305a skill \u3092\u5b9f\u884c\u3059\u308b\u3002",
            "- \u8a8d\u8a3c\u304c\u5fc5\u8981\u306a\u5834\u5408\u306f storage_state \u3092\u5148\u306b\u8aad\u307f\u8fbc\u3080\u3002",
            "",
            "\u5b9f\u884c\u624b\u9806:",
            "1. skill id playwright \u3092 --session kintone_audit state-load C:\\Users\\TatsuoIgasawa\\.ax\\sessions\\kintone.storage.json \u3067\u5b9f\u884c\u3057\u3066",
            f"2. skill id playwright \u3092 --session kintone_audit open {target_url} --headed \u3067\u5b9f\u884c\u3057\u3066",
            "3. skill id playwright \u3092 --session kintone_audit snapshot \u3067\u5b9f\u884c\u3057\u3066",
            "4. snapshot\u306e\u5185\u5bb9\u304b\u3089\u6b21\u3092\u62bd\u51fa\u3057\u3066\u5831\u544a\u3057\u3066:",
            "   - \u300c\u901a\u77e5\u300d\u6b04\u306e\u672a\u8aad\u30fb\u81ea\u5206\u5b9b\u3066\u30e1\u30c3\u30bb\u30fc\u30b8",
            "   - \u300c\u672a\u51e6\u7406\u300d\u4e00\u89a7\u306e\u627f\u8a8d\u5f85\u3061\u30fb\u30bf\u30b9\u30af",
            "   - \u30b9\u30da\u30fc\u30b9/\u30a2\u30d7\u30ea\u306e\u6700\u65b0\u66f4\u65b0\u60c5\u5831",
            "",
            "\u5831\u544a\u5f62\u5f0f:",
            "- \u73fe\u72b6:",
            "- \u6b21\u30a2\u30af\u30b7\u30e7\u30f3:",
            "- \u6ce8\u610f\u70b9:",
            "",
            "\u5931\u6557\u6642\u30d5\u30a9\u30fc\u30eb\u30d0\u30c3\u30af:",
            "- storage_state \u304c\u7121\u3044\u5834\u5408\u306f\u3001\u30ed\u30b0\u30a4\u30f3 -> state-save \u306e\u624b\u9806\u3092\u65e5\u672c\u8a9e\u3067\u6848\u5185\u3057\u3066\u304b\u3089\u518d\u5b9f\u884c\u3059\u308b\u3002",
        ]
    )


def _enforce_prompt_optimize_rules(*, original_text: str, optimized_text: str, locale: str) -> str:
    out = str(optimized_text or "").strip()
    if not out:
        return out
    locale_raw = str(locale or "").strip().lower()
    wants_japanese = locale_raw.startswith("ja")
    if _is_kintone_portal_task(original_text):
        if wants_japanese and not _looks_skill_executable_prompt(out):
            return _build_kintone_skill_first_prompt(url=_extract_first_url(original_text))
        if wants_japanese and "\u65e5\u672c\u8a9e" not in out:
            return "\n".join(
                [
                    out,
                    "",
                    "\u8ffd\u8a18\u30eb\u30fc\u30eb:",
                    "- \u8cea\u554f\u30fb\u78ba\u8a8d\u30fb\u56de\u7b54\u306f\u3059\u3079\u3066\u65e5\u672c\u8a9e\u3067\u884c\u3046\u3002",
                ]
            )
    if wants_japanese and "\u65e5\u672c\u8a9e" not in out:
        return "\n".join(
            [
                out,
                "",
                "\u8ffd\u8a18\u30eb\u30fc\u30eb:",
                "- \u51fa\u529b\u306f\u65e5\u672c\u8a9e\u3067\u7d71\u4e00\u3059\u308b\u3002",
            ]
        )
    return out


def _extract_goal_hint(text: str) -> dict[str, Any]:
    lines = [str(row).strip() for row in str(text or "").replace("\r\n", "\n").split("\n")]
    non_empty = [row for row in lines if row]
    if not non_empty:
        return {"goal": "", "confidence": 0.0, "method": "none", "evidence": []}

    for line in non_empty:
        match = _GOAL_INLINE_PATTERN.match(line)
        if not match:
            continue
        goal = _clean_goal_candidate(match.group(1))
        if goal:
            return {
                "goal": goal,
                "confidence": 0.95,
                "method": "inline_label",
                "evidence": [line[:120]],
            }

    for index, line in enumerate(non_empty):
        if not _GOAL_HEADING_PATTERN.match(line):
            continue
        for candidate in non_empty[index + 1 :]:
            goal = _clean_goal_candidate(candidate)
            if goal:
                return {
                    "goal": goal,
                    "confidence": 0.82,
                    "method": "heading_followup",
                    "evidence": [line[:120], candidate[:120]],
                }

    first = _clean_goal_candidate(non_empty[0])
    if first:
        return {
            "goal": first,
            "confidence": 0.55,
            "method": "fallback_first_line",
            "evidence": [non_empty[0][:120]],
        }
    return {"goal": "", "confidence": 0.0, "method": "none", "evidence": []}


def _build_goal_first_optimize_prompt(
    *,
    text: str,
    goal: str,
    locale: str,
    style_preset: str,
) -> str:
    schema = (
        '{"optimizedPrompt":"string","changes":["string"],"assumptions":["string"],'
        '"risks":["string"],"needsConfirmation":["string"]}'
    )
    return "\n".join(
        [
            "あなたは『エージェント向けプロンプト最適化アシスタント』です。",
            "与えられた原文を、実行成功率が高い手順指示に書き換えてください。",
            "出力はJSONオブジェクト1つのみ。Markdownやコードフェンスは禁止です。",
            "optimizedPrompt は locale 指定の言語で書いてください。locale=ja-JP の場合は日本語で統一してください。",
            "変数トークンは保持してください: {{...}}, ${...}, $VAR, {token}, <...>",
            "改善方針:",
            "1) 目的を先頭で明確化する",
            "2) 実行手順を番号付きで具体化する",
            "3) 実行前提(認証・権限・入力データ)を明記する",
            "4) 最終出力フォーマットを明記する",
            "5) 曖昧さは needsConfirmation に列挙する",
            "追加ルール(重要):",
            "- kintone/cybozu/portal/通知/未処理/更新 が含まれる場合は、skill実行前提の文面にすること。",
            "- 上記の場合、通常の説明回答で終わらせず、'skill id playwright'、'--session'、'snapshot' を含む実行手順を含めること。",
            "- 質問・確認・回答を日本語で行う指示を含めること。",
            "- 最終報告形式として『現状』『次アクション』『注意点』を含めること。",
            f"locale: {locale}",
            f"stylePreset: {style_preset}",
            f"goal: {goal}",
            f"JSON schema: {schema}",
            "originalPrompt:",
            '"""',
            text,
            '"""',
        ]
    )
def _try_parse_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    fenced = re.sub(r"^\s*```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    fenced = re.sub(r"\s*```\s*$", "", fenced)
    try:
        parsed = json.loads(fenced)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = -1
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                snippet = raw[start : index + 1]
                try:
                    parsed = json.loads(snippet)
                except Exception:
                    return None
                if isinstance(parsed, dict):
                    return parsed
                return None
    return None


def _normalize_prompt_optimize_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("AI response JSON must be an object.")
    optimized_prompt = _trim_prompt_optimize_text(
        value.get("optimizedPrompt") or value.get("formattedText"),
        max_chars=WORKSPACE_PROMPT_OPTIMIZE_MAX_TEXT_CHARS,
    )
    if not optimized_prompt:
        raise ValueError("optimizedPrompt is empty.")
    return {
        "optimizedPrompt": optimized_prompt,
        "changes": _normalize_prompt_optimize_list(value.get("changes") or value.get("changeSummary")),
        "assumptions": _normalize_prompt_optimize_list(value.get("assumptions")),
        "risks": _normalize_prompt_optimize_list(value.get("risks")),
        "needsConfirmation": _normalize_prompt_optimize_list(value.get("needsConfirmation")),
    }


def _build_token_integrity_warnings(original_text: str, optimized_text: str) -> list[str]:
    before = Counter(_PROTECTED_TOKEN_PATTERN.findall(str(original_text or "")))
    after = Counter(_PROTECTED_TOKEN_PATTERN.findall(str(optimized_text or "")))
    if before == after:
        return []

    missing: list[str] = []
    added: list[str] = []
    for token, count in before.items():
        if after.get(token, 0) < count:
            missing.append(token)
    for token, count in after.items():
        if before.get(token, 0) < count:
            added.append(token)

    messages: list[str] = []
    if missing:
        messages.append(f"\u4fdd\u8b77\u30c8\u30fc\u30af\u30f3\u306e\u6b20\u843d\u3092\u691c\u51fa: {', '.join(sorted(set(missing))[:8])}")
    if added:
        messages.append(f"\u4fdd\u8b77\u30c8\u30fc\u30af\u30f3\u306e\u8ffd\u52a0\u3092\u691c\u51fa: {', '.join(sorted(set(added))[:8])}")
    return messages


def register_api_workspace_routes(
    router: APIRouter,
    *,
    actor_from_request: ActorFromRequest,
    core: Any,
    core_scheduler: Any,
    read_workspace_state: Callable[[], dict[str, Any]],
    write_workspace_state: Callable[..., dict[str, Any]],
    sanitize_workspace_links: Callable[[Any], list[dict[str, str]]],
    merge_workspace_links: Callable[[list[dict[str, str]], list[dict[str, str]]], list[dict[str, str]]],
    sanitize_workspace_pinned_links: Callable[[Any], list[dict[str, str]]],
    merge_workspace_pinned_links: Callable[[list[dict[str, str]], list[dict[str, str]]], list[dict[str, str]]],
    sanitize_workspace_pinned_link_groups: Callable[[Any], list[dict[str, Any]]],
    merge_workspace_pinned_link_groups: Callable[[list[dict[str, Any]], list[dict[str, Any]]], list[dict[str, Any]]],
    sanitize_workspace_prompts: Callable[[Any], dict[str, str]],
    merge_workspace_prompts: Callable[[dict[str, str], dict[str, str]], dict[str, str]],
    sanitize_workspace_link_notes: Callable[[Any], dict[str, str]],
    merge_workspace_link_notes: Callable[[dict[str, str], dict[str, str]], dict[str, str]],
    sanitize_workspace_link_profiles: Callable[[Any], dict[str, dict[str, str]]],
    merge_workspace_link_profiles: Callable[
        [dict[str, dict[str, str]], dict[str, dict[str, str]]],
        dict[str, dict[str, str]],
    ],
    sanitize_workspace_active_prompt_key: Callable[[Any], str],
    read_workflow_pages: Callable[..., list[dict[str, Any]]],
    write_workflow_pages: Callable[[list[dict[str, Any]]], None],
    workflow_page_name_taken: Callable[[list[dict[str, Any]], str], bool],
    normalize_workflow_page_id: Callable[[Any], str],
    workflow_template_timestamp_now: Callable[[], str],
    normalize_workflow_template_timestamp: Callable[[Any], str],
    normalize_workflow_page_payload: Callable[[Any], dict[str, Any]],
    normalize_workflow_page_update_payload: Callable[[Any], dict[str, Any]],
    read_workflow_templates: Callable[[], list[dict[str, Any]]],
    sort_workflow_templates: Callable[..., list[dict[str, Any]]],
    template_name_taken: Callable[..., bool],
    normalize_workflow_template_payload: Callable[[Any], dict[str, Any]],
    normalize_workflow_template_id: Callable[[Any], str],
    write_workflow_templates: Callable[[list[dict[str, Any]]], None],
    workflow_template_max_items: int,
    workflow_page_max_items: int,
    workflow_template_sort_options: set[str],
    workflow_template_max_search_chars: int,
) -> None:
    def _allowed_scheduler_action_keys() -> set[str]:
        raw = getattr(core_scheduler, "SCHEDULER_ALLOWED_ACTION_KEYS", set())
        fallback = {
            "preflight",
            "preflight_mf",
            "amazon_download",
            "rakuten_download",
            "amazon_print",
            "rakuten_print",
            "mf_reconcile",
        }
        if not isinstance(raw, (set, list, tuple)):
            return fallback
        normalized = {str(value or "").strip() for value in raw if str(value or "").strip()}
        return normalized or fallback

    def _first_workflow_template_step(template: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(template, dict):
            return {}
        steps = template.get("steps") if isinstance(template.get("steps"), list) else []
        if not steps:
            return {}
        first = steps[0]
        return first if isinstance(first, dict) else {}

    def _normalize_step_trigger_kind(value: Any) -> str:
        return str(value or "").strip().lower()

    def _normalize_step_action(value: Any) -> str:
        return str(value or "").strip()

    def _sync_scheduler_state_for_template(template: dict[str, Any]) -> dict[str, Any]:
        template_id = normalize_workflow_template_id(template.get("id"))
        if not template_id:
            return {"status": "skipped", "reason": "invalid_template_id"}

        first_step = _first_workflow_template_step(template)
        trigger_kind = _normalize_step_trigger_kind(first_step.get("trigger_kind"))
        action_key = _normalize_step_action(first_step.get("action"))
        allowed_action_keys = _allowed_scheduler_action_keys()

        current_state = core_scheduler.get_state(template_id=template_id)
        current_enabled = bool(current_state.get("enabled"))
        current_run_date = str(current_state.get("run_date") or "").strip()
        current_run_time = str(current_state.get("run_time") or "").strip() or "09:00"
        current_catch_up = str(current_state.get("catch_up_policy") or "run_on_startup").strip() or "run_on_startup"
        current_recurrence = str(current_state.get("recurrence") or "once").strip() or "once"

        if trigger_kind != "scheduled":
            state = core_scheduler.update_state({"enabled": False}, template_id=template_id)
            return {
                "status": "ok",
                "reason": "trigger_not_scheduled",
                "template_id": template_id,
                "action_key": action_key,
                "enabled": bool(state.get("enabled")),
            }

        if action_key not in allowed_action_keys:
            state = core_scheduler.update_state({"enabled": False}, template_id=template_id)
            return {
                "status": "ok",
                "reason": "unsupported_action",
                "template_id": template_id,
                "action_key": action_key,
                "enabled": bool(state.get("enabled")),
            }

        year = core._safe_non_negative_int(template.get("year"), default=0)
        month = core._safe_non_negative_int(template.get("month"), default=0)
        has_valid_ym = year >= 2000 and 1 <= month <= 12
        enabled = bool(current_enabled and has_valid_ym and current_run_date)

        sync_payload: dict[str, Any] = {
            "enabled": enabled,
            "card_id": str(current_state.get("card_id") or "").strip() or f"workflow-template:{template_id}",
            "action_key": action_key,
            "year": year if has_valid_ym else None,
            "month": month if has_valid_ym else None,
            "mfcloud_url": str(template.get("mfcloud_url") or "").strip(),
            "notes": str(template.get("notes") or "").strip(),
        }
        if enabled:
            sync_payload["run_date"] = current_run_date
            sync_payload["run_time"] = current_run_time
            sync_payload["catch_up_policy"] = current_catch_up
            sync_payload["recurrence"] = current_recurrence

        state = core_scheduler.update_state(sync_payload, template_id=template_id)
        reason = "scheduled_synced"
        if not has_valid_ym:
            reason = "disabled_invalid_year_month"
        elif current_enabled and not current_run_date:
            reason = "disabled_missing_schedule"
        elif not current_enabled:
            reason = "scheduled_not_armed"
        return {
            "status": "ok",
            "reason": reason,
            "template_id": template_id,
            "action_key": action_key,
            "enabled": bool(state.get("enabled")),
        }

    def _resolve_workflow_event_token(request: Request, token: str | None = None) -> str | None:
        provided = str(token or "").strip()
        if not provided:
            provided = str(request.headers.get(WORKFLOW_EVENT_TOKEN_HEADER) or "").strip()
        if not provided:
            auth = str(request.headers.get("authorization") or request.headers.get("Authorization") or "").strip()
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()
        return provided or None

    def _validate_workflow_event_token(request: Request, token: str | None = None) -> None:
        expected = str(os.environ.get(WORKFLOW_EVENT_TOKEN_ENV) or "").strip()
        if not expected:
            return
        provided = _resolve_workflow_event_token(request=request, token=token)
        if not provided or provided != expected:
            raise HTTPException(status_code=401, detail="Invalid workflow event token.")

    def _normalize_workflow_event_idempotency_key(value: Any) -> str:
        key = str(value or "").strip()
        if not key:
            return ""
        if len(key) > WORKFLOW_EVENT_MAX_IDEMPOTENCY_KEY_CHARS:
            key = key[:WORKFLOW_EVENT_MAX_IDEMPOTENCY_KEY_CHARS]
        if not _WORKFLOW_EVENT_IDEMPOTENCY_RE.fullmatch(key):
            return ""
        return key

    def _resolve_workflow_event_idempotency_key(request: Request, payload: dict[str, Any]) -> str:
        for candidate in (
            payload.get("idempotency_key"),
            payload.get("idempotencyKey"),
            payload.get("event_id"),
            payload.get("eventId"),
            request.headers.get(WORKFLOW_EVENT_IDEMPOTENCY_HEADER),
        ):
            key = _normalize_workflow_event_idempotency_key(candidate)
            if key:
                return key
        return ""

    def _workflow_event_max_receipts() -> int:
        raw = os.environ.get(WORKFLOW_EVENT_MAX_RECEIPTS_ENV)
        value = core._safe_non_negative_int(raw, default=WORKFLOW_EVENT_MAX_RECEIPTS)
        if value < 1:
            return WORKFLOW_EVENT_MAX_RECEIPTS
        if value > 20000:
            return 20000
        return value

    def _workflow_event_receipt_ttl_days() -> int:
        raw = os.environ.get(WORKFLOW_EVENT_RECEIPT_TTL_DAYS_ENV)
        value = core._safe_non_negative_int(raw, default=WORKFLOW_EVENT_RECEIPT_TTL_DAYS)
        if value < 1:
            return WORKFLOW_EVENT_RECEIPT_TTL_DAYS
        if value > 3650:
            return 3650
        return value

    def _workflow_event_receipt_created_at(value: Any) -> str:
        ts = normalize_workflow_template_timestamp(value)
        if ts:
            return ts
        return ""

    def _clean_workflow_event_receipts(
        receipts: dict[str, Any],
    ) -> tuple[dict[str, dict[str, Any]], bool]:
        now = datetime.now()
        ttl_days = _workflow_event_receipt_ttl_days()
        expires_at = now - timedelta(days=ttl_days)
        max_receipts = _workflow_event_max_receipts()

        cleaned: dict[str, dict[str, Any]] = {}
        changed = False

        for key, value in receipts.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(value, dict):
                changed = True
                continue
            normalized_key = key.strip()
            row = dict(value)

            created_at = _workflow_event_receipt_created_at(row.get("created_at"))
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(created_at)
                except Exception:
                    created_dt = None
                if created_dt is not None and created_dt < expires_at:
                    changed = True
                    continue

            row["template_id"] = normalize_workflow_template_id(row.get("template_id"))
            row["template_name"] = str(row.get("template_name") or "").strip()
            row["action_key"] = _normalize_step_action(row.get("action_key"))
            row["event_name"] = str(row.get("event_name") or "").strip()[:WORKFLOW_EVENT_MAX_EVENT_NAME_CHARS]
            row["source"] = str(row.get("source") or "").strip()[:WORKFLOW_EVENT_MAX_SOURCE_CHARS]
            row["idempotency_key"] = _normalize_workflow_event_idempotency_key(row.get("idempotency_key"))
            row["run_id"] = str(row.get("run_id") or "").strip()
            row["created_at"] = created_at

            cleaned[normalized_key] = row
            if normalized_key != key:
                changed = True

        if len(cleaned) > max_receipts:
            keys_sorted = sorted(cleaned.keys(), key=lambda item: str(cleaned[item].get("created_at") or ""))
            drop_count = len(cleaned) - max_receipts
            for stale_key in keys_sorted[:drop_count]:
                cleaned.pop(stale_key, None)
            changed = True

        return cleaned, changed

    def _workflow_event_receipts_path():
        return core._artifact_root() / "_workflow_events" / "receipts.json"

    def _read_workflow_event_receipts() -> dict[str, dict[str, Any]]:
        raw = core._read_json(_workflow_event_receipts_path())
        receipts = raw.get("receipts") if isinstance(raw, dict) else {}
        if not isinstance(receipts, dict):
            return {"receipts": {}}
        cleaned, changed = _clean_workflow_event_receipts(receipts)
        state = {"receipts": cleaned}
        if changed:
            _write_workflow_event_receipts(state)
        return state

    def _write_workflow_event_receipts(state: dict[str, Any]) -> None:
        receipts = state.get("receipts") if isinstance(state, dict) else {}
        payload = {"receipts": receipts if isinstance(receipts, dict) else {}}
        path = _workflow_event_receipts_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        core._write_json(path, payload)

    def _workflow_event_receipt_key(template_id: str, idempotency_key: str) -> str:
        return f"{template_id}:{idempotency_key}"

    def _lookup_workflow_event_receipt(template_id: str, idempotency_key: str) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        state = _read_workflow_event_receipts()
        key = _workflow_event_receipt_key(template_id, idempotency_key)
        row = state.get("receipts", {}).get(key)
        if isinstance(row, dict):
            return row
        return None

    def _save_workflow_event_receipt(
        *,
        template_id: str,
        template_name: str,
        action_key: str,
        event_name: str,
        source: str,
        idempotency_key: str,
        run_id: str,
    ) -> None:
        if not idempotency_key:
            return
        state = _read_workflow_event_receipts()
        receipts = state.get("receipts")
        if not isinstance(receipts, dict):
            receipts = {}
        key = _workflow_event_receipt_key(template_id, idempotency_key)
        if key in receipts:
            return
        receipts[key] = {
            "template_id": template_id,
            "template_name": template_name,
            "action_key": action_key,
            "event_name": event_name,
            "source": source,
            "idempotency_key": idempotency_key,
            "run_id": run_id,
            "created_at": workflow_template_timestamp_now(),
        }
        cleaned, _ = _clean_workflow_event_receipts(receipts)
        state["receipts"] = cleaned
        _write_workflow_event_receipts(state)

    def _workflow_event_retry_max_attempts() -> int:
        raw = os.environ.get(WORKFLOW_EVENT_RETRY_MAX_ATTEMPTS_ENV)
        value = core._safe_non_negative_int(raw, default=WORKFLOW_EVENT_RETRY_MAX_ATTEMPTS)
        if value < 1:
            return WORKFLOW_EVENT_RETRY_MAX_ATTEMPTS
        if value > 10:
            return 10
        return value

    def _workflow_event_retry_base_delay_seconds() -> int:
        raw = os.environ.get(WORKFLOW_EVENT_RETRY_BASE_DELAY_SECONDS_ENV)
        value = core._safe_non_negative_int(raw, default=WORKFLOW_EVENT_RETRY_BASE_DELAY_SECONDS)
        if value < 1:
            return WORKFLOW_EVENT_RETRY_BASE_DELAY_SECONDS
        if value > 3600:
            return 3600
        return value

    def _workflow_event_retry_terminal_ttl_days() -> int:
        raw = os.environ.get(WORKFLOW_EVENT_RETRY_TERMINAL_TTL_DAYS_ENV)
        value = core._safe_non_negative_int(raw, default=WORKFLOW_EVENT_RETRY_TERMINAL_TTL_DAYS)
        if value < 1:
            return WORKFLOW_EVENT_RETRY_TERMINAL_TTL_DAYS
        if value > 3650:
            return 3650
        return value

    def _workflow_event_retry_max_jobs() -> int:
        raw = os.environ.get(WORKFLOW_EVENT_RETRY_MAX_JOBS_ENV)
        value = core._safe_non_negative_int(raw, default=WORKFLOW_EVENT_RETRY_MAX_JOBS)
        if value < 10:
            return WORKFLOW_EVENT_RETRY_MAX_JOBS
        if value > 20000:
            return 20000
        return value

    def _workflow_event_retry_jobs_path():
        return core._artifact_root() / "_workflow_events" / "retry_jobs.json"

    def _workflow_event_retry_job_key(template_id: str, idempotency_key: str) -> str:
        normalized_template_id = normalize_workflow_template_id(template_id)
        normalized_idempotency_key = _normalize_workflow_event_idempotency_key(idempotency_key)
        if not normalized_template_id or not normalized_idempotency_key:
            return ""
        return f"{normalized_template_id}:{normalized_idempotency_key}"

    def _workflow_event_parse_iso(value: Any) -> datetime | None:
        text = normalize_workflow_template_timestamp(value)
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    def _normalize_workflow_event_retry_job(value: Any) -> dict[str, Any] | None:
        row = value if isinstance(value, dict) else {}
        template_id = normalize_workflow_template_id(row.get("template_id"))
        idempotency_key = _normalize_workflow_event_idempotency_key(row.get("idempotency_key"))
        key = _workflow_event_retry_job_key(template_id, idempotency_key)
        if not key:
            return None

        year = core._safe_non_negative_int(row.get("year"), default=0)
        month = core._safe_non_negative_int(row.get("month"), default=0)
        if year < 2000 or month < 1 or month > 12:
            return None

        status = str(row.get("status") or "pending").strip().lower()
        known_statuses = WORKFLOW_EVENT_RETRY_ACTIVE_STATUSES | WORKFLOW_EVENT_RETRY_TERMINAL_STATUSES
        if status not in known_statuses:
            status = "pending"

        attempts = core._safe_non_negative_int(row.get("attempts"), default=0)
        if attempts < 0:
            attempts = 0
        if attempts > 100:
            attempts = 100

        max_attempts = core._safe_non_negative_int(row.get("max_attempts"), default=_workflow_event_retry_max_attempts())
        if max_attempts < 1:
            max_attempts = _workflow_event_retry_max_attempts()
        if max_attempts > 10:
            max_attempts = 10

        next_retry_at = normalize_workflow_template_timestamp(row.get("next_retry_at"))
        created_at = normalize_workflow_template_timestamp(row.get("created_at"))
        updated_at = normalize_workflow_template_timestamp(row.get("updated_at"))
        if not created_at:
            created_at = workflow_template_timestamp_now()
        if not updated_at:
            updated_at = created_at

        out: dict[str, Any] = {
            "template_id": template_id,
            "template_name": str(row.get("template_name") or "").strip()[:WORKFLOW_EVENT_RETRY_TEMPLATE_NAME_CHARS],
            "action_key": _normalize_step_action(row.get("action_key")),
            "event_name": str(row.get("event_name") or "").strip()[:WORKFLOW_EVENT_MAX_EVENT_NAME_CHARS],
            "source": str(row.get("source") or "").strip()[:WORKFLOW_EVENT_MAX_SOURCE_CHARS],
            "idempotency_key": idempotency_key,
            "year": year,
            "month": month,
            "mfcloud_url": str(row.get("mfcloud_url") or "").strip()[:WORKFLOW_EVENT_RETRY_URL_CHARS],
            "notes": str(row.get("notes") or "").strip()[:WORKFLOW_EVENT_RETRY_NOTES_CHARS],
            "status": status,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "next_retry_at": next_retry_at,
            "last_error": str(row.get("last_error") or "").strip()[:500],
            "last_reason_class": str(row.get("last_reason_class") or "").strip().lower()[:64],
            "last_reason_code": str(row.get("last_reason_code") or "").strip().lower()[:64],
            "last_retry_advice": str(row.get("last_retry_advice") or "").strip().lower()[:64],
            "last_run_id": str(row.get("last_run_id") or "").strip()[:128],
            "created_at": created_at,
            "updated_at": updated_at,
        }
        if not out["action_key"]:
            out["action_key"] = _normalize_step_action(row.get("event_name"))
        if not out["event_name"]:
            out["event_name"] = out["action_key"][:WORKFLOW_EVENT_MAX_EVENT_NAME_CHARS]
        return out

    def _clean_workflow_event_retry_jobs(
        jobs: dict[str, Any],
    ) -> tuple[dict[str, dict[str, Any]], bool]:
        changed = False
        cleaned: dict[str, dict[str, Any]] = {}
        expire_before = datetime.now() - timedelta(days=_workflow_event_retry_terminal_ttl_days())

        for key, value in jobs.items():
            if not isinstance(key, str) or not key.strip():
                changed = True
                continue
            normalized = _normalize_workflow_event_retry_job(value)
            if not normalized:
                changed = True
                continue
            normalized_key = _workflow_event_retry_job_key(
                str(normalized.get("template_id") or ""),
                str(normalized.get("idempotency_key") or ""),
            )
            if not normalized_key:
                changed = True
                continue

            status = str(normalized.get("status") or "").strip().lower()
            if status in WORKFLOW_EVENT_RETRY_TERMINAL_STATUSES:
                updated_dt = _workflow_event_parse_iso(normalized.get("updated_at"))
                if updated_dt is not None and updated_dt < expire_before:
                    changed = True
                    continue

            if normalized_key != key:
                changed = True
            cleaned[normalized_key] = normalized

        max_jobs = _workflow_event_retry_max_jobs()
        if len(cleaned) > max_jobs:
            drop_count = len(cleaned) - max_jobs
            keys_sorted = sorted(
                cleaned.keys(),
                key=lambda item: (
                    0
                    if str(cleaned[item].get("status") or "").strip().lower() in WORKFLOW_EVENT_RETRY_TERMINAL_STATUSES
                    else 1,
                    str(cleaned[item].get("updated_at") or ""),
                    item,
                ),
            )
            for stale_key in keys_sorted[:drop_count]:
                cleaned.pop(stale_key, None)
            changed = True

        return cleaned, changed

    def _read_workflow_event_retry_jobs() -> dict[str, dict[str, Any]]:
        raw = core._read_json(_workflow_event_retry_jobs_path())
        jobs = raw.get("jobs") if isinstance(raw, dict) else {}
        if not isinstance(jobs, dict):
            return {"jobs": {}}
        cleaned, changed = _clean_workflow_event_retry_jobs(jobs)
        state = {"jobs": cleaned}
        if changed:
            _write_workflow_event_retry_jobs(state)
        return state

    def _write_workflow_event_retry_jobs(state: dict[str, Any]) -> None:
        jobs = state.get("jobs") if isinstance(state, dict) else {}
        payload = {"jobs": jobs if isinstance(jobs, dict) else {}}
        path = _workflow_event_retry_jobs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        core._write_json(path, payload)

    def _workflow_event_retry_backoff_seconds(attempts: int) -> int:
        safe_attempts = max(1, core._safe_non_negative_int(attempts, default=1))
        base = _workflow_event_retry_base_delay_seconds()
        delay = base * (2 ** max(0, safe_attempts - 1))
        if delay > 24 * 3600:
            return 24 * 3600
        return delay

    def _workflow_event_retry_due(job: dict[str, Any], now: datetime, *, force: bool = False) -> bool:
        if force:
            return True
        next_retry_dt = _workflow_event_parse_iso(job.get("next_retry_at"))
        if next_retry_dt is None:
            return True
        return next_retry_dt <= now

    def _workflow_event_retry_queue_snapshot(*, limit: int = 20) -> dict[str, Any]:
        state = _read_workflow_event_retry_jobs()
        jobs = state.get("jobs") if isinstance(state.get("jobs"), dict) else {}
        now = datetime.now()
        by_status: Counter[str] = Counter()
        due = 0
        rows: list[dict[str, Any]] = []

        for value in jobs.values():
            if not isinstance(value, dict):
                continue
            status = str(value.get("status") or "").strip().lower()
            if not status:
                status = "unknown"
            by_status[status] += 1
            if status in WORKFLOW_EVENT_RETRY_ACTIVE_STATUSES and _workflow_event_retry_due(value, now):
                due += 1
            rows.append(dict(value))

        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        bounded_limit = max(1, min(int(limit), 200))
        return {
            "total": len(rows),
            "due": due,
            "by_status": _workflow_event_counter_rows(by_status, key_name="status"),
            "jobs": rows[:bounded_limit],
            "policy": {
                "max_attempts": _workflow_event_retry_max_attempts(),
                "base_delay_seconds": _workflow_event_retry_base_delay_seconds(),
                "terminal_ttl_days": _workflow_event_retry_terminal_ttl_days(),
                "max_jobs": _workflow_event_retry_max_jobs(),
            },
        }

    def _enqueue_workflow_event_retry_job(
        *,
        template_id: str,
        template_name: str,
        action_key: str,
        event_name: str,
        source: str,
        idempotency_key: str,
        year: int | None,
        month: int | None,
        mfcloud_url: str,
        notes: str,
        reason: str,
        reason_class: str,
        reason_code: str,
        retry_advice: str,
    ) -> dict[str, Any]:
        normalized_retry_advice = str(retry_advice or "").strip().lower()
        if normalized_retry_advice != "retry_with_backoff":
            return {"queued": False, "reason": "retry_advice_not_backoff", "retry_advice": normalized_retry_advice}

        normalized_template_id = normalize_workflow_template_id(template_id)
        normalized_idempotency_key = _normalize_workflow_event_idempotency_key(idempotency_key)
        if not normalized_template_id or not normalized_idempotency_key:
            return {"queued": False, "reason": "missing_idempotency_key", "retry_advice": normalized_retry_advice}
        if year is None or month is None or year < 2000 or month < 1 or month > 12:
            return {"queued": False, "reason": "invalid_year_month", "retry_advice": normalized_retry_advice}

        key = _workflow_event_retry_job_key(normalized_template_id, normalized_idempotency_key)
        if not key:
            return {"queued": False, "reason": "invalid_job_key", "retry_advice": normalized_retry_advice}

        state = _read_workflow_event_retry_jobs()
        jobs = state.get("jobs")
        if not isinstance(jobs, dict):
            jobs = {}
        now_iso = workflow_template_timestamp_now()
        existing = jobs.get(key) if isinstance(jobs.get(key), dict) else None
        existing_status = str((existing or {}).get("status") or "").strip().lower()
        is_active = existing_status in WORKFLOW_EVENT_RETRY_ACTIVE_STATUSES

        next_retry_at = normalize_workflow_template_timestamp((existing or {}).get("next_retry_at"))
        if not next_retry_at:
            next_retry_at = (datetime.now() + timedelta(seconds=_workflow_event_retry_base_delay_seconds())).isoformat(
                timespec="seconds"
            )

        jobs[key] = {
            "template_id": normalized_template_id,
            "template_name": str(template_name or "").strip()[:WORKFLOW_EVENT_RETRY_TEMPLATE_NAME_CHARS],
            "action_key": _normalize_step_action(action_key),
            "event_name": str(event_name or "").strip()[:WORKFLOW_EVENT_MAX_EVENT_NAME_CHARS],
            "source": str(source or "").strip()[:WORKFLOW_EVENT_MAX_SOURCE_CHARS],
            "idempotency_key": normalized_idempotency_key,
            "year": int(year),
            "month": int(month),
            "mfcloud_url": str(mfcloud_url or "").strip()[:WORKFLOW_EVENT_RETRY_URL_CHARS],
            "notes": str(notes or "").strip()[:WORKFLOW_EVENT_RETRY_NOTES_CHARS],
            "status": "pending",
            "attempts": int((existing or {}).get("attempts") or 0) if is_active else 0,
            "max_attempts": int((existing or {}).get("max_attempts") or _workflow_event_retry_max_attempts()),
            "next_retry_at": next_retry_at,
            "last_error": str(reason or "").strip()[:500],
            "last_reason_class": str(reason_class or "").strip().lower()[:64],
            "last_reason_code": str(reason_code or "").strip().lower()[:64],
            "last_retry_advice": normalized_retry_advice,
            "last_run_id": str((existing or {}).get("last_run_id") or "").strip()[:128],
            "created_at": normalize_workflow_template_timestamp((existing or {}).get("created_at")) or now_iso,
            "updated_at": now_iso,
        }
        cleaned, _ = _clean_workflow_event_retry_jobs(jobs)
        state["jobs"] = cleaned
        _write_workflow_event_retry_jobs(state)

        current = cleaned.get(key) if isinstance(cleaned.get(key), dict) else {}
        return {
            "queued": True,
            "reason": "already_pending" if is_active else "queued",
            "retry_advice": normalized_retry_advice,
            "job_key": key,
            "next_retry_at": str(current.get("next_retry_at") or ""),
            "attempts": int(current.get("attempts") or 0),
            "max_attempts": int(current.get("max_attempts") or _workflow_event_retry_max_attempts()),
        }

    def _mark_workflow_event_retry_job_succeeded(
        *,
        template_id: str,
        idempotency_key: str,
        run_id: str = "",
    ) -> None:
        key = _workflow_event_retry_job_key(template_id, idempotency_key)
        if not key:
            return
        state = _read_workflow_event_retry_jobs()
        jobs = state.get("jobs")
        if not isinstance(jobs, dict):
            return
        job = jobs.get(key)
        if not isinstance(job, dict):
            return
        job["status"] = "succeeded"
        job["next_retry_at"] = ""
        job["last_error"] = ""
        job["last_reason_class"] = ""
        job["last_reason_code"] = ""
        job["last_retry_advice"] = ""
        if run_id:
            job["last_run_id"] = str(run_id).strip()[:128]
        job["updated_at"] = workflow_template_timestamp_now()
        cleaned, _ = _clean_workflow_event_retry_jobs(jobs)
        state["jobs"] = cleaned
        _write_workflow_event_retry_jobs(state)

    def _workflow_event_status_for_http(status_code: int) -> str:
        if status_code in {400, 401, 403, 404, 409, 422}:
            return "rejected"
        return "failed"

    def _workflow_event_error_class(status_code: int, detail: str) -> str:
        text = str(detail or "").strip().lower()
        if status_code in {401, 403}:
            return "auth"
        if status_code == 404:
            if "template" in text or "event_name" in text:
                return "template_not_found"
            return "not_found"
        if status_code == 409:
            if "already in progress" in text:
                return "run_conflict"
            if "external_event action is not executable" in text:
                return "unsupported_action"
            if "template" in text or "event_name" in text:
                return "template_conflict"
            return "conflict"
        if status_code in {400, 422}:
            return "validation"
        return "infra"

    def _workflow_event_retry_advice(*, status: str, reason_class: str) -> str:
        normalized_status = str(status or "").strip().lower()
        normalized_reason_class = str(reason_class or "").strip().lower()
        if normalized_status == "success":
            return ""
        if normalized_reason_class == "duplicate":
            return "do_not_retry"
        if normalized_reason_class in {
            "auth",
            "validation",
            "template_conflict",
            "template_not_found",
            "not_found",
            "unsupported_action",
        }:
            return "retry_after_fix"
        if normalized_reason_class in {"run_conflict", "infra", "conflict"}:
            return "retry_with_backoff"
        if normalized_status == "failed":
            return "retry_with_backoff"
        if normalized_status in {"rejected", "skipped"}:
            return "retry_after_fix"
        return "retry_after_fix"

    def _workflow_event_notification_settings_path():
        return core._artifact_root() / "_workflow_events" / WORKFLOW_EVENT_NOTIFICATION_SETTINGS_FILE

    def _is_valid_workflow_event_google_chat_webhook_url(value: Any) -> bool:
        raw = str(value or "").strip()
        if not raw or any(ch.isspace() for ch in raw):
            return False
        try:
            parsed = url_parse.urlsplit(raw)
        except Exception:
            return False
        if str(parsed.scheme or "").strip().lower() != "https":
            return False
        if str(parsed.netloc or "").strip().lower() != "chat.googleapis.com":
            return False
        path = str(parsed.path or "").strip()
        if not path.startswith("/v1/spaces/") or not path.endswith("/messages"):
            return False
        query = url_parse.parse_qs(parsed.query, keep_blank_values=False)
        key = str((query.get("key") or [""])[0] or "").strip()
        token = str((query.get("token") or [""])[0] or "").strip()
        return bool(key and token)

    def _mask_workflow_event_secret(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        length = len(raw)
        if length <= 4:
            return "*" * length
        if length <= 8:
            return f"{raw[:1]}{'*' * (length - 2)}{raw[-1:]}"
        return f"{raw[:4]}...{raw[-4:]}"

    def _mask_workflow_event_google_chat_webhook_url(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = url_parse.urlsplit(raw)
        except Exception:
            return _mask_workflow_event_secret(raw)
        if not parsed.scheme or not parsed.netloc:
            return _mask_workflow_event_secret(raw)

        path_segments = [segment for segment in str(parsed.path or "").split("/") if segment]
        for index, segment in enumerate(path_segments):
            if index > 0 and path_segments[index - 1] == "spaces":
                path_segments[index] = _mask_workflow_event_secret(segment)
        masked_path = f"/{'/'.join(path_segments)}" if path_segments else str(parsed.path or "")

        masked_query_pairs: list[tuple[str, str]] = []
        for key, val in url_parse.parse_qsl(parsed.query, keep_blank_values=True):
            normalized_key = str(key or "").strip().lower()
            if normalized_key in {"key", "token"}:
                masked_query_pairs.append((key, _mask_workflow_event_secret(val)))
            else:
                masked_query_pairs.append((key, val))
        masked_query = url_parse.urlencode(masked_query_pairs, doseq=True)
        return url_parse.urlunsplit((parsed.scheme, parsed.netloc, masked_path, masked_query, ""))

    def _read_workflow_event_notification_settings_file() -> dict[str, str]:
        payload = core._read_json(_workflow_event_notification_settings_path())
        row = payload if isinstance(payload, dict) else {}
        webhook_url = str(row.get("webhook_url") or "").strip()
        updated_at = normalize_workflow_template_timestamp(row.get("updated_at"))
        if not webhook_url or not _is_valid_workflow_event_google_chat_webhook_url(webhook_url):
            return {"webhook_url": "", "updated_at": ""}
        return {"webhook_url": webhook_url, "updated_at": updated_at}

    def _write_workflow_event_notification_settings_file(*, webhook_url: str) -> dict[str, str]:
        normalized = str(webhook_url or "").strip()
        payload = {"webhook_url": normalized, "updated_at": workflow_template_timestamp_now()}
        path = _workflow_event_notification_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        core._write_json(path, payload)
        return payload

    def _clear_workflow_event_notification_settings_file() -> None:
        path = _workflow_event_notification_settings_path()
        try:
            path.unlink()
        except FileNotFoundError:
            return

    def _workflow_event_notification_webhook_status() -> dict[str, Any]:
        file_row = _read_workflow_event_notification_settings_file()
        file_webhook = str(file_row.get("webhook_url") or "").strip()
        if file_webhook:
            return {
                "configured": True,
                "webhook_url": file_webhook,
                "webhook_url_masked": _mask_workflow_event_google_chat_webhook_url(file_webhook),
                "source": "file",
                "updated_at": str(file_row.get("updated_at") or "").strip(),
            }
        env_webhook = str(os.environ.get(WORKFLOW_EVENT_GOOGLE_CHAT_WEBHOOK_URL_ENV) or "").strip()
        if _is_valid_workflow_event_google_chat_webhook_url(env_webhook):
            return {
                "configured": True,
                "webhook_url": env_webhook,
                "webhook_url_masked": _mask_workflow_event_google_chat_webhook_url(env_webhook),
                "source": "env",
                "updated_at": "",
            }
        return {
            "configured": False,
            "webhook_url": "",
            "webhook_url_masked": "",
            "source": "none",
            "updated_at": "",
        }

    def _workflow_event_notification_settings_response_payload() -> dict[str, Any]:
        settings = _workflow_event_notification_webhook_status()
        return {
            "status": "ok",
            "configured": bool(settings.get("configured")),
            "webhook_url_masked": str(settings.get("webhook_url_masked") or ""),
            "source": str(settings.get("source") or "none"),
            "updated_at": str(settings.get("updated_at") or ""),
        }

    def _workflow_event_google_chat_webhook_url() -> str:
        status = _workflow_event_notification_webhook_status()
        return str(status.get("webhook_url") or "").strip()

    def _workflow_event_google_chat_send(text: str, *, webhook_url: str) -> dict[str, Any]:
        safe_webhook_url = str(webhook_url or "").strip()
        if not safe_webhook_url:
            return {
                "sent": False,
                "http_status": 0,
                "reason": "google chat webhook is not configured",
                "reason_code": "webhook_not_configured",
            }

        request = url_request.Request(
            safe_webhook_url,
            data=json.dumps({"text": str(text or "")}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=UTF-8"},
            method="POST",
        )
        try:
            with url_request.urlopen(request, timeout=WORKFLOW_EVENT_GOOGLE_CHAT_TIMEOUT_SECONDS) as response:
                status_raw = getattr(response, "status", None)
                if status_raw is None:
                    status_raw = response.getcode()
                status_code = int(status_raw or 0)
                response.read()
        except url_error.HTTPError as exc:
            reason_text = ""
            try:
                reason_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                reason_text = str(exc)
            return {
                "sent": False,
                "http_status": int(exc.code),
                "reason": reason_text or f"http error {int(exc.code)}",
                "reason_code": f"http_{int(exc.code)}",
            }
        except Exception as exc:
            return {
                "sent": False,
                "http_status": 0,
                "reason": str(exc),
                "reason_code": "network_error",
            }

        if status_code >= 400:
            return {
                "sent": False,
                "http_status": status_code,
                "reason": f"unexpected response status: {status_code}",
                "reason_code": f"http_{status_code}",
            }

        return {
            "sent": True,
            "http_status": max(200, status_code),
            "reason": "sent",
            "reason_code": "sent",
        }

    def _append_workflow_event_notification_audit(
        *,
        year: int | None,
        month: int | None,
        action_key: str,
        status: str,
        actor: Any,
        template_id: str,
        template_name: str,
        event_name: str,
        source: str,
        idempotency_key: str,
        channel: str,
        attempts: int,
        max_attempts: int,
        reason: str = "",
        reason_code: str = "",
    ) -> None:
        if year is None or month is None or year < 2000 or month < 1 or month > 12:
            return
        details: dict[str, Any] = {
            "template_id": template_id,
            "template_name": template_name,
            "event_name": event_name,
            "source": source,
            "idempotency_key": idempotency_key,
            "channel": channel,
            "attempts": int(attempts),
            "max_attempts": int(max_attempts),
        }
        if reason:
            details["reason"] = str(reason).strip()[:500]
        if reason_code:
            details["reason_code"] = str(reason_code).strip().lower()[:64]
        core._append_audit_event(
            year=year,
            month=month,
            event_type="workflow_event_notification",
            action=action_key or "unknown",
            status=status,
            actor=actor,
            mode=action_key or "unknown",
            run_id=None,
            details=details,
        )

    def _workflow_event_google_chat_escalation_text(
        *,
        template_id: str,
        template_name: str,
        action_key: str,
        year: int | None,
        month: int | None,
        source: str,
        idempotency_key: str,
        attempts: int,
        max_attempts: int,
        reason_class: str,
        reason_code: str,
        reason: str,
        at: str,
    ) -> str:
        ym = (
            f"{int(year):04d}-{int(month):02d}"
            if year is not None and month is not None and year >= 2000 and 1 <= month <= 12
            else "unknown"
        )
        safe_reason = " ".join(str(reason or "").strip().split())[:300]
        safe_template_name = str(template_name or "").strip() or "unknown"
        safe_template_id = str(template_id or "").strip() or "unknown"
        safe_action = str(action_key or "").strip() or "unknown"
        safe_source = str(source or "").strip() or "unknown"
        safe_reason_class = str(reason_class or "").strip().lower() or "unknown"
        safe_reason_code = str(reason_code or "").strip().lower() or "unknown"
        safe_idempotency_key = str(idempotency_key or "").strip() or "unknown"
        safe_at = str(at or "").strip() or workflow_template_timestamp_now()

        lines = [
            "[Workflow Retry Escalated]",
            f"template: {safe_template_name} ({safe_template_id})",
            f"ym: {ym}",
            f"action: {safe_action}",
            f"source: {safe_source}",
            f"attempts: {int(attempts)}/{int(max_attempts)}",
            f"reason: {safe_reason_class} / {safe_reason_code}",
            f"error: {safe_reason or 'unknown'}",
            f"idempotency_key: {safe_idempotency_key}",
            f"at: {safe_at}",
            "",
            "\u5bfe\u5fdc: /expense-workflow-copy \u306e Retry Queue \u3092\u78ba\u8a8d\u3057\u3001\u539f\u56e0\u4fee\u6b63\u5f8c\u306b\u518d\u9001\u3002",
        ]
        return "\n".join(lines)

    def _notify_workflow_event_retry_escalated(
        *,
        actor: Any,
        year: int | None,
        month: int | None,
        template_id: str,
        template_name: str,
        action_key: str,
        event_name: str,
        source: str,
        idempotency_key: str,
        attempts: int,
        max_attempts: int,
        reason_class: str,
        reason_code: str,
        reason: str,
        at: str,
    ) -> dict[str, Any]:
        webhook_url = _workflow_event_google_chat_webhook_url()

        text = _workflow_event_google_chat_escalation_text(
            template_id=template_id,
            template_name=template_name,
            action_key=action_key,
            year=year,
            month=month,
            source=source,
            idempotency_key=idempotency_key,
            attempts=attempts,
            max_attempts=max_attempts,
            reason_class=reason_class,
            reason_code=reason_code,
            reason=reason,
            at=at,
        )
        result = _workflow_event_google_chat_send(text, webhook_url=webhook_url)
        sent = bool(result.get("sent"))
        reason_code = str(result.get("reason_code") or "").strip().lower()
        reason = str(result.get("reason") or "").strip()
        http_status = core._safe_non_negative_int(result.get("http_status"), default=0)
        if not sent:
            notify_status = "failed"
            if reason_code == "webhook_not_configured":
                notify_status = "skipped"
            _append_workflow_event_notification_audit(
                year=year,
                month=month,
                action_key=action_key,
                status=notify_status,
                actor=actor,
                template_id=template_id,
                template_name=template_name,
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                channel="google_chat",
                attempts=attempts,
                max_attempts=max_attempts,
                reason=reason,
                reason_code=reason_code,
            )
            return {"sent": False, "status": notify_status, "reason": reason_code, "http_status": http_status}

        _append_workflow_event_notification_audit(
            year=year,
            month=month,
            action_key=action_key,
            status="success",
            actor=actor,
            template_id=template_id,
            template_name=template_name,
            event_name=event_name,
            source=source,
            idempotency_key=idempotency_key,
            channel="google_chat",
            attempts=attempts,
            max_attempts=max_attempts,
            reason="sent",
            reason_code="sent",
        )
        return {"sent": True, "status": "success", "http_status": http_status}

    def _maybe_enqueue_workflow_event_retry(
        *,
        template_id: str,
        template_name: str,
        action_key: str,
        event_name: str,
        source: str,
        idempotency_key: str,
        year: int | None,
        month: int | None,
        mfcloud_url: str,
        notes: str,
        status: str,
        reason: str,
        reason_class: str,
        reason_code: str,
    ) -> dict[str, Any]:
        retry_advice = _workflow_event_retry_advice(status=status, reason_class=reason_class)
        return _enqueue_workflow_event_retry_job(
            template_id=template_id,
            template_name=template_name,
            action_key=action_key,
            event_name=event_name,
            source=source,
            idempotency_key=idempotency_key,
            year=year,
            month=month,
            mfcloud_url=mfcloud_url,
            notes=notes,
            reason=reason,
            reason_class=reason_class,
            reason_code=reason_code,
            retry_advice=retry_advice,
        )

    def _append_workflow_event_audit(
        *,
        year: int | None,
        month: int | None,
        action_key: str,
        status: str,
        actor: Any,
        template_id: str,
        template_name: str,
        event_name: str,
        source: str,
        idempotency_key: str,
        run_id: str = "",
        reason: str = "",
        reason_class: str = "",
        reason_code: str = "",
        retry_advice: str = "",
        duplicate: bool | None = None,
    ) -> None:
        if year is None or month is None or year < 2000 or month < 1 or month > 12:
            return
        details: dict[str, Any] = {
            "template_id": template_id,
            "template_name": template_name,
            "event_name": event_name,
            "source": source,
            "idempotency_key": idempotency_key,
        }
        if reason:
            details["reason"] = reason
        if reason_class:
            details["reason_class"] = reason_class
        if reason_code:
            details["reason_code"] = reason_code
        normalized_retry_advice = str(retry_advice or "").strip().lower()
        if not normalized_retry_advice:
            normalized_retry_advice = _workflow_event_retry_advice(status=status, reason_class=reason_class)
        if normalized_retry_advice:
            details["retry_advice"] = normalized_retry_advice
        if duplicate is not None:
            details["duplicate"] = bool(duplicate)
        core._append_audit_event(
            year=year,
            month=month,
            event_type="workflow_event",
            action=action_key or "unknown",
            status=status,
            actor=actor,
            mode=action_key or "unknown",
            run_id=run_id or None,
            details=details,
        )

    def _workflow_event_counter_rows(counter: Counter[str], *, key_name: str) -> list[dict[str, Any]]:
        rows = [
            {
                key_name: str(key or ""),
                "count": int(value),
            }
            for key, value in counter.items()
            if str(key or "").strip() and int(value) > 0
        ]
        rows.sort(key=lambda row: (-int(row["count"]), str(row.get(key_name) or "")))
        return rows

    def _summarize_workflow_event_audit_rows(
        rows: list[dict[str, Any]],
        *,
        recent_limit: int = 20,
    ) -> dict[str, Any]:
        status_counter: Counter[str] = Counter()
        reason_class_counter: Counter[str] = Counter()
        reason_code_counter: Counter[str] = Counter()
        retry_advice_counter: Counter[str] = Counter()
        duplicate_counter: Counter[str] = Counter()
        events: list[dict[str, Any]] = []

        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("event_type") or "").strip() != "workflow_event":
                continue

            status = str(row.get("status") or "").strip().lower()
            if status not in {"success", "skipped", "rejected", "failed"}:
                status = "unknown"
            status_counter[status] += 1

            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            reason_class = str(details.get("reason_class") or "").strip().lower()
            reason_code = str(details.get("reason_code") or "").strip().lower()
            if reason_class:
                reason_class_counter[reason_class] += 1
            if reason_code:
                reason_code_counter[reason_code] += 1
            retry_advice = str(details.get("retry_advice") or "").strip().lower()
            if not retry_advice:
                retry_advice = _workflow_event_retry_advice(status=status, reason_class=reason_class)
            if retry_advice:
                retry_advice_counter[retry_advice] += 1

            duplicate_raw = details.get("duplicate")
            duplicate_value: bool | None = None
            duplicate_key = "unknown"
            if isinstance(duplicate_raw, bool):
                duplicate_value = duplicate_raw
                duplicate_key = "true" if duplicate_raw else "false"
            duplicate_counter[duplicate_key] += 1

            events.append(
                {
                    "at": str(row.get("at") or "").strip(),
                    "status": status,
                    "action": str(row.get("action") or "").strip(),
                    "run_id": str(row.get("run_id") or "").strip(),
                    "template_id": str(details.get("template_id") or "").strip(),
                    "template_name": str(details.get("template_name") or "").strip(),
                    "event_name": str(details.get("event_name") or "").strip(),
                    "source": str(details.get("source") or "").strip(),
                    "idempotency_key": str(details.get("idempotency_key") or "").strip(),
                    "reason": str(details.get("reason") or "").strip(),
                    "reason_class": reason_class,
                    "reason_code": reason_code,
                    "retry_advice": retry_advice,
                    "duplicate": duplicate_value,
                }
            )

        events.sort(key=lambda row: str(row.get("at") or ""), reverse=True)
        limit = max(1, min(int(recent_limit), 200))
        recent = events[:limit]

        first_at = str(events[-1].get("at") or "") if events else ""
        last_at = str(events[0].get("at") or "") if events else ""

        return {
            "event_type": "workflow_event",
            "total": len(events),
            "first_at": first_at,
            "last_at": last_at,
            "by_status": {
                "success": int(status_counter.get("success", 0)),
                "skipped": int(status_counter.get("skipped", 0)),
                "rejected": int(status_counter.get("rejected", 0)),
                "failed": int(status_counter.get("failed", 0)),
                "unknown": int(status_counter.get("unknown", 0)),
            },
            "by_reason_class": _workflow_event_counter_rows(reason_class_counter, key_name="reason_class"),
            "by_reason_code": _workflow_event_counter_rows(reason_code_counter, key_name="reason_code"),
            "by_retry_advice": _workflow_event_counter_rows(retry_advice_counter, key_name="retry_advice"),
            "duplicate": {
                "true": int(duplicate_counter.get("true", 0)),
                "false": int(duplicate_counter.get("false", 0)),
                "unknown": int(duplicate_counter.get("unknown", 0)),
            },
            "recent": recent,
        }

    def _summarize_workflow_event_notification_rows(
        rows: list[dict[str, Any]],
        *,
        recent_limit: int = 20,
    ) -> dict[str, Any]:
        status_counter: Counter[str] = Counter()
        reason_code_counter: Counter[str] = Counter()
        events: list[dict[str, Any]] = []

        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("event_type") or "").strip() != "workflow_event_notification":
                continue

            status = str(row.get("status") or "").strip().lower()
            if status not in {"success", "failed", "skipped"}:
                status = "unknown"
            status_counter[status] += 1

            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            reason_code = str(details.get("reason_code") or "").strip().lower()
            if reason_code:
                reason_code_counter[reason_code] += 1

            events.append(
                {
                    "at": str(row.get("at") or "").strip(),
                    "status": status,
                    "action": str(row.get("action") or "").strip(),
                    "template_id": str(details.get("template_id") or "").strip(),
                    "template_name": str(details.get("template_name") or "").strip(),
                    "event_name": str(details.get("event_name") or "").strip(),
                    "source": str(details.get("source") or "").strip(),
                    "idempotency_key": str(details.get("idempotency_key") or "").strip(),
                    "channel": str(details.get("channel") or "").strip().lower(),
                    "reason": str(details.get("reason") or "").strip(),
                    "reason_code": reason_code,
                    "attempts": core._safe_non_negative_int(details.get("attempts"), default=0),
                    "max_attempts": core._safe_non_negative_int(details.get("max_attempts"), default=0),
                }
            )

        events.sort(key=lambda row: str(row.get("at") or ""), reverse=True)
        limit = max(1, min(int(recent_limit), 200))
        recent = events[:limit]

        first_at = str(events[-1].get("at") or "") if events else ""
        last_at = str(events[0].get("at") or "") if events else ""

        return {
            "event_type": "workflow_event_notification",
            "total": len(events),
            "first_at": first_at,
            "last_at": last_at,
            "by_status": {
                "success": int(status_counter.get("success", 0)),
                "failed": int(status_counter.get("failed", 0)),
                "skipped": int(status_counter.get("skipped", 0)),
                "unknown": int(status_counter.get("unknown", 0)),
            },
            "by_reason_code": _workflow_event_counter_rows(reason_code_counter, key_name="reason_code"),
            "recent": recent,
        }

    def _resolve_external_event_template(
        payload: dict[str, Any],
        templates: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        requested_template_id = normalize_workflow_template_id(payload.get("template_id") or payload.get("templateId"))
        requested_event_name = str(payload.get("event_name") or payload.get("eventName") or "").strip().lower()

        external_templates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for template in templates:
            first_step = _first_workflow_template_step(template)
            trigger_kind = _normalize_step_trigger_kind(first_step.get("trigger_kind"))
            if trigger_kind == "external_event":
                external_templates.append((template, first_step))

        if requested_template_id:
            for template, first_step in external_templates:
                if str(template.get("id") or "") == requested_template_id:
                    return template, first_step
            for template in templates:
                if str(template.get("id") or "") == requested_template_id:
                    raise HTTPException(status_code=409, detail="Template step 1 must use trigger_kind=external_event.")
            raise HTTPException(status_code=404, detail="Workflow template not found.")

        if requested_event_name:
            matched = [
                (template, first_step)
                for template, first_step in external_templates
                if _normalize_step_action(first_step.get("action")).lower() == requested_event_name
            ]
            if not matched:
                raise HTTPException(status_code=404, detail="No external_event workflow template matched event_name.")
            if len(matched) > 1:
                raise HTTPException(status_code=409, detail="Multiple templates matched event_name. Specify template_id.")
            return matched[0]

        if len(external_templates) == 1:
            return external_templates[0]
        if not external_templates:
            raise HTTPException(status_code=404, detail="No external_event workflow template was found.")
        raise HTTPException(status_code=409, detail="Multiple external_event templates found. Specify template_id.")

    @router.get("/api/workspace/state")
    def api_get_workspace_state() -> JSONResponse:
        state = read_workspace_state()
        return JSONResponse({"status": "ok", **state}, headers={"Cache-Control": "no-store"})

    @router.post("/api/workspace/state")
    def api_set_workspace_state(payload: dict[str, Any]) -> JSONResponse:
        payload = payload if isinstance(payload, dict) else {}
        current = read_workspace_state()
        current_revision = core._safe_non_negative_int(current.get("revision"), default=0)
        base_revision_raw = payload.get("base_revision")
        has_base_revision = base_revision_raw is not None
        base_revision = core._safe_non_negative_int(base_revision_raw, default=-1)
        revision_conflict = bool(has_base_revision and base_revision != current_revision)

        if "links" in payload:
            links_payload = sanitize_workspace_links(payload.get("links"))
            if revision_conflict:
                current["links"] = merge_workspace_links(links_payload, sanitize_workspace_links(current.get("links")))
            else:
                current["links"] = links_payload
        if "pinned_link_groups" in payload:
            pinned_link_groups_payload = sanitize_workspace_pinned_link_groups(payload.get("pinned_link_groups"))
            current_server_groups = sanitize_workspace_pinned_link_groups(current.get("pinned_link_groups"))
            if revision_conflict:
                current["pinned_link_groups"] = merge_workspace_pinned_link_groups(
                    pinned_link_groups_payload,
                    current_server_groups,
                )
            else:
                current["pinned_link_groups"] = pinned_link_groups_payload
        elif "pinned_links" in payload:
            current_server_groups = sanitize_workspace_pinned_link_groups(current.get("pinned_link_groups"))
            first_server_group = current_server_groups[0] if current_server_groups else {}
            first_label = str(first_server_group.get("label") or "").strip() or "蝗ｺ螳壹Μ繝ｳ繧ｯ1"
            first_id = str(first_server_group.get("id") or "").strip()
            legacy_links = sanitize_workspace_pinned_links(payload.get("pinned_links"))
            legacy_group = {
                "id": first_id if first_id else "",
                "label": first_label,
                "links": legacy_links,
                "created_at": str(first_server_group.get("created_at") or "").strip() if first_server_group else "",
            }
            if current_server_groups:
                next_groups = current_server_groups[:]
                if next_groups:
                    next_groups[0] = legacy_group
                current["pinned_link_groups"] = next_groups
            elif legacy_group.get("links"):
                current["pinned_link_groups"] = [legacy_group]
            else:
                current["pinned_link_groups"] = []
            if revision_conflict:
                current["pinned_link_groups"] = merge_workspace_pinned_link_groups(
                    current["pinned_link_groups"],
                    current_server_groups,
                )
        if "pinned_link_groups" in payload or "pinned_links" in payload:
            pinned_groups = sanitize_workspace_pinned_link_groups(current.get("pinned_link_groups"))
            current["pinned_links"] = sanitize_workspace_pinned_links(
                pinned_groups[0].get("links") if pinned_groups else []
            )
        if "prompts" in payload:
            prompts_payload = sanitize_workspace_prompts(payload.get("prompts"))
            if revision_conflict:
                current["prompts"] = merge_workspace_prompts(
                    prompts_payload,
                    sanitize_workspace_prompts(current.get("prompts")),
                )
            else:
                current["prompts"] = prompts_payload
        if "link_notes" in payload:
            notes_payload = sanitize_workspace_link_notes(payload.get("link_notes"))
            if revision_conflict:
                current["link_notes"] = merge_workspace_link_notes(
                    notes_payload,
                    sanitize_workspace_link_notes(current.get("link_notes")),
                )
            else:
                current["link_notes"] = notes_payload
        if "link_profiles" in payload:
            profiles_payload = sanitize_workspace_link_profiles(payload.get("link_profiles"))
            if revision_conflict:
                current["link_profiles"] = merge_workspace_link_profiles(
                    profiles_payload,
                    sanitize_workspace_link_profiles(current.get("link_profiles")),
                )
            else:
                current["link_profiles"] = profiles_payload
        if "active_prompt_key" in payload:
            current["active_prompt_key"] = sanitize_workspace_active_prompt_key(payload.get("active_prompt_key"))
        saved = write_workspace_state(current, revision=current_revision + 1)
        return JSONResponse(
            {"status": "ok", **saved, "conflict_resolved": revision_conflict},
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/api/workspace/prompt/optimize")
    def api_optimize_workspace_prompt(payload: dict[str, Any]) -> JSONResponse:
        body = payload if isinstance(payload, dict) else {}
        raw_text = str(body.get("text") or "").strip()
        if not raw_text:
            raise HTTPException(status_code=400, detail="text must not be empty.")
        if len(raw_text) > WORKSPACE_PROMPT_OPTIMIZE_MAX_TEXT_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"text exceeds {WORKSPACE_PROMPT_OPTIMIZE_MAX_TEXT_CHARS} chars.",
            )
        text = raw_text

        goal_from_client = _clean_goal_candidate(body.get("goal"))
        goal_hint = _extract_goal_hint(text)
        goal = goal_from_client or str(goal_hint.get("goal") or "").strip() or "\u5bfe\u8c61\u30bf\u30b9\u30af\u3092\u5b8c\u9042\u3067\u304d\u308b\u3088\u3046\u306b\u6700\u9069\u5316\u3059\u308b"
        locale = _normalize_prompt_optimize_locale(body.get("locale"))
        style_preset = _normalize_prompt_optimize_style(body.get("stylePreset"))

        optimize_message = _build_goal_first_optimize_prompt(
            text=text,
            goal=goal,
            locale=locale,
            style_preset=style_preset,
        )

        try:
            result = ai_chat.chat(
                messages=[{"role": "user", "content": optimize_message}],
                page_context={
                    "path": "/workspace",
                    "feature": "workspace_prompt_optimize",
                    "locale": locale,
                    "style": style_preset,
                },
                policy_profile=ai_chat.POLICY_PROFILE_STRUCTURED_JSON,
            )
        except ai_chat.MissingApiKeyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ai_chat.UpstreamTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except ai_chat.UpstreamApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        reply = result.get("reply") if isinstance(result.get("reply"), dict) else {}
        reply_text = str(reply.get("content") or "")
        parsed = _try_parse_json_object(reply_text)
        if not isinstance(parsed, dict):
            parsed = {
                "optimizedPrompt": _enforce_prompt_optimize_rules(
                    original_text=text,
                    optimized_text=text,
                    locale=locale,
                ),
                "changes": [
                    "AIのJSON応答を解析できなかったため、ルールベース最適化にフォールバックしました。"
                ],
                "assumptions": [],
                "risks": [],
                "needsConfirmation": [
                    "AI最適化の応答形式が不正だったため、ルールベース最適化を適用しました。"
                ],
            }

        try:
            normalized = _normalize_prompt_optimize_response(parsed)
        except ValueError as exc:
            normalized = {
                "optimizedPrompt": _enforce_prompt_optimize_rules(
                    original_text=text,
                    optimized_text=text,
                    locale=locale,
                ),
                "changes": [
                    "AI最適化の出力が不足していたため、ルールベース最適化にフォールバックしました。"
                ],
                "assumptions": [],
                "risks": [],
                "needsConfirmation": [f"AI最適化フォーマットエラー: {str(exc)}"],
            }

        normalized["optimizedPrompt"] = _enforce_prompt_optimize_rules(
            original_text=text,
            optimized_text=normalized["optimizedPrompt"],
            locale=locale,
        )

        token_warnings = _build_token_integrity_warnings(text, normalized["optimizedPrompt"])
        needs_confirmation = normalized["needsConfirmation"] + token_warnings
        if needs_confirmation:
            deduped: list[str] = []
            seen: set[str] = set()
            for row in needs_confirmation:
                item = str(row or "").strip()
                if not item or item in seen:
                    continue
                seen.add(item)
                deduped.append(item)
                if len(deduped) >= WORKSPACE_PROMPT_OPTIMIZE_MAX_LIST_ITEMS:
                    break
            needs_confirmation = deduped

        return JSONResponse(
            {
                "status": "ok",
                "optimizedPrompt": normalized["optimizedPrompt"],
                "changes": normalized["changes"],
                "assumptions": normalized["assumptions"],
                "risks": normalized["risks"],
                "needsConfirmation": needs_confirmation,
                "changed": normalized["optimizedPrompt"] != text,
                "goal": goal,
                "goalMeta": {
                    "source": "client" if goal_from_client else str(goal_hint.get("method") or "fallback"),
                    "confidence": 1.0 if goal_from_client else float(goal_hint.get("confidence") or 0.0),
                    "evidence": goal_hint.get("evidence") if isinstance(goal_hint.get("evidence"), list) else [],
                },
                "provider": result.get("provider"),
                "model": result.get("model"),
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/workflow-pages")
    def api_get_workflow_pages(include_archived: bool = Query(default=False)) -> JSONResponse:
        pages = read_workflow_pages(include_archived=include_archived)
        return JSONResponse(
            {"status": "ok", "workflow_pages": pages, "count": len(pages)},
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/api/workflow-pages")
    def api_create_workflow_page(payload: dict[str, Any]) -> JSONResponse:
        page = normalize_workflow_page_payload(payload)
        page["mfcloud_url"] = ""
        page["source_urls"] = []
        page["notes"] = ""
        page["rakuten_orders_url"] = ""
        page["lifecycle_state"] = "draft"
        page["fixed_at"] = ""
        existing = read_workflow_pages(include_archived=True)
        if workflow_page_name_taken(existing, str(page.get("name") or "")):
            raise HTTPException(status_code=409, detail="Workflow page name already exists.")
        if len(existing) >= workflow_page_max_items:
            raise HTTPException(status_code=409, detail="Workflow page limit reached. Remove one and create again.")
        existing.append(page)
        existing.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
        write_workflow_pages(existing)
        return JSONResponse(
            {"status": "ok", "workflow_page": page, "count": len(existing), "scheduler_copied": False},
            headers={"Cache-Control": "no-store"},
        )

    @router.patch("/api/workflow-pages/{workflow_page_id}")
    def api_update_workflow_page(workflow_page_id: str, payload: dict[str, Any]) -> JSONResponse:
        normalized_id = normalize_workflow_page_id(workflow_page_id)
        if not normalized_id:
            raise HTTPException(status_code=400, detail="Invalid workflow page id.")
        payload = payload if isinstance(payload, dict) else {}
        base_updated_at = normalize_workflow_template_timestamp(payload.get("base_updated_at"))
        base_step_version_raw = payload.get("base_step_version")
        has_base_step_version = base_step_version_raw is not None
        base_step_version = core._safe_non_negative_int(base_step_version_raw, default=0)
        updates = normalize_workflow_page_update_payload(payload)
        if not updates:
            raise HTTPException(status_code=400, detail="No updates.")

        existing = read_workflow_pages(include_archived=True)
        saved: dict[str, Any] = {}
        updated = False
        for index, page in enumerate(existing):
            if str(page.get("id") or "") != normalized_id:
                continue
            if base_updated_at and str(page.get("updated_at") or "") != base_updated_at:
                raise HTTPException(
                    status_code=409,
                    detail="Workflow page was updated by another action. Reload and try again.",
                )
            current_step_version = core._safe_non_negative_int(page.get("step_version"), default=1)
            if current_step_version < 1:
                current_step_version = 1
            if has_base_step_version and base_step_version != current_step_version:
                raise HTTPException(
                    status_code=409,
                    detail="Workflow steps were updated by another action. Reload and try again.",
                )
            lifecycle_state = str(page.get("lifecycle_state") or "draft").strip().lower()
            if lifecycle_state not in {"draft", "fixed"}:
                lifecycle_state = "draft"
            mutable_when_fixed = {
                "name",
                "subheading",
                "notes",
                "rakuten_orders_url",
                "year",
                "month",
                "steps",
                "source_urls",
                "mfcloud_url",
            }
            if lifecycle_state == "fixed" and any(key in updates for key in mutable_when_fixed):
                raise HTTPException(
                    status_code=409,
                    detail="Workflow page is fixed. Switch to draft before editing.",
                )
            next_name = str(updates.get("name") or page.get("name") or "").strip().lower()
            if next_name:
                for other in existing:
                    other_id = str(other.get("id") or "")
                    if other_id == normalized_id:
                        continue
                    if str(other.get("name") or "").strip().lower() == next_name:
                        raise HTTPException(status_code=409, detail="Workflow page name already exists.")
            merged = dict(page, **updates)
            updated_at = workflow_template_timestamp_now()
            if "steps" in updates:
                current_steps = page.get("steps") if isinstance(page.get("steps"), list) else []
                next_steps = updates.get("steps") if isinstance(updates.get("steps"), list) else []
                if current_steps != next_steps:
                    next_step_version = current_step_version + 1
                    raw_versions = page.get("step_versions") if isinstance(page.get("step_versions"), list) else []
                    versions: list[dict[str, Any]] = []
                    seen_versions: set[int] = set()
                    for row in raw_versions:
                        if not isinstance(row, dict):
                            continue
                        version = core._safe_non_negative_int(row.get("version"), default=0)
                        if version < 1 or version in seen_versions:
                            continue
                        seen_versions.add(version)
                        versions.append(
                            {
                                "version": version,
                                "steps": row.get("steps") if isinstance(row.get("steps"), list) else [],
                                "updated_at": normalize_workflow_template_timestamp(row.get("updated_at"))
                                or normalize_workflow_template_timestamp(page.get("updated_at"))
                                or updated_at,
                            }
                        )
                    if current_step_version not in seen_versions:
                        versions.append(
                            {
                                "version": current_step_version,
                                "steps": current_steps,
                                "updated_at": normalize_workflow_template_timestamp(page.get("updated_at")) or updated_at,
                            }
                        )
                    versions.append(
                        {
                            "version": next_step_version,
                            "steps": next_steps,
                            "updated_at": updated_at,
                        }
                    )
                    versions.sort(key=lambda row: int(row.get("version") or 0))
                    if len(versions) > 30:
                        versions = versions[-30:]
                    merged["step_version"] = next_step_version
                    merged["step_versions"] = versions
                else:
                    merged["step_version"] = current_step_version
            if "archived" in updates:
                merged["archived_at"] = workflow_template_timestamp_now() if bool(updates.get("archived")) else ""
            if "lifecycle_state" in updates:
                next_lifecycle_state = str(updates.get("lifecycle_state") or "draft").strip().lower()
                if next_lifecycle_state == "fixed":
                    merged["fixed_at"] = str(page.get("fixed_at") or "").strip() or workflow_template_timestamp_now()
                else:
                    merged["fixed_at"] = ""
            else:
                merged["fixed_at"] = str(page.get("fixed_at") or "").strip() if lifecycle_state == "fixed" else ""
            merged["updated_at"] = updated_at
            existing[index] = merged
            saved = dict(merged)
            updated = True
            break

        if not updated:
            raise HTTPException(status_code=404, detail="Workflow page not found.")

        existing.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
        write_workflow_pages(existing)
        return JSONResponse(
            {"status": "ok", "workflow_page": saved, "count": len(existing), "updated": True},
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/workflow-templates")
    def api_get_workflow_templates(
        search: str | None = Query(default=None),
        sort: str = Query(default="updated_desc"),
        limit: int | None = Query(default=None, ge=1, le=workflow_template_max_items),
        offset: int = Query(default=0, ge=0),
    ) -> JSONResponse:
        if sort not in workflow_template_sort_options:
            raise HTTPException(status_code=400, detail="Invalid sort option.")

        templates = read_workflow_templates()

        query = str(search or "").strip()
        if len(query) > workflow_template_max_search_chars:
            query = query[:workflow_template_max_search_chars]
        if query:
            q = query.lower()
            templates = [
                item
                for item in templates
                if q in str(item.get("name") or "").lower()
                or q in str(item.get("notes") or "").lower()
                or q in str(item.get("mfcloud_url") or "").lower()
            ]

        templates = sort_workflow_templates(templates, sort=sort)
        total_count = len(templates)
        if offset:
            templates = templates[offset:]
        if limit is not None:
            templates = templates[:limit]

        return JSONResponse(
            {
                "status": "ok",
                "templates": templates,
                "count": len(templates),
                "total_count": total_count,
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/api/workflow-templates")
    def api_save_workflow_template(payload: dict[str, Any]) -> JSONResponse:
        payload = payload if isinstance(payload, dict) else {}
        payload = normalize_workflow_template_payload(payload)
        template_id = str(payload.get("id") or "")
        source_template_id = normalize_workflow_template_id(payload.get("source_template_id"))
        template_mode = str(payload.get("template_mode") or "new").strip().lower()
        allow_duplicate_name = bool(payload.get("allow_duplicate_name"))
        base_updated_at = normalize_workflow_template_timestamp(payload.get("base_updated_at"))
        existing = read_workflow_templates()
        source_template: dict[str, Any] | None = None
        if template_mode == "copy":
            source_template = next((row for row in existing if str(row.get("id") or "") == source_template_id), None)
            if source_template is None:
                raise HTTPException(status_code=404, detail="template_source_id not found.")
            source_updated_at = str(source_template.get("updated_at") or "")
            if base_updated_at and source_updated_at and source_updated_at != base_updated_at:
                raise HTTPException(
                    status_code=409,
                    detail="Template was updated by another action. Reload and try again.",
                )

        existing_template_index = next(
            (index for index, row in enumerate(existing) if str(row.get("id") or "") == template_id),
            -1,
        )
        is_update = existing_template_index >= 0 and template_mode != "copy"
        allow_existing_id = template_id if is_update else None
        if not allow_duplicate_name and template_name_taken(
            existing,
            str(payload.get("name") or ""),
            allow_existing_id=allow_existing_id,
        ):
            raise HTTPException(status_code=409, detail="Template name already exists.")

        now = workflow_template_timestamp_now()
        sanitized = dict(payload)
        sanitized.pop("allow_duplicate_name", None)
        sanitized.pop("base_updated_at", None)
        sanitized.pop("template_mode", None)
        if source_template_id:
            sanitized["source_template_id"] = source_template_id

        updated = False
        saved: dict[str, Any]
        if is_update:
            existing_template = existing[existing_template_index]
            existing_updated_at = str(existing_template.get("updated_at") or "")
            if base_updated_at and existing_updated_at and existing_updated_at != base_updated_at:
                raise HTTPException(
                    status_code=409,
                    detail="Template was updated by another action. Reload and try again.",
                )
            sanitized["created_at"] = str(existing_template.get("created_at") or now)
            sanitized["updated_at"] = now
            existing[existing_template_index] = dict(existing_template, **sanitized)
            saved = dict(existing[existing_template_index])
            updated = True
        else:
            created = dict(sanitized)
            created["created_at"] = str(created.get("created_at") or now)
            created["updated_at"] = now
            existing.append(created)
            saved = dict(created)

        existing.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
        write_workflow_templates(existing)

        if not updated and template_mode == "copy" and source_template is not None:
            try:
                core_scheduler.copy_timer_state(str(source_template.get("id") or source_template_id), str(saved.get("id") or ""))
            except Exception:
                pass

        scheduler_sync: dict[str, Any] = {"status": "skipped", "reason": "not_synced"}
        try:
            scheduler_sync = _sync_scheduler_state_for_template(saved)
        except HTTPException as exc:
            scheduler_sync = {
                "status": "error",
                "reason": "scheduler_sync_failed",
                "detail": str(exc.detail),
            }
        except Exception as exc:
            scheduler_sync = {
                "status": "error",
                "reason": "scheduler_sync_failed",
                "detail": str(exc),
            }

        return JSONResponse(
            {
                "status": "ok",
                "template": saved,
                "count": len(existing),
                "updated": updated,
                "scheduler_sync": scheduler_sync,
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.delete("/api/workflow-templates/{template_id}")
    def api_delete_workflow_template(
        template_id: str,
        base_updated_at: str | None = Query(default=None),
    ) -> JSONResponse:
        normalized_template_id = normalize_workflow_template_id(template_id)
        if not normalized_template_id:
            raise HTTPException(status_code=400, detail="Invalid template id.")

        base_updated_at = normalize_workflow_template_timestamp(base_updated_at)

        existing = read_workflow_templates()
        target = None
        target_index = -1
        for index, row in enumerate(existing):
            if str(row.get("id") or "") == normalized_template_id:
                target = row
                target_index = index
                break

        if target is None:
            raise HTTPException(status_code=404, detail="Template not found.")

        target_updated_at = str(target.get("updated_at") or "")
        if base_updated_at and target_updated_at and target_updated_at != base_updated_at:
            raise HTTPException(status_code=409, detail="Template was updated by another action. Reload and try again.")

        existing.pop(target_index)

        for row in existing:
            if str(row.get("source_template_id") or "") == normalized_template_id:
                row["source_template_id"] = ""

        write_workflow_templates(existing)
        core_scheduler.delete_timer_state(normalized_template_id)

        return JSONResponse(
            {"status": "ok", "deleted_template_id": normalized_template_id, "count": len(existing)},
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/scheduler/state")
    def api_get_scheduler_state(template_id: str | None = Query(default=None)) -> JSONResponse:
        state = core_scheduler.get_state(template_id=template_id)
        return JSONResponse({"status": "ok", **state}, headers={"Cache-Control": "no-store"})

    @router.post("/api/scheduler/state")
    def api_set_scheduler_state(
        payload: dict[str, Any] | None = None,
        template_id: str | None = Query(default=None),
    ) -> JSONResponse:
        body = payload if isinstance(payload, dict) else {}
        state = core_scheduler.update_state(body, template_id=template_id)
        return JSONResponse({"status": "ok", **state}, headers={"Cache-Control": "no-store"})

    @router.get("/api/workflow-events/notification-settings")
    def api_workflow_event_notification_settings() -> JSONResponse:
        return JSONResponse(
            _workflow_event_notification_settings_response_payload(),
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/api/workflow-events/notification-settings")
    def api_workflow_event_notification_settings_upsert(
        payload: dict[str, Any] | None = None,
    ) -> JSONResponse:
        body = payload if isinstance(payload, dict) else {}
        if "webhook_url" not in body:
            raise HTTPException(status_code=400, detail="webhook_url is required.")
        raw_webhook = body.get("webhook_url")
        if raw_webhook is None:
            raw_webhook = ""
        if not isinstance(raw_webhook, str):
            raise HTTPException(status_code=400, detail="webhook_url must be a string.")
        webhook_url = str(raw_webhook).strip()
        if webhook_url:
            if not _is_valid_workflow_event_google_chat_webhook_url(webhook_url):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid webhook_url. Use a Google Chat incoming webhook URL.",
                )
            _write_workflow_event_notification_settings_file(webhook_url=webhook_url)
        else:
            _clear_workflow_event_notification_settings_file()
        return JSONResponse(
            _workflow_event_notification_settings_response_payload(),
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/api/workflow-events/notification-settings/test")
    def api_workflow_event_notification_settings_test(request: Request) -> JSONResponse:
        actor = actor_from_request(request)
        now = datetime.now()
        year = int(now.year)
        month = int(now.month)
        action_key = "notification_settings_test"
        event_name = "notification_settings_test"
        source = "admin_center"
        idempotency_key = ""
        attempts = 1
        max_attempts = 1
        settings = _workflow_event_notification_webhook_status()
        webhook_url = str(settings.get("webhook_url") or "").strip()
        if not webhook_url:
            _append_workflow_event_notification_audit(
                year=year,
                month=month,
                action_key=action_key,
                status="skipped",
                actor=actor,
                template_id="",
                template_name="",
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                channel="google_chat",
                attempts=attempts,
                max_attempts=max_attempts,
                reason="google chat webhook is not configured",
                reason_code="webhook_not_configured",
            )
            return JSONResponse(
                {
                    "status": "error",
                    "sent": False,
                    "http_status": 0,
                    "message": "Google Chat webhook is not configured.",
                },
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )

        text = "\n".join(
            [
                "[Workflow Notification Test]",
                "source: /errors notification-settings",
                f"at: {workflow_template_timestamp_now()}",
                "",
                "This is a connection test from expense workflow dashboard.",
            ]
        )
        result = _workflow_event_google_chat_send(text, webhook_url=webhook_url)
        sent = bool(result.get("sent"))
        http_status = core._safe_non_negative_int(result.get("http_status"), default=0)
        reason = str(result.get("reason") or "").strip()
        reason_code = str(result.get("reason_code") or "").strip().lower()
        if sent:
            _append_workflow_event_notification_audit(
                year=year,
                month=month,
                action_key=action_key,
                status="success",
                actor=actor,
                template_id="",
                template_name="",
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                channel="google_chat",
                attempts=attempts,
                max_attempts=max_attempts,
                reason="sent",
                reason_code="sent",
            )
            return JSONResponse(
                {
                    "status": "ok",
                    "sent": True,
                    "http_status": http_status or 200,
                    "message": "Test notification sent.",
                },
                headers={"Cache-Control": "no-store"},
            )

        if reason_code == "webhook_not_configured":
            status_code = 400
            message = "Google Chat webhook is not configured."
        elif http_status >= 400:
            status_code = http_status
            message = reason or f"Google Chat returned HTTP {http_status}."
        else:
            status_code = 502
            message = reason or "Failed to send notification to Google Chat."

        _append_workflow_event_notification_audit(
            year=year,
            month=month,
            action_key=action_key,
            status="failed",
            actor=actor,
            template_id="",
            template_name="",
            event_name=event_name,
            source=source,
            idempotency_key=idempotency_key,
            channel="google_chat",
            attempts=attempts,
            max_attempts=max_attempts,
            reason=message,
            reason_code=reason_code or "send_failed",
        )
        return JSONResponse(
            {
                "status": "error",
                "sent": False,
                "http_status": http_status,
                "message": message,
            },
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/workflow-events/summary")
    def api_workflow_events_summary(
        ym: str = Query(...),
        recent_limit: int = Query(default=20, ge=1, le=200),
    ) -> JSONResponse:
        normalized_ym = core._safe_ym(ym)
        audit_path = core._artifact_root() / normalized_ym / "reports" / "audit_log.jsonl"
        raw_rows = core._read_jsonl(audit_path) if audit_path.exists() else []
        rows = raw_rows if isinstance(raw_rows, list) else []
        summary = _summarize_workflow_event_audit_rows(rows, recent_limit=recent_limit)
        notification = _summarize_workflow_event_notification_rows(rows, recent_limit=recent_limit)
        retry_queue = _workflow_event_retry_queue_snapshot(limit=5)
        return JSONResponse(
            {
                "status": "ok",
                "ym": normalized_ym,
                "receipt_retention": {
                    "ttl_days": _workflow_event_receipt_ttl_days(),
                    "max_receipts": _workflow_event_max_receipts(),
                },
                "retry_queue": {
                    "total": int(retry_queue.get("total") or 0),
                    "due": int(retry_queue.get("due") or 0),
                    "by_status": retry_queue.get("by_status") if isinstance(retry_queue.get("by_status"), list) else [],
                    "policy": retry_queue.get("policy") if isinstance(retry_queue.get("policy"), dict) else {},
                },
                "notification": notification,
                **summary,
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/workflow-events/retry-jobs")
    def api_workflow_event_retry_jobs(
        limit: int = Query(default=20, ge=1, le=200),
    ) -> JSONResponse:
        snapshot = _workflow_event_retry_queue_snapshot(limit=limit)
        return JSONResponse(
            {
                "status": "ok",
                **snapshot,
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/api/workflow-events/retry-jobs/drain")
    def api_workflow_event_retry_jobs_drain(
        payload: dict[str, Any] | None = None,
    ) -> JSONResponse:
        body = payload if isinstance(payload, dict) else {}
        limit = core._safe_non_negative_int(body.get("limit"), default=10)
        if limit < 1:
            limit = 1
        if limit > 50:
            limit = 50
        force = bool(body.get("force"))
        now = datetime.now()
        now_iso = now.isoformat(timespec="seconds")
        retry_actor = {"type": "system", "id": "workflow_event_retry"}

        state = _read_workflow_event_retry_jobs()
        jobs = state.get("jobs")
        if not isinstance(jobs, dict):
            jobs = {}

        templates = read_workflow_templates()
        templates_by_id = {
            str(row.get("id") or ""): row
            for row in templates
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }

        candidate_keys = sorted(
            jobs.keys(),
            key=lambda key: (
                str((jobs.get(key) or {}).get("next_retry_at") or ""),
                str((jobs.get(key) or {}).get("updated_at") or ""),
                key,
            ),
        )

        processed = 0
        succeeded = 0
        retrying = 0
        escalated = 0
        discarded = 0

        for key in candidate_keys:
            if processed >= limit:
                break
            job = jobs.get(key)
            if not isinstance(job, dict):
                continue
            status = str(job.get("status") or "").strip().lower()
            if status not in WORKFLOW_EVENT_RETRY_ACTIVE_STATUSES:
                continue
            if not _workflow_event_retry_due(job, now, force=force):
                continue

            processed += 1
            template_id = normalize_workflow_template_id(job.get("template_id"))
            template_name = str(job.get("template_name") or "").strip()
            action_key = _normalize_step_action(job.get("action_key"))
            event_name = str(job.get("event_name") or "").strip()[:WORKFLOW_EVENT_MAX_EVENT_NAME_CHARS]
            source = str(job.get("source") or "retry_queue").strip()[:WORKFLOW_EVENT_MAX_SOURCE_CHARS]
            idempotency_key = _normalize_workflow_event_idempotency_key(job.get("idempotency_key"))
            year = core._safe_non_negative_int(job.get("year"), default=0)
            month = core._safe_non_negative_int(job.get("month"), default=0)
            mfcloud_url = str(job.get("mfcloud_url") or "").strip()
            notes = str(job.get("notes") or "").strip()
            max_attempts = core._safe_non_negative_int(job.get("max_attempts"), default=_workflow_event_retry_max_attempts())
            if max_attempts < 1:
                max_attempts = _workflow_event_retry_max_attempts()
            attempts = core._safe_non_negative_int(job.get("attempts"), default=0) + 1

            def _update_job_failure(
                *,
                next_status: str,
                reason: str,
                reason_class: str,
                reason_code: str,
                retry_advice: str,
                next_retry_at: str = "",
                last_run_id: str = "",
            ) -> None:
                job["status"] = next_status
                job["attempts"] = attempts
                job["max_attempts"] = max_attempts
                job["last_error"] = str(reason or "").strip()[:500]
                job["last_reason_class"] = str(reason_class or "").strip().lower()[:64]
                job["last_reason_code"] = str(reason_code or "").strip().lower()[:64]
                job["last_retry_advice"] = str(retry_advice or "").strip().lower()[:64]
                job["last_run_id"] = str(last_run_id or "").strip()[:128]
                job["next_retry_at"] = str(next_retry_at or "").strip()
                job["updated_at"] = now_iso

            template = templates_by_id.get(template_id)
            if not isinstance(template, dict):
                reason = "Workflow template not found."
                _update_job_failure(
                    next_status="discarded",
                    reason=reason,
                    reason_class="template_not_found",
                    reason_code="template_not_found",
                    retry_advice="retry_after_fix",
                )
                _append_workflow_event_audit(
                    year=year,
                    month=month,
                    action_key=action_key,
                    status="rejected",
                    actor=retry_actor,
                    template_id=template_id,
                    template_name=template_name,
                    event_name=event_name,
                    source=f"{source}:retry",
                    idempotency_key=idempotency_key,
                    reason=reason,
                    reason_class="template_not_found",
                    reason_code="template_not_found",
                    retry_advice="retry_after_fix",
                )
                discarded += 1
                continue

            first_step = _first_workflow_template_step(template)
            trigger_kind = _normalize_step_trigger_kind(first_step.get("trigger_kind"))
            current_action_key = _normalize_step_action(first_step.get("action"))
            if trigger_kind != "external_event" or (current_action_key and action_key and current_action_key != action_key):
                reason = "Template external_event settings changed. Retry job discarded."
                _update_job_failure(
                    next_status="discarded",
                    reason=reason,
                    reason_class="template_conflict",
                    reason_code="template_conflict",
                    retry_advice="retry_after_fix",
                )
                _append_workflow_event_audit(
                    year=year,
                    month=month,
                    action_key=action_key,
                    status="rejected",
                    actor=retry_actor,
                    template_id=template_id,
                    template_name=template_name or str(template.get("name") or "").strip(),
                    event_name=event_name,
                    source=f"{source}:retry",
                    idempotency_key=idempotency_key,
                    reason=reason,
                    reason_class="template_conflict",
                    reason_code="template_conflict",
                    retry_advice="retry_after_fix",
                )
                discarded += 1
                continue

            run_payload: dict[str, Any] = {
                "year": year,
                "month": month,
                "mode": action_key,
                "mfcloud_url": mfcloud_url or str(template.get("mfcloud_url") or "").strip(),
                "notes": notes or str(template.get("notes") or "").strip(),
                "auth_handoff": False,
                "auto_receipt_name": True,
                "_audit_actor": retry_actor,
            }
            if action_key == "mf_reconcile":
                run_payload["mf_draft_create"] = True

            try:
                run_result = core._start_run(run_payload)
            except HTTPException as exc:
                detail = str(exc.detail)
                http_status = int(exc.status_code)
                event_status = _workflow_event_status_for_http(http_status)
                reason_class = _workflow_event_error_class(http_status, detail)
                reason_code = f"http_{http_status}"
                retry_advice = _workflow_event_retry_advice(status=event_status, reason_class=reason_class)

                if retry_advice == "retry_with_backoff" and attempts < max_attempts:
                    delay = _workflow_event_retry_backoff_seconds(attempts)
                    next_retry_at = (now + timedelta(seconds=delay)).isoformat(timespec="seconds")
                    _update_job_failure(
                        next_status="retrying",
                        reason=detail,
                        reason_class=reason_class,
                        reason_code=reason_code,
                        retry_advice=retry_advice,
                        next_retry_at=next_retry_at,
                    )
                    retrying += 1
                elif retry_advice == "retry_with_backoff":
                    exhausted_reason = f"retry_exhausted after {attempts} attempts: {detail}"
                    _update_job_failure(
                        next_status="escalated",
                        reason=exhausted_reason,
                        reason_class=reason_class or "infra",
                        reason_code="retry_exhausted",
                        retry_advice="retry_after_fix",
                    )
                    escalated += 1
                    _notify_workflow_event_retry_escalated(
                        actor=retry_actor,
                        year=year,
                        month=month,
                        template_id=template_id,
                        template_name=template_name or str(template.get("name") or "").strip(),
                        action_key=action_key,
                        event_name=event_name,
                        source=f"{source}:retry",
                        idempotency_key=idempotency_key,
                        attempts=attempts,
                        max_attempts=max_attempts,
                        reason_class=str(job.get("last_reason_class") or reason_class or "infra"),
                        reason_code=str(job.get("last_reason_code") or "retry_exhausted"),
                        reason=str(job.get("last_error") or exhausted_reason),
                        at=now_iso,
                    )
                else:
                    _update_job_failure(
                        next_status="discarded",
                        reason=detail,
                        reason_class=reason_class,
                        reason_code=reason_code,
                        retry_advice=retry_advice,
                    )
                    discarded += 1

                _append_workflow_event_audit(
                    year=year,
                    month=month,
                    action_key=action_key,
                    status="failed" if str(job.get("status") or "") == "escalated" else event_status,
                    actor=retry_actor,
                    template_id=template_id,
                    template_name=template_name or str(template.get("name") or "").strip(),
                    event_name=event_name,
                    source=f"{source}:retry",
                    idempotency_key=idempotency_key,
                    reason=str(job.get("last_error") or detail),
                    reason_class=str(job.get("last_reason_class") or reason_class),
                    reason_code=str(job.get("last_reason_code") or reason_code),
                    retry_advice=str(job.get("last_retry_advice") or retry_advice),
                )
                continue
            except Exception as exc:
                detail = str(exc)
                reason_class = "infra"
                reason_code = "exception"
                retry_advice = "retry_with_backoff"
                if attempts < max_attempts:
                    delay = _workflow_event_retry_backoff_seconds(attempts)
                    next_retry_at = (now + timedelta(seconds=delay)).isoformat(timespec="seconds")
                    _update_job_failure(
                        next_status="retrying",
                        reason=detail,
                        reason_class=reason_class,
                        reason_code=reason_code,
                        retry_advice=retry_advice,
                        next_retry_at=next_retry_at,
                    )
                    retrying += 1
                else:
                    exhausted_reason = f"retry_exhausted after {attempts} attempts: {detail}"
                    _update_job_failure(
                        next_status="escalated",
                        reason=exhausted_reason,
                        reason_class=reason_class,
                        reason_code="retry_exhausted",
                        retry_advice="retry_after_fix",
                    )
                    escalated += 1
                    _notify_workflow_event_retry_escalated(
                        actor=retry_actor,
                        year=year,
                        month=month,
                        template_id=template_id,
                        template_name=template_name or str(template.get("name") or "").strip(),
                        action_key=action_key,
                        event_name=event_name,
                        source=f"{source}:retry",
                        idempotency_key=idempotency_key,
                        attempts=attempts,
                        max_attempts=max_attempts,
                        reason_class=str(job.get("last_reason_class") or reason_class),
                        reason_code=str(job.get("last_reason_code") or "retry_exhausted"),
                        reason=str(job.get("last_error") or exhausted_reason),
                        at=now_iso,
                    )

                _append_workflow_event_audit(
                    year=year,
                    month=month,
                    action_key=action_key,
                    status="failed",
                    actor=retry_actor,
                    template_id=template_id,
                    template_name=template_name or str(template.get("name") or "").strip(),
                    event_name=event_name,
                    source=f"{source}:retry",
                    idempotency_key=idempotency_key,
                    reason=str(job.get("last_error") or detail),
                    reason_class=str(job.get("last_reason_class") or reason_class),
                    reason_code=str(job.get("last_reason_code") or reason_code),
                    retry_advice=str(job.get("last_retry_advice") or "retry_with_backoff"),
                )
                continue

            run_id = str(run_result.get("run_id") or "").strip()
            _save_workflow_event_receipt(
                template_id=template_id,
                template_name=template_name or str(template.get("name") or "").strip(),
                action_key=action_key,
                event_name=event_name,
                source=f"{source}:retry",
                idempotency_key=idempotency_key,
                run_id=run_id,
            )
            job["status"] = "succeeded"
            job["attempts"] = attempts
            job["max_attempts"] = max_attempts
            job["next_retry_at"] = ""
            job["last_error"] = ""
            job["last_reason_class"] = ""
            job["last_reason_code"] = ""
            job["last_retry_advice"] = ""
            job["last_run_id"] = run_id[:128]
            job["updated_at"] = now_iso

            _append_workflow_event_audit(
                year=year,
                month=month,
                action_key=action_key,
                status="success",
                actor=retry_actor,
                template_id=template_id,
                template_name=template_name or str(template.get("name") or "").strip(),
                event_name=event_name,
                source=f"{source}:retry",
                idempotency_key=idempotency_key,
                run_id=run_id,
                duplicate=False,
            )
            succeeded += 1

        cleaned, _ = _clean_workflow_event_retry_jobs(jobs)
        state["jobs"] = cleaned
        _write_workflow_event_retry_jobs(state)

        remaining_due = 0
        now_after = datetime.now()
        for value in cleaned.values():
            if not isinstance(value, dict):
                continue
            if str(value.get("status") or "").strip().lower() not in WORKFLOW_EVENT_RETRY_ACTIVE_STATUSES:
                continue
            if _workflow_event_retry_due(value, now_after, force=force):
                remaining_due += 1

        snapshot = _workflow_event_retry_queue_snapshot(limit=20)
        return JSONResponse(
            {
                "status": "ok",
                "processed": processed,
                "succeeded": succeeded,
                "retrying": retrying,
                "escalated": escalated,
                "discarded": discarded,
                "remaining_due": remaining_due,
                "queue": snapshot,
            },
            headers={"Cache-Control": "no-store"},
        )

    def _drain_workflow_event_retry_jobs_for_worker() -> None:
        api_workflow_event_retry_jobs_drain({"limit": 10, "force": False})

    set_workflow_event_retry_drain_callback(_drain_workflow_event_retry_jobs_for_worker)

    @router.post("/api/workflow-events")
    def api_workflow_events(
        request: Request,
        payload: dict[str, Any] | None = None,
        token: str | None = Query(default=None),
    ) -> JSONResponse:
        body = payload if isinstance(payload, dict) else {}
        req = request
        actor = actor_from_request(req)
        idempotency_key = _resolve_workflow_event_idempotency_key(req, body)
        action_key = ""
        template_id = normalize_workflow_template_id(body.get("template_id") or body.get("templateId"))
        template_name = ""
        event_name = (
            str(body.get("event_name") or body.get("eventName") or "").strip()[:WORKFLOW_EVENT_MAX_EVENT_NAME_CHARS]
        )
        source = str(body.get("source") or body.get("event_source") or "webhook").strip()[:WORKFLOW_EVENT_MAX_SOURCE_CHARS]
        year = core._safe_non_negative_int(body.get("year"), default=0)
        month = core._safe_non_negative_int(body.get("month"), default=0)
        if year < 2000 or month < 1 or month > 12:
            year = None
            month = None

        try:
            _validate_workflow_event_token(req, token=token)
        except HTTPException as exc:
            _append_workflow_event_audit(
                year=year,
                month=month,
                action_key=action_key,
                status=_workflow_event_status_for_http(exc.status_code),
                actor=actor,
                template_id=template_id,
                template_name=template_name,
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                reason=str(exc.detail),
                reason_class=_workflow_event_error_class(exc.status_code, str(exc.detail)),
                reason_code=f"http_{exc.status_code}",
            )
            raise

        templates = read_workflow_templates()
        try:
            template, first_step = _resolve_external_event_template(body, templates)
        except HTTPException as exc:
            _append_workflow_event_audit(
                year=year,
                month=month,
                action_key=action_key,
                status=_workflow_event_status_for_http(exc.status_code),
                actor=actor,
                template_id=template_id,
                template_name=template_name,
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                reason=str(exc.detail),
                reason_class=_workflow_event_error_class(exc.status_code, str(exc.detail)),
                reason_code=f"http_{exc.status_code}",
            )
            raise

        template_id = normalize_workflow_template_id(template.get("id"))
        if not template_id:
            raise HTTPException(status_code=400, detail="Resolved template id is invalid.")
        template_name = str(template.get("name") or "").strip()
        action_key = _normalize_step_action(first_step.get("action"))
        if not event_name:
            event_name = action_key[:WORKFLOW_EVENT_MAX_EVENT_NAME_CHARS]

        if year is None or month is None:
            fallback_year = core._safe_non_negative_int(template.get("year"), default=0)
            fallback_month = core._safe_non_negative_int(template.get("month"), default=0)
            if 2000 <= fallback_year and 1 <= fallback_month <= 12:
                year = fallback_year
                month = fallback_month

        allowed_action_keys = _allowed_scheduler_action_keys()
        if action_key not in allowed_action_keys:
            detail = f"external_event action is not executable in MVP: {action_key or '(empty)'}"
            _append_workflow_event_audit(
                year=year,
                month=month,
                action_key=action_key,
                status="rejected",
                actor=actor,
                template_id=template_id,
                template_name=template_name,
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                reason=detail,
                reason_class="unsupported_action",
                reason_code="unsupported_action",
            )
            raise HTTPException(status_code=409, detail=detail)

        duplicate = _lookup_workflow_event_receipt(template_id, idempotency_key) if idempotency_key else None
        if duplicate:
            run_id = str(duplicate.get("run_id") or "")
            _mark_workflow_event_retry_job_succeeded(
                template_id=template_id,
                idempotency_key=idempotency_key,
                run_id=run_id,
            )
            _append_workflow_event_audit(
                year=year,
                month=month,
                action_key=action_key,
                status="skipped",
                actor=actor,
                template_id=template_id,
                template_name=template_name,
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                run_id=run_id,
                reason="duplicate_event",
                reason_class="duplicate",
                reason_code="duplicate_idempotency_key",
                duplicate=True,
            )
            return JSONResponse(
                {
                    "status": "ok",
                    "duplicate": True,
                    "triggered": False,
                    "template_id": template_id,
                    "template_name": template_name,
                    "action_key": action_key,
                    "idempotency_key": idempotency_key,
                    "run_id": run_id,
                },
                headers={"Cache-Control": "no-store"},
            )

        if year is None or month is None or year < 2000 or month < 1 or month > 12:
            detail = "Workflow event requires valid year/month."
            _append_workflow_event_audit(
                year=year,
                month=month,
                action_key=action_key,
                status="rejected",
                actor=actor,
                template_id=template_id,
                template_name=template_name,
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                reason=detail,
                reason_class="validation",
                reason_code="invalid_year_month",
            )
            raise HTTPException(status_code=400, detail=detail)

        mfcloud_url = str(body.get("mfcloud_url") or template.get("mfcloud_url") or "").strip()
        notes = str(body.get("notes") or template.get("notes") or "").strip()

        run_payload: dict[str, Any] = {
            "year": year,
            "month": month,
            "mode": action_key,
            "mfcloud_url": mfcloud_url,
            "notes": notes,
            "auth_handoff": False,
            "auto_receipt_name": True,
            "_audit_actor": actor,
        }
        if action_key == "mf_reconcile":
            run_payload["mf_draft_create"] = True

        try:
            run_result = core._start_run(run_payload)
        except HTTPException as exc:
            status = _workflow_event_status_for_http(exc.status_code)
            reason = str(exc.detail)
            reason_class = _workflow_event_error_class(exc.status_code, reason)
            reason_code = f"http_{exc.status_code}"
            _append_workflow_event_audit(
                year=year,
                month=month,
                action_key=action_key,
                status=status,
                actor=actor,
                template_id=template_id,
                template_name=template_name,
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                reason=reason,
                reason_class=reason_class,
                reason_code=reason_code,
            )
            _maybe_enqueue_workflow_event_retry(
                template_id=template_id,
                template_name=template_name,
                action_key=action_key,
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                year=year,
                month=month,
                mfcloud_url=mfcloud_url,
                notes=notes,
                status=status,
                reason=reason,
                reason_class=reason_class,
                reason_code=reason_code,
            )
            raise
        except Exception as exc:
            reason = str(exc)
            _append_workflow_event_audit(
                year=year,
                month=month,
                action_key=action_key,
                status="failed",
                actor=actor,
                template_id=template_id,
                template_name=template_name,
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                reason=reason,
                reason_class="infra",
                reason_code="exception",
            )
            _maybe_enqueue_workflow_event_retry(
                template_id=template_id,
                template_name=template_name,
                action_key=action_key,
                event_name=event_name,
                source=source,
                idempotency_key=idempotency_key,
                year=year,
                month=month,
                mfcloud_url=mfcloud_url,
                notes=notes,
                status="failed",
                reason=reason,
                reason_class="infra",
                reason_code="exception",
            )
            raise

        run_id = str(run_result.get("run_id") or "")
        _save_workflow_event_receipt(
            template_id=template_id,
            template_name=template_name,
            action_key=action_key,
            event_name=event_name,
            source=source,
            idempotency_key=idempotency_key,
            run_id=run_id,
        )
        _mark_workflow_event_retry_job_succeeded(
            template_id=template_id,
            idempotency_key=idempotency_key,
            run_id=run_id,
        )
        _append_workflow_event_audit(
            year=year,
            month=month,
            action_key=action_key,
            status="success",
            actor=actor,
            template_id=template_id,
            template_name=template_name,
            event_name=event_name,
            source=source,
            idempotency_key=idempotency_key,
            run_id=run_id,
            duplicate=False,
        )
        return JSONResponse(
            {
                "status": "ok",
                "duplicate": False,
                "triggered": True,
                "template_id": template_id,
                "template_name": template_name,
                "action_key": action_key,
                "idempotency_key": idempotency_key,
                "run_id": run_id,
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/api/print-pdf/{ym}/{source}/{filename}")
    def api_print_pdf(ym: str, source: str, filename: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=404, detail="PDF not found.")
        if not filename or not core.SAFE_NAME_RE.match(filename) or not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=404, detail="PDF not found.")
        root = core._artifact_root() / ym
        path = core._resolve_pdf_path(root, source, filename)
        if not path:
            raise HTTPException(status_code=404, detail="PDF not found.")
        pdf_url = f"/files/{ym}/pdf/{source}/{path.name}"
        year, month = core._split_ym(ym)
        core._append_audit_event(
            year=year,
            month=month,
            event_type="source_action",
            action="print_single_pdf",
            status="success",
            actor=actor_from_request(request),
            source=source,
            details={"file": str(path.name), "mode": "manual_open"},
        )
        return JSONResponse(
            {
                "status": "ok",
                "file": str(path.name),
                "pdf_url": pdf_url,
                "print_mode": "manual_open",
            }
        )




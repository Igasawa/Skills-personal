from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Any, Callable

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
WORKFLOW_EVENT_MAX_EVENT_NAME_CHARS = 80
WORKFLOW_EVENT_MAX_SOURCE_CHARS = 80

_GOAL_INLINE_PATTERN = re.compile(r"^(?:目的|goal|ゴール|やりたいこと|狙い|task)\s*[:：]\s*(.+)$", flags=re.IGNORECASE)
_GOAL_HEADING_PATTERN = re.compile(r"^(?:目的|goal|ゴール|やりたいこと|狙い|task)\s*[:：]?$", flags=re.IGNORECASE)
_GOAL_LEADING_MARKERS_PATTERN = re.compile(r"^[\s\-*・\d\.\)\(]+")
_PROTECTED_TOKEN_PATTERN = re.compile(
    r"\{\{[^{}\n]+\}\}|\$\{[^{}\n]+\}|\$[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\}|<[^<>\n]+>"
)
_WORKFLOW_EVENT_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")


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
            "あなたは「エージェント向けプロンプト最適化アシスタント」です。",
            "最優先は、元文の忠実再現ではなく、目的達成率の最大化です。",
            "優先順位:",
            "1) 目的達成",
            "2) 明示制約・禁止事項の遵守",
            "3) 実行可能性（曖昧さ解消、手順化、出力形式の明確化）",
            "4) 可読性",
            "許可: 再構成、要約、追記、削除、順序入れ替え。",
            "必須: 変数・プレースホルダ・識別子（{{...}}, ${...}, $VAR, {token}, <...>）は原則保持。",
            "出力はJSONのみ。Markdownは禁止。",
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
        messages.append(f"保護トークンの欠落を検出: {', '.join(sorted(set(missing))[:8])}")
    if added:
        messages.append(f"保護トークンの追加を検出: {', '.join(sorted(set(added))[:8])}")
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

    def _workflow_event_receipts_path():
        return core._artifact_root() / "_workflow_events" / "receipts.json"

    def _read_workflow_event_receipts() -> dict[str, dict[str, Any]]:
        raw = core._read_json(_workflow_event_receipts_path())
        receipts = raw.get("receipts") if isinstance(raw, dict) else {}
        if not isinstance(receipts, dict):
            return {"receipts": {}}
        normalized: dict[str, dict[str, Any]] = {}
        for key, value in receipts.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(value, dict):
                continue
            normalized[key.strip()] = dict(value)
        return {"receipts": normalized}

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
        if len(receipts) > WORKFLOW_EVENT_MAX_RECEIPTS:
            keys_sorted = sorted(receipts.keys(), key=lambda item: str(receipts[item].get("created_at") or ""))
            drop_count = max(0, len(receipts) - WORKFLOW_EVENT_MAX_RECEIPTS)
            for stale_key in keys_sorted[:drop_count]:
                receipts.pop(stale_key, None)
        state["receipts"] = receipts
        _write_workflow_event_receipts(state)

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
            first_label = str(first_server_group.get("label") or "").strip() or "固定リンク1"
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
        goal = goal_from_client or str(goal_hint.get("goal") or "").strip() or "対象タスクを完遂できるように最適化する"
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
            raise HTTPException(status_code=502, detail="AI response format is invalid. Expected JSON object.")

        try:
            normalized = _normalize_prompt_optimize_response(parsed)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

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
        page_id = str(page.get("id") or "").strip()
        source_template_id = normalize_workflow_template_id(page.get("source_template_id"))
        existing = read_workflow_pages(include_archived=True)
        if workflow_page_name_taken(existing, str(page.get("name") or "")):
            raise HTTPException(status_code=409, detail="Workflow page name already exists.")
        if len(existing) >= workflow_page_max_items:
            raise HTTPException(status_code=409, detail="Workflow page limit reached. Remove one and create again.")
        existing.append(page)
        existing.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
        write_workflow_pages(existing)
        scheduler_copied = False
        if page_id and source_template_id:
            try:
                core_scheduler.copy_timer_state(source_template_id, page_id)
                scheduler_copied = True
            except Exception:
                scheduler_copied = False
        return JSONResponse(
            {"status": "ok", "workflow_page": page, "count": len(existing), "scheduler_copied": scheduler_copied},
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

    @router.post("/api/workflow-events")
    def api_workflow_events(
        request: Request,
        payload: dict[str, Any] | None = None,
        token: str | None = Query(default=None),
    ) -> JSONResponse:
        body = payload if isinstance(payload, dict) else {}
        req = request
        _validate_workflow_event_token(req, token=token)

        templates = read_workflow_templates()
        template, first_step = _resolve_external_event_template(body, templates)
        template_id = normalize_workflow_template_id(template.get("id"))
        if not template_id:
            raise HTTPException(status_code=400, detail="Resolved template id is invalid.")

        action_key = _normalize_step_action(first_step.get("action"))
        allowed_action_keys = _allowed_scheduler_action_keys()
        if action_key not in allowed_action_keys:
            raise HTTPException(
                status_code=409,
                detail=f"external_event action is not executable in MVP: {action_key or '(empty)'}",
            )

        idempotency_key = _resolve_workflow_event_idempotency_key(req, body)
        duplicate = _lookup_workflow_event_receipt(template_id, idempotency_key) if idempotency_key else None
        if duplicate:
            return JSONResponse(
                {
                    "status": "ok",
                    "duplicate": True,
                    "triggered": False,
                    "template_id": template_id,
                    "template_name": str(template.get("name") or "").strip(),
                    "action_key": action_key,
                    "idempotency_key": idempotency_key,
                    "run_id": str(duplicate.get("run_id") or ""),
                },
                headers={"Cache-Control": "no-store"},
            )

        year = core._safe_non_negative_int(body.get("year"), default=0)
        month = core._safe_non_negative_int(body.get("month"), default=0)
        if year <= 0:
            year = core._safe_non_negative_int(template.get("year"), default=0)
        if month <= 0:
            month = core._safe_non_negative_int(template.get("month"), default=0)
        if year < 2000 or month < 1 or month > 12:
            raise HTTPException(status_code=400, detail="Workflow event requires valid year/month.")

        template_name = str(template.get("name") or "").strip()
        event_name = (
            str(body.get("event_name") or body.get("eventName") or action_key).strip()[:WORKFLOW_EVENT_MAX_EVENT_NAME_CHARS]
        )
        source = str(body.get("source") or body.get("event_source") or "webhook").strip()[:WORKFLOW_EVENT_MAX_SOURCE_CHARS]
        mfcloud_url = str(body.get("mfcloud_url") or template.get("mfcloud_url") or "").strip()
        notes = str(body.get("notes") or template.get("notes") or "").strip()
        actor = actor_from_request(req)

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
            core._append_audit_event(
                year=year,
                month=month,
                event_type="workflow_event",
                action=action_key or "unknown",
                status="rejected" if exc.status_code in {400, 404, 409} else "failed",
                actor=actor,
                details={
                    "reason": str(exc.detail),
                    "template_id": template_id,
                    "template_name": template_name,
                    "event_name": event_name,
                    "source": source,
                    "idempotency_key": idempotency_key,
                },
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
        core._append_audit_event(
            year=year,
            month=month,
            event_type="workflow_event",
            action=action_key,
            status="success",
            actor=actor,
            mode=action_key,
            run_id=run_id,
            details={
                "template_id": template_id,
                "template_name": template_name,
                "event_name": event_name,
                "source": source,
                "idempotency_key": idempotency_key,
            },
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


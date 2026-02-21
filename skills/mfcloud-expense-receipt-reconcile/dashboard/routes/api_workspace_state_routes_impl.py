from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse


def register_api_workspace_state_routes(
    *,
    router: APIRouter,
    core: Any,
    ai_chat: Any,
    read_workspace_state: Callable[[], dict[str, Any]],
    write_workspace_state: Callable[..., dict[str, Any]],
    sanitize_workspace_links: Callable[[Any], list[dict[str, str]]],
    merge_workspace_links: Callable[[list[dict[str, str]], list[dict[str, str]]], list[dict[str, str]]],
    sanitize_workspace_pinned_links: Callable[[Any], list[dict[str, str]]],
    merge_workspace_pinned_link_groups: Callable[[list[dict[str, Any]], list[dict[str, Any]]], list[dict[str, Any]]],
    sanitize_workspace_pinned_link_groups: Callable[[Any], list[dict[str, Any]]],
    sanitize_workspace_prompts: Callable[[Any], dict[str, str]],
    merge_workspace_prompts: Callable[[dict[str, str], dict[str, str]], dict[str, str]],
    sanitize_workspace_link_notes: Callable[[Any], dict[str, str]],
    merge_workspace_link_notes: Callable[[dict[str, str], dict[str, str]], dict[str, str]],
    sanitize_workspace_link_profiles: Callable[[Any], dict[str, dict[str, str]]],
    merge_workspace_link_profiles: Callable[[dict[str, dict[str, str]], dict[str, dict[str, str]]], dict[str, dict[str, str]]],
    sanitize_workspace_active_prompt_key: Callable[[Any], str],
    WORKSPACE_PROMPT_OPTIMIZE_MAX_TEXT_CHARS: int,
    WORKSPACE_PROMPT_OPTIMIZE_MAX_LIST_ITEMS: int,
    clean_goal_candidate: Callable[[Any], str],
    extract_goal_hint: Callable[[str], dict[str, Any]],
    normalize_prompt_optimize_locale: Callable[[Any], str],
    normalize_prompt_optimize_style: Callable[[Any], str],
    build_goal_first_optimize_prompt: Callable[..., str],
    try_parse_json_object: Callable[[str], dict[str, Any] | None],
    normalize_prompt_optimize_response: Callable[[Any], dict[str, Any]],
    enforce_prompt_optimize_rules: Callable[[str, str, str], str],
    build_token_integrity_warnings: Callable[[str, str], list[str]],
    **_unused: Any,
) -> None:
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
            first_label = str(first_server_group.get("label") or "").strip() or "\u56fa\u5b9a\u30ea\u30f3\u30af\u0031"
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
            current["pinned_links"] = sanitize_workspace_pinned_links(pinned_groups[0].get("links") if pinned_groups else [])
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

        goal_from_client = clean_goal_candidate(body.get("goal"))
        goal_hint = extract_goal_hint(text)
        goal = goal_from_client or str(goal_hint.get("goal") or "").strip() or "\u5bfe\u8c61\u30bf\u30b9\u30af\u3092\u5b8c\u9042\u3067\u304d\u308b\u3088\u3046\u306b\u6700\u9069\u5316\u3059\u308b"
        locale = normalize_prompt_optimize_locale(body.get("locale"))
        style_preset = normalize_prompt_optimize_style(body.get("stylePreset"))

        optimize_message = build_goal_first_optimize_prompt(
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
        parsed = try_parse_json_object(reply_text)
        if not isinstance(parsed, dict):
            parsed = {
                "optimizedPrompt": enforce_prompt_optimize_rules(
                    original_text=text,
                    optimized_text=text,
                    locale=locale,
                ),
                "changes": [
                    "\u0041\u0049\u306eJSON\u5fdc\u7b54\u3092\u89e3\u6790\u3067\u304d\u306a\u304b\u3063\u305f\u305f\u3081\u3001\u30eb\u30fc\u30eb\u30d9\u30fc\u30b9\u6700\u9069\u5316\u306b\u30d5\u30a9\u30fc\u30eb\u30d0\u30c3\u30af\u3057\u307e\u3057\u305f\u3002",
                ],
                "assumptions": [],
                "risks": [],
                "needsConfirmation": [
                    "\u0041\u0049\u6700\u9069\u5316\u306e\u5fdc\u7b54\u5f62\u5f0f\u304c\u4e0d\u6b63\u3060\u3063\u305f\u305f\u3081\u3001\u30eb\u30fc\u30eb\u30d9\u30fc\u30b9\u6700\u9069\u5316\u3092\u9069\u7528\u3057\u307e\u3057\u305f\u3002",
                ],
            }

        try:
            normalized = normalize_prompt_optimize_response(parsed)
        except ValueError as exc:
            normalized = {
                "optimizedPrompt": enforce_prompt_optimize_rules(
                    original_text=text,
                    optimized_text=text,
                    locale=locale,
                ),
                "changes": [
                    "\u0041\u0049\u6700\u9069\u5316\u30d5\u30a9\u30fc\u30de\u30c3\u30c8\u30a8\u30e9\u30fc: {str(exc)}",
                ],
                "assumptions": [],
                "risks": [],
                "needsConfirmation": [f"\u0041\u0049\u6700\u9069\u5316\u30d5\u30a9\u30fc\u30de\u30c3\u30c8\u30a8\u30e9\u30fc: {str(exc)}"],
            }

        normalized["optimizedPrompt"] = enforce_prompt_optimize_rules(
            original_text=text,
            optimized_text=normalized["optimizedPrompt"],
            locale=locale,
        )

        token_warnings = build_token_integrity_warnings(text, normalized["optimizedPrompt"])
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


__all__ = [
    "register_api_workspace_state_routes",
]

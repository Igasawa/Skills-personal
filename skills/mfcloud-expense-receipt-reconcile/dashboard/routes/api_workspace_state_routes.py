from __future__ import annotations

from typing import Any

from .api_workspace_routes import (
    WORKSPACE_PROMPT_OPTIMIZE_MAX_LIST_ITEMS,
    WORKSPACE_PROMPT_OPTIMIZE_MAX_TEXT_CHARS,
    ai_chat,
    _clean_goal_candidate,
    _build_goal_first_optimize_prompt,
    _enforce_prompt_optimize_rules,
    _build_token_integrity_warnings,
    _extract_goal_hint,
    _normalize_prompt_optimize_locale,
    _normalize_prompt_optimize_response,
    _normalize_prompt_optimize_style,
    _try_parse_json_object,
    register_api_workspace_routes as _register_full_api_workspace_routes,
)
from .api_workspace_state_routes_impl import (
    register_api_workspace_state_routes as _register_api_workspace_state_routes,
)


def register_api_workspace_state_routes(*args: Any, **kwargs: Any) -> None:
    """Register workspace state routes.

    Missing prompt-optimize dependencies are filled from local defaults in
    api_workspace_routes so callers that use the legacy signature keep working.
    """
    resolved_kwargs: dict[str, Any] = {
        "ai_chat": kwargs.pop("ai_chat", ai_chat),
        "WORKSPACE_PROMPT_OPTIMIZE_MAX_TEXT_CHARS": kwargs.pop(
            "WORKSPACE_PROMPT_OPTIMIZE_MAX_TEXT_CHARS",
            WORKSPACE_PROMPT_OPTIMIZE_MAX_TEXT_CHARS,
        ),
        "WORKSPACE_PROMPT_OPTIMIZE_MAX_LIST_ITEMS": kwargs.pop(
            "WORKSPACE_PROMPT_OPTIMIZE_MAX_LIST_ITEMS",
            WORKSPACE_PROMPT_OPTIMIZE_MAX_LIST_ITEMS,
        ),
        "clean_goal_candidate": kwargs.pop("clean_goal_candidate", _clean_goal_candidate),
        "extract_goal_hint": kwargs.pop("extract_goal_hint", _extract_goal_hint),
        "normalize_prompt_optimize_locale": kwargs.pop(
            "normalize_prompt_optimize_locale",
            _normalize_prompt_optimize_locale,
        ),
        "normalize_prompt_optimize_style": kwargs.pop(
            "normalize_prompt_optimize_style",
            _normalize_prompt_optimize_style,
        ),
        "build_goal_first_optimize_prompt": kwargs.pop(
            "build_goal_first_optimize_prompt",
            _build_goal_first_optimize_prompt,
        ),
        "try_parse_json_object": kwargs.pop("try_parse_json_object", _try_parse_json_object),
        "normalize_prompt_optimize_response": kwargs.pop(
            "normalize_prompt_optimize_response",
            _normalize_prompt_optimize_response,
        ),
        "enforce_prompt_optimize_rules": kwargs.pop(
            "enforce_prompt_optimize_rules",
            _enforce_prompt_optimize_rules,
        ),
        "build_token_integrity_warnings": kwargs.pop(
            "build_token_integrity_warnings",
            _build_token_integrity_warnings,
        ),
    }
    for name, value in resolved_kwargs.items():
        if name not in kwargs:
            kwargs[name] = value

    _register_api_workspace_state_routes(*args, **kwargs)


def register_api_workspace_routes(*args: Any, **kwargs: Any) -> None:
    """Backward-compatible full route registration entrypoint."""
    _register_full_api_workspace_routes(*args, **kwargs)


__all__ = [
    "register_api_workspace_state_routes",
    "register_api_workspace_routes",
]

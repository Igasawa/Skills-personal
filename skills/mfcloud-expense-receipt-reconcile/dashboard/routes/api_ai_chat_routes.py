from __future__ import annotations

import json
import shlex
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from services import ai_chat
from services import ai_skill_router
from services import ai_skill_tools


def _format_skill_list(skills: list[dict[str, Any]], *, only_allowed: bool = True) -> str:
    all_rows = list(skills)
    rows = [row for row in all_rows if bool(row.get("allowed"))] if only_allowed else all_rows
    runnerless_count = sum(1 for row in all_rows if not bool(row.get("has_runner")))
    if not rows:
        lines = ["No API-executable skills were found."]
        if runnerless_count:
            lines.append(
                f"Note: {runnerless_count} skill(s) have no runner, so `/skill run` cannot execute them."
            )
            lines.append("They are still usable with SKILL.md-based agent execution.")
        return "\n".join(lines)
    lines = ["API-executable skills:"]
    for row in rows:
        skill_id = str(row.get("id") or "").strip()
        desc = str(row.get("description") or "").strip()
        if desc:
            lines.append(f"- {skill_id}: {desc}")
        else:
            lines.append(f"- {skill_id}")
    lines.append("Usage: /skill run <skill_id> [args...]")
    if runnerless_count:
        lines.append(
            f"Note: {runnerless_count} skill(s) have no runner, so `/skill run` cannot execute them."
        )
        lines.append("They are still usable with SKILL.md-based agent execution.")
    return "\n".join(lines)


def _format_skill_result(result: dict[str, Any]) -> str:
    lines = [
        f"skill: {result.get('skill')}",
        f"returncode: {result.get('returncode')}",
        f"duration_ms: {result.get('duration_ms')}",
    ]
    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    if stdout:
        lines.append("stdout:")
        lines.append(stdout)
    if stderr:
        lines.append("stderr:")
        lines.append(stderr)
    if not stdout and not stderr:
        lines.append("(no output)")
    return "\n".join(lines)


def _build_local_skill_response(text: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "status": "ok",
        "provider": "local-skill",
        "model": "local-skill",
        "reply": {"role": "assistant", "content": text},
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    if metadata:
        payload["tool_result"] = metadata
    return payload


def _handle_skill_chat_command(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw.lower().startswith("/skill"):
        return None
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"skill command parse error: {exc}") from exc

    if len(tokens) == 1 or (len(tokens) >= 2 and tokens[1].lower() == "list"):
        rows = ai_skill_tools.list_skills()
        message = _format_skill_list(rows, only_allowed=True)
        return _build_local_skill_response(
            message,
            metadata={"command": "list", "count": len(rows)},
        )

    if len(tokens) >= 3 and tokens[1].lower() == "run":
        skill_id = str(tokens[2] or "").strip()
        args = tokens[3:]
        try:
            result = ai_skill_tools.execute_skill(skill_id=skill_id, args=args)
        except ai_skill_tools.SkillNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ai_skill_tools.SkillNotAllowedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ai_skill_tools.SkillNotExecutableError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ai_skill_tools.SkillExecutionTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except ai_skill_tools.SkillInvalidArgumentsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ai_skill_tools.SkillError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return _build_local_skill_response(
            _format_skill_result(result),
            metadata={"command": "run", "skill": skill_id, "returncode": result.get("returncode")},
        )

    usage = {
        "message": "skill command is invalid. Use '/skill list' or '/skill run <skill_id> [args...]'.",
        "example": "/skill run docs-knowledge-refresh --help",
    }
    return _build_local_skill_response(json.dumps(usage, ensure_ascii=False))


def register_api_ai_chat_routes(router: APIRouter) -> None:
    @router.get("/api/ai/chat/status")
    def api_ai_chat_status() -> JSONResponse:
        return JSONResponse(ai_chat.get_chat_status())

    @router.post("/api/ai/chat")
    def api_ai_chat(payload: dict[str, Any]) -> JSONResponse:
        if "model" in payload:
            raise HTTPException(status_code=400, detail="model field is not allowed.")
        try:
            messages = ai_chat.validate_messages(payload.get("messages"))
            page_context = ai_chat.validate_page_context(payload.get("page_context"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        command_response = _handle_skill_chat_command(messages[-1]["content"])
        if command_response is not None:
            return JSONResponse(command_response)

        latest_text = str(messages[-1]["content"] or "").strip()
        if not latest_text.lower().startswith("/skill"):
            try:
                routed = ai_skill_router.route_chat(messages=messages, page_context=page_context)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except ai_chat.UpstreamTimeoutError as exc:
                raise HTTPException(status_code=504, detail=str(exc)) from exc
            except ai_chat.UpstreamApiError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            if routed is not None:
                return JSONResponse(routed)

        try:
            result = ai_chat.chat(
                messages=messages,
                page_context=page_context,
                policy_profile=ai_chat.POLICY_PROFILE_DASHBOARD_CHAT_STRICT,
            )
        except ai_chat.MissingApiKeyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ai_chat.UpstreamTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except ai_chat.UpstreamApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return JSONResponse({"status": "ok", **result})

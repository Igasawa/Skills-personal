from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from services import ai_skill_tools


def register_api_ai_skill_routes(router: APIRouter) -> None:
    @router.get("/api/ai/skills")
    def api_ai_skill_list() -> JSONResponse:
        rows = ai_skill_tools.list_skills()
        settings = ai_skill_tools.get_permission_settings()
        return JSONResponse({"status": "ok", "skills": rows, "count": len(rows), "permissions": settings})

    @router.get("/api/ai/skills/permissions")
    def api_ai_skill_permissions() -> JSONResponse:
        return JSONResponse({"status": "ok", **ai_skill_tools.get_permission_settings()})

    @router.post("/api/ai/skills/permissions")
    def api_ai_skill_permissions_update(payload: dict[str, Any]) -> JSONResponse:
        skill_id = str(payload.get("skill") or "").strip()
        if "enabled" not in payload:
            raise HTTPException(status_code=400, detail="enabled field is required.")
        if not isinstance(payload.get("enabled"), bool):
            raise HTTPException(status_code=400, detail="enabled must be a boolean.")
        enabled = bool(payload.get("enabled"))

        try:
            permission = ai_skill_tools.set_skill_permission(skill_id=skill_id, enabled=enabled)
        except ai_skill_tools.SkillNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ai_skill_tools.SkillError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        skill_row = next(
            (row for row in ai_skill_tools.list_skills() if str(row.get("id") or "").strip() == permission["skill"]),
            None,
        )
        return JSONResponse({"status": "ok", "permission": permission, "skill": skill_row})

    @router.post("/api/ai/skills/execute")
    def api_ai_skill_execute(payload: dict[str, Any]) -> JSONResponse:
        skill_id = str(payload.get("skill") or "").strip()
        args = payload.get("args")
        timeout_seconds = payload.get("timeout_seconds")

        try:
            result = ai_skill_tools.execute_skill(
                skill_id=skill_id,
                args=args,
                timeout_seconds=timeout_seconds,
            )
        except ai_skill_tools.SkillNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ai_skill_tools.SkillNotExecutableError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ai_skill_tools.SkillNotAllowedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ai_skill_tools.SkillExecutionTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except ai_skill_tools.SkillInvalidArgumentsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ai_skill_tools.SkillError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return JSONResponse({"status": "ok", "result": result})

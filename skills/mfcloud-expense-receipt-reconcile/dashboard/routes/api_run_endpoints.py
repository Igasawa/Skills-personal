from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from services import core, core_scheduler, core_shared

from .api_helpers import _actor_from_request


def register_api_run_endpoints(router: APIRouter) -> None:
    @router.get("/api/steps/{ym}")
    def api_steps(ym: str) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        state = core._workflow_state_for_ym(year, month)
        return JSONResponse(state, headers={"Cache-Control": "no-store"})


    @router.post("/api/steps/{ym}/reset/{step_id}")
    def api_step_reset(ym: str, step_id: str, request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        result = core._reset_step_state(year, month, str(step_id).strip(), actor=actor)
        return JSONResponse({"status": "ok", **result})


    @router.get("/api/exclusions/{ym}")
    def api_get_exclusions(ym: str) -> JSONResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym / "reports"
        data = core._read_json(root / "exclude_orders.json")
        if not isinstance(data, dict):
            data = {"ym": ym, "exclude": []}
        return JSONResponse(data)


    @router.post("/api/exclusions/{ym}")
    def api_set_exclusions(ym: str, payload: dict[str, Any], request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        exclude = payload.get("exclude")
        if not isinstance(exclude, list):
            raise HTTPException(status_code=400, detail="exclude must be a list.")
        source = str(payload.get("source") or "").strip()
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=400, detail="source must be amazon or rakuten.")
        try:
            core._assert_source_action_allowed(year, month, source, "confirm")
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="source_action",
                action="confirm",
                status="rejected",
                actor=actor,
                source=source,
                details={"reason": str(exc.detail)},
            )
            raise

        cleaned: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in exclude:
            if not isinstance(item, dict):
                continue
            item_source = str(item.get("source") or "").strip()
            order_id = str(item.get("order_id") or "").strip()
            if item_source not in {"amazon", "rakuten"}:
                continue
            if not order_id or not core.ORDER_ID_RE.match(order_id):
                continue
            key = (item_source, order_id)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append({"source": item_source, "order_id": order_id})

        reports_dir = core._artifact_root() / ym / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        data = {"ym": ym, "exclude": cleaned, "updated_at": datetime.now().isoformat(timespec="seconds")}
        core._write_json(reports_dir / "exclude_orders.json", data)
        wf = core._read_workflow(reports_dir)
        section = wf.get(source) if isinstance(wf.get(source), dict) else {}
        section["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
        section.pop("printed_at", None)
        section.pop("print_prepared_at", None)
        wf[source] = section
        core._write_workflow(reports_dir, wf)
        core._append_audit_event(
            year=year,
            month=month,
            event_type="source_action",
            action="confirm",
            status="success",
            actor=actor,
            source=source,
            details={"exclude_count": len(cleaned)},
        )

        return JSONResponse({"status": "ok", "count": len(cleaned)})



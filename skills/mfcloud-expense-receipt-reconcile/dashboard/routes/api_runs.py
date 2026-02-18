from __future__ import annotations

from datetime import datetime
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from services import core

ActorFromRequest = Callable[[Request], dict[str, str]]
TryYearMonth = Callable[[dict[str, Any]], tuple[int, int] | None]
ErrorToolRunner = Callable[..., dict[str, Any]]
GetErrorReportsRoot = Callable[[], Path]
GetReviewScriptPath = Callable[[], Path]


def register_api_run_routes(
    router: APIRouter,
    *,
    actor_from_request: ActorFromRequest,
    try_year_month: TryYearMonth,
    run_error_tool: ErrorToolRunner,
    safe_incident_id: Callable[[str], str],
    extract_incident_year_month: Callable[[dict[str, Any]], tuple[int, int] | None],
    error_reports_root: GetErrorReportsRoot,
    review_kil_script_path: GetReviewScriptPath,
) -> None:

    @router.post("/api/runs")
    def api_run(payload: dict[str, Any], request: Request) -> JSONResponse:
        actor = actor_from_request(request)
        req_payload = dict(payload)
        req_payload["_audit_actor"] = actor
        mode = str(req_payload.get("mode") or "unknown")
        try:
            result = core._start_run(req_payload)
        except HTTPException as exc:
            ym = try_year_month(req_payload)
            detail = str(exc.detail)
            if ym and ("Invalid year/month" in detail or "Month must be between" in detail):
                year, month = ym
                core._append_audit_event(
                    year=year,
                    month=month,
                    event_type="run",
                    action=mode,
                    status="rejected",
                    actor=actor,
                    mode=mode,
                    details={"reason": detail},
                )
            raise
        return JSONResponse(result)
    
    @router.post("/api/runs/{run_id}/stop")
    def api_run_stop(run_id: str, request: Request) -> JSONResponse:
        run_id = core._safe_run_id(run_id)
        meta_path = core._runs_root() / f"{run_id}.json"
        meta = core._read_json(meta_path)
        if not meta:
            raise HTTPException(status_code=404, detail="Run not found.")
        if meta.get("status") != "running":
            return JSONResponse({"status": "ignored", "message": "Run is not running."})
    
        pid = meta.get("pid")
        if pid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass
    
        meta["status"] = "cancelled"
        meta["finished_at"] = datetime.now().isoformat(timespec="seconds")
        meta["returncode"] = -1
        core._write_json(meta_path, meta)
        params = meta.get("params") if isinstance(meta.get("params"), dict) else {}
        try:
            year = int(params.get("year"))
            month = int(params.get("month"))
        except Exception:
            year = None
            month = None
        if year is not None and month is not None:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="run",
                action="stop",
                status="success",
                actor=actor_from_request(request),
                mode=str(params.get("mode") or ""),
                run_id=run_id,
                details={"returncode": -1},
            )
        return JSONResponse({"status": "cancelled", "run_id": run_id})
    
    @router.get("/api/runs/{run_id}")
    def api_run_status(run_id: str) -> JSONResponse:
        run_id = core._safe_run_id(run_id)
        core._reconcile_running_jobs()
        meta_path = core._runs_root() / f"{run_id}.json"
        meta = core._read_json(meta_path)
        if not meta:
            raise HTTPException(status_code=404, detail="Run not found.")
    
        log_path = Path(meta.get("log_path") or "")
        log_text = core._tail_text(log_path, max_bytes=8000)
        return JSONResponse({"run": meta, "log_tail": log_text}, headers={"Cache-Control": "no-store"})
    
    @router.get("/api/mf-draft-actions/{ym}")
    def api_get_mf_draft_actions(ym: str, limit_events: int = 0) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        payload = core._mf_draft_actions_summary_for_ym(year, month, limit_events=limit_events)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    
    @router.get("/api/errors/incidents")
    def api_get_error_incidents() -> JSONResponse:
        payload = run_error_tool("error_status.py", ["--json"], timeout_seconds=30)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    
    @router.post("/api/errors/incidents/plan-all")
    def api_build_all_error_plans(payload: dict[str, Any] | None = None) -> JSONResponse:
        body = payload if isinstance(payload, dict) else {}
        force = bool(body.get("force"))
        status_payload = run_error_tool("error_status.py", ["--json"], timeout_seconds=30)
        incidents = status_payload.get("incidents") if isinstance(status_payload.get("incidents"), list) else []
    
        planned: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
    
        for row in incidents:
            if not isinstance(row, dict):
                continue
            raw_incident_id = str(row.get("incident_id") or "").strip()
            if not raw_incident_id:
                continue
            try:
                safe_incident_id = safe_incident_id(raw_incident_id)
            except HTTPException as exc:
                failed.append({"incident_id": raw_incident_id, "detail": str(exc.detail)})
                continue
    
            args = ["--incident-id", safe_incident_id]
            if force:
                args.append("--force")
            try:
                result = run_error_tool("error_plan_generate.py", args, timeout_seconds=60)
                planned.append(
                    {
                        "incident_id": safe_incident_id,
                        "plan_json": str(result.get("plan_json") or ""),
                    }
                )
            except HTTPException as exc:
                failed.append({"incident_id": safe_incident_id, "detail": str(exc.detail)})
    
        return JSONResponse(
            {
                "status": "ok",
                "target_count": len(incidents),
                "planned_count": len(planned),
                "failed_count": len(failed),
                "planned": planned,
                "failed": failed,
            },
            headers={"Cache-Control": "no-store"},
        )
    
    @router.get("/api/errors/incidents/{incident_id}")
    def api_get_error_incident(incident_id: str) -> JSONResponse:
        safe_incident_id = safe_incident_id(incident_id)
        payload = run_error_tool(
            "error_status.py",
            ["--json", "--incident-id", safe_incident_id],
            timeout_seconds=30,
        )
        plan_dir = error_reports_root() / "error_plans" / safe_incident_id
        plan_json = core._read_json(plan_dir / "plan.json")
        if isinstance(plan_json, dict):
            payload["plan"] = plan_json
            payload["plan_json_path"] = str(plan_dir / "plan.json")
            payload["plan_md_path"] = str(plan_dir / "plan.md")
        run_result = core._read_json(error_reports_root() / "error_runs" / safe_incident_id / "run_result.json")
        if isinstance(run_result, dict):
            payload["run_result"] = run_result
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    
    @router.post("/api/errors/incidents/{incident_id}/plan")
    def api_build_error_plan(incident_id: str, request: Request, payload: dict[str, Any] | None = None) -> JSONResponse:
        safe_incident_id = safe_incident_id(incident_id)
        body = payload if isinstance(payload, dict) else {}
        args = ["--incident-id", safe_incident_id]
        if bool(body.get("force")):
            args.append("--force")
        result = run_error_tool("error_plan_generate.py", args, timeout_seconds=60)
    
        ym = extract_incident_year_month(result)
        if ym:
            year, month = ym
            core._append_audit_event(
                year=year,
                month=month,
                event_type="error_incident",
                action="plan",
                status="success",
                actor=actor_from_request(request),
                details={
                    "incident_id": safe_incident_id,
                    "plan_json": result.get("plan_json"),
                },
            )
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    
    @router.post("/api/errors/incidents/{incident_id}/go")
    def api_execute_error_go(incident_id: str, request: Request, payload: dict[str, Any] | None = None) -> JSONResponse:
        safe_incident_id = safe_incident_id(incident_id)
        body = payload if isinstance(payload, dict) else {}
        max_loops = core._safe_non_negative_int(body.get("max_loops"), default=8) or 8
        max_runtime = core._safe_non_negative_int(body.get("max_runtime_minutes"), default=45) or 45
        same_error_limit = core._safe_non_negative_int(body.get("same_error_limit"), default=3) or 3
        single_iteration = bool(body.get("single_iteration"))
        archive_on_success = bool(body.get("archive_on_success", True))
        archive_on_escalate = bool(body.get("archive_on_escalate", True))
    
        args = [
            "--incident-id",
            safe_incident_id,
            "--max-loops",
            str(max_loops),
            "--max-runtime-minutes",
            str(max_runtime),
            "--same-error-limit",
            str(same_error_limit),
        ]
        if single_iteration:
            args.append("--single-iteration")
        if archive_on_success:
            args.append("--archive-on-success")
        if archive_on_escalate:
            args.append("--archive-on-escalate")
    
        timeout_seconds = max(60, max_runtime * 60 + 120)
        result = run_error_tool("error_exec_loop.py", args, timeout_seconds=timeout_seconds)
    
        incident_view = run_error_tool(
            "error_status.py",
            ["--json", "--incident-id", safe_incident_id],
            timeout_seconds=30,
        )
        ym = extract_incident_year_month(incident_view)
        if ym:
            year, month = ym
            core._append_audit_event(
                year=year,
                month=month,
                event_type="error_incident",
                action="go_exec",
                status=str(result.get("final_status") or "unknown"),
                actor=actor_from_request(request),
                details={
                    "incident_id": safe_incident_id,
                    "loops_used": result.get("loops_used"),
                    "runtime_minutes": result.get("runtime_minutes"),
                    "same_error_repeats": result.get("same_error_repeats"),
                },
            )
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    
    @router.post("/api/errors/incidents/{incident_id}/archive")
    def api_archive_error_incident(incident_id: str, request: Request, payload: dict[str, Any]) -> JSONResponse:
        safe_incident_id = safe_incident_id(incident_id)
        body = payload if isinstance(payload, dict) else {}
        result_value = str(body.get("result") or "").strip().lower()
        if result_value not in {"resolved", "escalated"}:
            raise HTTPException(status_code=400, detail="result must be resolved or escalated.")
        reason = str(body.get("reason") or "").strip()
        args = ["--incident-id", safe_incident_id, "--result", result_value]
        if reason:
            args += ["--reason", reason]
        result = run_error_tool("error_archive.py", args, timeout_seconds=30)
    
        incident_view = run_error_tool("error_status.py", ["--json"], timeout_seconds=30)
        ym = extract_incident_year_month(incident_view)
        if ym:
            year, month = ym
            core._append_audit_event(
                year=year,
                month=month,
                event_type="error_incident",
                action="archive",
                status=result_value,
                actor=actor_from_request(request),
                details={"incident_id": safe_incident_id, "reason": reason},
        )
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    
    @router.post("/api/errors/doc-update/run")
    def api_run_doc_update(request: Request) -> JSONResponse:
        _ = request
        script_path = review_kil_script_path()
        started_at = datetime.now()
        try:
            process = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(script_path.parent),
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                status_code=504,
                detail=f"Document update tool timeout: review_kil_brain.py ({exc.timeout}s)",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Document update tool failed to start: {exc}",
            ) from exc
    
        if process.returncode != 0:
            detail = (process.stderr or process.stdout or "").strip() or f"exit={process.returncode}"
            raise HTTPException(
                status_code=500,
                detail=f"Document update tool failed: {detail}",
            )
    
        duration = (datetime.now() - started_at).total_seconds()
        return JSONResponse(
            {
                "status": "ok",
                "tool": "review_kil_brain.py",
                "script": str(script_path),
                "returncode": int(process.returncode),
                "stdout": process.stdout.strip() if process.stdout else "",
                "stderr": process.stderr.strip() if process.stderr else "",
                "duration_seconds": round(float(duration), 2),
                "ran_at": datetime.now().isoformat(timespec="seconds"),
            },
            headers={"Cache-Control": "no-store"},
        )
    


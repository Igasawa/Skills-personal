from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from services import core, core_scheduler, core_shared

from .api_helpers import (
    _actor_from_request,
    _merge_workspace_link_notes,
    _merge_workspace_link_profiles,
    _merge_workspace_links,
    _merge_workspace_pinned_links,
    _sanitize_workspace_pinned_link_groups,
    _merge_workspace_pinned_link_groups,
    _merge_workspace_prompts,
    _read_workspace_state,
    _sanitize_workspace_active_prompt_key,
    _sanitize_workspace_link_notes,
    _sanitize_workspace_link_profiles,
    _sanitize_workspace_links,
    _sanitize_workspace_pinned_links,
    _sanitize_workspace_prompts,
    _write_workspace_state,
    WORKFLOW_PAGE_ID_RE,
    WORKFLOW_PAGE_MAX_ITEMS,
    WORKFLOW_PAGE_MAX_NAME_CHARS,
    WORKFLOW_PAGE_MAX_STEP_VERSIONS,
    WORKFLOW_PAGE_MAX_SUBHEADING_CHARS,
    WORKFLOW_TEMPLATE_ALLOWED_STEP_ACTIONS,
    WORKFLOW_TEMPLATE_DEFAULT_STEP_TIMER_MINUTES,
    WORKFLOW_TEMPLATE_FALLBACK_ACTION_ORDER,
    WORKFLOW_TEMPLATE_ID_RE,
    WORKFLOW_TEMPLATE_MAX_ITEMS,
    WORKFLOW_TEMPLATE_MAX_NAME_CHARS,
    WORKFLOW_TEMPLATE_MAX_NOTES_CHARS,
    WORKFLOW_TEMPLATE_MAX_SEARCH_CHARS,
    WORKFLOW_TEMPLATE_MAX_SOURCE_URLS,
    WORKFLOW_TEMPLATE_MAX_STEP_AGENT_PROMPT_CHARS,
    WORKFLOW_TEMPLATE_MAX_STEP_ACTION_CHARS,
    WORKFLOW_TEMPLATE_MAX_STEP_EXECUTION_LOG_ITEMS,
    WORKFLOW_TEMPLATE_MAX_STEP_EXECUTION_LOG_MESSAGE_CHARS,
    WORKFLOW_TEMPLATE_MAX_STEP_TIMER_MINUTES,
    WORKFLOW_TEMPLATE_MAX_STEP_TITLE_CHARS,
    WORKFLOW_TEMPLATE_MAX_STEPS,
    WORKFLOW_TEMPLATE_MAX_SUBHEADING_CHARS,
    WORKFLOW_TEMPLATE_MAX_URL_CHARS,
    WORKFLOW_TEMPLATE_MIN_STEP_TIMER_MINUTES,
    WORKFLOW_TEMPLATE_MODES,
    WORKFLOW_TEMPLATE_REQUIRED_STEP_ACTIONS,
    WORKFLOW_TEMPLATE_REQUIRED_STEP_TITLES,
    WORKFLOW_TEMPLATE_SORT_OPTIONS,
    WORKFLOW_TEMPLATE_STEP_DEFAULT_ACTION,
    WORKFLOW_TEMPLATE_STEP_DEFAULT_TRIGGER,
    WORKFLOW_TEMPLATE_STEP_DEFAULT_TYPE,
    WORKFLOW_TEMPLATE_STEP_TRIGGERS,
    WORKFLOW_TEMPLATE_STEP_TYPES,
)
from .api_workspace_routes import register_api_workspace_routes


def register_api_workflow_endpoints(router: APIRouter) -> None:
    def _run_archive_action(
        *,
        ym: str,
        request: Request,
        action: str,
        cleanup: bool,
    ) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        include_pdfs = True
        include_debug = False
        try:
            if action == "month_close":
                checklist_payload = core._read_month_close_checklist_for_ym(ym)
                checklist = checklist_payload.get("checklist")
                missing_items = core._incomplete_month_close_checklist_keys(checklist)
                if missing_items:
                    joined = ", ".join(missing_items)
                    raise HTTPException(
                        status_code=409,
                        detail=f"Month close checklist is incomplete: {joined}",
                    )
            core._assert_archive_allowed(year, month)
            result = core._archive_outputs_for_ym(
                year,
                month,
                include_pdfs=include_pdfs,
                include_debug=include_debug,
                cleanup=cleanup,
            )
        except HTTPException as exc:
            core._append_audit_event(
                year=year,
                month=month,
                event_type="archive",
                action=action,
                status="rejected" if exc.status_code in {400, 404, 409} else "failed",
                actor=actor,
                details={
                    "reason": str(exc.detail),
                    "include_pdfs": include_pdfs,
                    "include_debug": include_debug,
                    "cleanup": cleanup,
                },
            )
            raise
        core._append_audit_event(
            year=year,
            month=month,
            event_type="archive",
            action=action,
            status="success",
            actor=actor,
            details={
                "archived_to": result.get("archived_to"),
                "include_pdfs": include_pdfs,
                "include_debug": include_debug,
                "cleanup": cleanup,
                "cleanup_report": result.get("cleanup_report"),
                "cleanup_removed": result.get("cleanup_removed"),
            },
        )
        response = dict(result)
        response["history_entry"] = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "ym": ym,
            "action": action,
            "action_label": core_shared._archive_action_label(action),
            "archived_to": result.get("archived_to"),
            "archive_url": f"/runs/{ym}/archived-receipts",
        }
        return JSONResponse(response)


    @router.post("/api/archive/{ym}")
    def api_archive(ym: str, request: Request) -> JSONResponse:
        return _run_archive_action(
            ym=ym,
            request=request,
            action="manual_archive",
            cleanup=False,
        )


    @router.post("/api/month-close/{ym}")
    def api_month_close(ym: str, request: Request) -> JSONResponse:
        return _run_archive_action(
            ym=ym,
            request=request,
            action="month_close",
            cleanup=True,
        )


    @router.get("/api/month-close-checklist/{ym}")
    def api_get_month_close_checklist(ym: str) -> JSONResponse:
        ym = core._safe_ym(ym)
        data = core._read_month_close_checklist_for_ym(ym)
        return JSONResponse(data)


    @router.post("/api/month-close-checklist/{ym}")
    def api_set_month_close_checklist(ym: str, payload: dict[str, Any], request: Request) -> JSONResponse:
        ym = core._safe_ym(ym)
        year, month = core._split_ym(ym)
        actor = _actor_from_request(request)
        checklist = core._validate_month_close_checklist_payload(payload.get("checklist"))
        checklist_path = core._month_close_checklist_path_for_ym(ym)

        data = {
            "ym": ym,
            "checklist": checklist,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        core._write_json(checklist_path, data)

        core._append_audit_event(
            year=year,
            month=month,
            event_type="month_close_checklist",
            action="update",
            status="success",
            actor=actor,
            details={"checklist": checklist},
        )

        return JSONResponse({"status": "ok", "checklist": checklist})


    def _workflow_templates_path() -> Path:
        return core._artifact_root() / "_workflow_templates" / "workflow_templates.json"


    def _normalize_workflow_template_id(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw or not WORKFLOW_TEMPLATE_ID_RE.fullmatch(raw):
            return ""
        return raw


    def _normalize_workflow_template_mode(value: Any) -> str:
        mode = str(value or "").strip().lower()
        return mode if mode in WORKFLOW_TEMPLATE_MODES else "new"


    def _normalize_workflow_template_name(value: Any) -> str:
        return " ".join(str(value or "").strip().split())[:WORKFLOW_TEMPLATE_MAX_NAME_CHARS] or "Workflow template"


    def _normalize_workflow_template_url(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if len(raw) > WORKFLOW_TEMPLATE_MAX_URL_CHARS:
            raw = raw[:WORKFLOW_TEMPLATE_MAX_URL_CHARS]
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return raw


    def _normalize_workflow_template_source_urls(value: Any) -> list[str]:
        raw_values = value if isinstance(value, list) else []
        normalized: list[str] = []
        seen: set[str] = set()
        for row in raw_values:
            url = _normalize_workflow_template_url(row)
            if not url:
                continue
            key = url.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(url)
            if len(normalized) >= WORKFLOW_TEMPLATE_MAX_SOURCE_URLS:
                break
        return normalized


    def _normalize_workflow_template_step_timer_minutes(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        timer_minutes = core._safe_non_negative_int(value, default=0)
        if timer_minutes < 0:
            return 0
        if timer_minutes > WORKFLOW_TEMPLATE_MAX_STEP_TIMER_MINUTES:
            return WORKFLOW_TEMPLATE_MAX_STEP_TIMER_MINUTES
        return timer_minutes


    def _normalize_workflow_template_step_order(value: Any, *, default: int) -> int:
        order = core._safe_non_negative_int(value, default=default)
        if order < 1:
            return default
        return order


    def _normalize_workflow_template_step_auto_run(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if not text:
            return False
        return text in {"1", "true", "yes", "on"}


    def _normalize_workflow_template_step_type(value: Any, *, default: str = WORKFLOW_TEMPLATE_STEP_DEFAULT_TYPE) -> str:
        step_type = str(value or "").strip().lower()
        if step_type in WORKFLOW_TEMPLATE_STEP_TYPES:
            return step_type
        return default


    def _normalize_workflow_template_step_trigger(
        value: Any,
        *,
        default: str = WORKFLOW_TEMPLATE_STEP_DEFAULT_TRIGGER,
    ) -> str:
        trigger = str(value or "").strip().lower()
        if trigger in WORKFLOW_TEMPLATE_STEP_TRIGGERS:
            return trigger
        return default


    def _normalize_workflow_template_step_agent_prompt(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()[:WORKFLOW_TEMPLATE_MAX_STEP_AGENT_PROMPT_CHARS]


    def _normalize_workflow_template_step_execution_log(value: Any) -> list[dict[str, str]]:
        rows = value if isinstance(value, list) else []
        normalized: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            result_raw = str(row.get("result") or "").strip().lower()
            result = "failed" if result_raw == "failed" else "success"
            executed_at = str(row.get("executed_at") or row.get("executedAt") or "").strip()
            message = str(row.get("message") or "").strip()[:WORKFLOW_TEMPLATE_MAX_STEP_EXECUTION_LOG_MESSAGE_CHARS]
            if not executed_at and not message:
                continue
            normalized.append(
                {
                    "executed_at": executed_at,
                    "result": result,
                    "message": message,
                }
            )
            if len(normalized) >= WORKFLOW_TEMPLATE_MAX_STEP_EXECUTION_LOG_ITEMS:
                break
        return normalized


    def _default_workflow_template_step_title(action: str) -> str:
        action_key = str(action or "").strip()
        defaults = {
            "preflight": "手順0 準備（ログイン確認・MF連携更新）",
            "preflight_mf": "手順0 MF再取得のみ",
            "amazon_download": "手順1 Amazon領収書取得",
            "amazon_print": "手順1 Amazon除外判断・印刷",
            "rakuten_download": "手順2 楽天領収書取得",
            "rakuten_print": "手順2 楽天除外判断・印刷",
            "provider_ingest": "手順3 共通フォルダ取り込み",
            "mf_bulk_upload_task": "手順4 MF一括アップロード",
            "month_close": "手順6 月次クローズ",
        }
        default_title = defaults.get(action_key) or WORKFLOW_TEMPLATE_REQUIRED_STEP_TITLES.get(action_key) or action_key
        return default_title[:WORKFLOW_TEMPLATE_MAX_STEP_TITLE_CHARS]


    def _next_available_step_action(used_actions: set[str]) -> str:
        for action in WORKFLOW_TEMPLATE_FALLBACK_ACTION_ORDER:
            if action in WORKFLOW_TEMPLATE_ALLOWED_STEP_ACTIONS and action not in used_actions:
                return action
        return WORKFLOW_TEMPLATE_STEP_DEFAULT_ACTION


    def _normalize_workflow_template_steps(value: Any) -> list[dict[str, Any]]:
        raw_values = value if isinstance(value, list) else []
        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        used_actions: set[str] = set()
        for index, row in enumerate(raw_values):
            has_timer_field = False
            raw_id = ""
            raw_title = ""
            raw_action = ""
            raw_type: Any = None
            raw_trigger: Any = None
            raw_target_url: Any = None
            raw_agent_prompt: Any = None
            raw_timer_minutes: Any = None
            raw_order: Any = index + 1
            raw_auto_run: Any = False
            raw_execution_log: Any = []
            if isinstance(row, dict):
                has_timer_field = "timer_minutes" in row or "timer" in row
                raw_id = str(row.get("id") or "").strip()
                if "title" in row:
                    raw_title = row.get("title")
                elif "name" in row:
                    raw_title = row.get("name")
                raw_action = str(row.get("action") or "").strip()
                if "timer_minutes" in row:
                    raw_timer_minutes = row.get("timer_minutes")
                elif "timer" in row:
                    raw_timer_minutes = row.get("timer")
                raw_order = row.get("order")
                if "auto_run" in row:
                    raw_auto_run = row.get("auto_run")
                elif "autoRun" in row:
                    raw_auto_run = row.get("autoRun")
                if "execution_log" in row:
                    raw_execution_log = row.get("execution_log")
                elif "executionLog" in row:
                    raw_execution_log = row.get("executionLog")
                if "type" in row:
                    raw_type = row.get("type")
                elif "step_type" in row:
                    raw_type = row.get("step_type")
                if "trigger" in row:
                    raw_trigger = row.get("trigger")
                if "target_url" in row:
                    raw_target_url = row.get("target_url")
                elif "targetUrl" in row:
                    raw_target_url = row.get("targetUrl")
                elif "url" in row:
                    raw_target_url = row.get("url")
                if "agent_prompt" in row:
                    raw_agent_prompt = row.get("agent_prompt")
                elif "agentPrompt" in row:
                    raw_agent_prompt = row.get("agentPrompt")
                elif "prompt" in row:
                    raw_agent_prompt = row.get("prompt")
            else:
                raw_title = row

            action = str(raw_action or "").strip()[:WORKFLOW_TEMPLATE_MAX_STEP_ACTION_CHARS]
            if action and action in used_actions:
                continue

            title = " ".join(str(raw_title or "").strip().split())
            if not title:
                if action:
                    title = _default_workflow_template_step_title(action)
                else:
                    continue
            auto_run = _normalize_workflow_template_step_auto_run(raw_auto_run)
            timer_minutes = _normalize_workflow_template_step_timer_minutes(raw_timer_minutes) if has_timer_field else None
            if auto_run and (
                timer_minutes is None or timer_minutes < WORKFLOW_TEMPLATE_MIN_STEP_TIMER_MINUTES
            ):
                timer_minutes = WORKFLOW_TEMPLATE_DEFAULT_STEP_TIMER_MINUTES
            target_url = _normalize_workflow_template_url(raw_target_url)
            agent_prompt = _normalize_workflow_template_step_agent_prompt(raw_agent_prompt)
            type_default = WORKFLOW_TEMPLATE_STEP_DEFAULT_TYPE
            if target_url:
                type_default = "browser"
            elif agent_prompt:
                type_default = "agent"
            step_type = _normalize_workflow_template_step_type(raw_type, default=type_default)
            trigger_default = "schedule" if auto_run else WORKFLOW_TEMPLATE_STEP_DEFAULT_TRIGGER
            trigger = _normalize_workflow_template_step_trigger(raw_trigger, default=trigger_default)
            order = _normalize_workflow_template_step_order(raw_order, default=index + 1)
            execution_log = _normalize_workflow_template_step_execution_log(raw_execution_log)
            normalized_row: dict[str, Any] = {
                "title": title[:WORKFLOW_TEMPLATE_MAX_STEP_TITLE_CHARS],
                "action": action,
                "type": step_type,
                "trigger": trigger,
                "target_url": target_url,
                "agent_prompt": agent_prompt,
                "order": order,
                "auto_run": auto_run,
                "timer_minutes": timer_minutes,
                "execution_log": execution_log,
            }

            step_id = raw_id[:24]
            if not step_id:
                step_id = uuid4().hex[:24]
            if len(step_id) < 8:
                step_id = f"{step_id}-{uuid4().hex}"[:24]
            if step_id in seen_ids:
                while step_id in seen_ids:
                    step_id = uuid4().hex[:24]
            seen_ids.add(step_id)
            normalized_row["id"] = step_id

            normalized.append(normalized_row)
            if action:
                used_actions.add(action)
            if len(normalized) >= WORKFLOW_TEMPLATE_MAX_STEPS:
                break

        for index, row in enumerate(normalized, start=1):
            row["order"] = index
        return normalized


    def _normalize_workflow_template_year(value: Any) -> int:
        year = core._safe_non_negative_int(value, default=0)
        if year and not 2000 <= year <= 3000:
            return 0
        return year


    def _normalize_workflow_template_month(value: Any) -> int:
        month = core._safe_non_negative_int(value, default=0)
        if month and not 1 <= month <= 12:
            return 0
        return month


    def _normalize_workflow_template_notes(value: Any) -> str:
        return " ".join(str(value or "").strip().split())[:WORKFLOW_TEMPLATE_MAX_NOTES_CHARS]


    def _normalize_workflow_template_subheading(value: Any) -> str:
        return " ".join(str(value or "").strip().split())[:WORKFLOW_TEMPLATE_MAX_SUBHEADING_CHARS]


    def _workflow_template_timestamp_now() -> str:
        return datetime.now().isoformat(timespec="seconds")


    def _normalize_workflow_template_timestamp(value: Any) -> str:
        return str(value or "").strip()


    def _sort_workflow_templates(
        templates: list[dict[str, Any]],
        *,
        sort: str,
    ) -> list[dict[str, Any]]:
        if sort not in WORKFLOW_TEMPLATE_SORT_OPTIONS:
            sort = "updated_desc"
        if sort.startswith("updated"):
            key = lambda item: str(item.get("updated_at") or item.get("created_at") or "")
        elif sort.startswith("created"):
            key = lambda item: str(item.get("created_at") or item.get("updated_at") or "")
        elif sort == "name_asc":
            key = lambda item: str(item.get("name") or "").lower()
        elif sort == "name_desc":
            key = lambda item: str(item.get("name") or "").lower()
        else:
            key = lambda item: (int(item.get("year") or 0), int(item.get("month") or 0))
        reverse = sort.endswith("desc")
        return sorted(templates, key=key, reverse=reverse)


    def _read_workflow_templates() -> list[dict[str, Any]]:
        raw = core._read_json(_workflow_templates_path())
        if not isinstance(raw, list):
            return []

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in raw:
            if not isinstance(row, dict):
                continue
            template_id = _normalize_workflow_template_id(row.get("id"))
            if not template_id or template_id in seen:
                continue
            mfcloud_url = _normalize_workflow_template_url(row.get("mfcloud_url"))
            source_urls = _normalize_workflow_template_source_urls(row.get("source_urls"))
            if not source_urls and mfcloud_url:
                source_urls = [mfcloud_url]
            if source_urls:
                mfcloud_url = source_urls[0]
            year_raw = _normalize_workflow_template_year(row.get("year"))
            month_raw = _normalize_workflow_template_month(row.get("month"))
            name = _normalize_workflow_template_name(row.get("name"))
            if not name:
                continue
            rows.append(
                {
                    "id": template_id,
                    "name": name,
                    "year": year_raw,
                    "month": month_raw,
                    "mfcloud_url": mfcloud_url,
                    "source_urls": source_urls,
                    "steps": _normalize_workflow_template_steps(row.get("steps")),
                    "notes": _normalize_workflow_template_notes(row.get("notes")),
                    "subheading": _normalize_workflow_template_subheading(row.get("subheading")),
                    "rakuten_orders_url": _normalize_workflow_template_url(row.get("rakuten_orders_url")) or "",
                    "source_template_id": _normalize_workflow_template_id(row.get("source_template_id")),
                    "created_at": _normalize_workflow_template_timestamp(row.get("created_at"))
                    or _workflow_template_timestamp_now(),
                    "updated_at": _normalize_workflow_template_timestamp(row.get("updated_at"))
                    or _workflow_template_timestamp_now(),
                }
            )
            seen.add(template_id)
        rows = _sort_workflow_templates(rows, sort="updated_desc")
        if len(rows) > WORKFLOW_TEMPLATE_MAX_ITEMS:
            rows = rows[:WORKFLOW_TEMPLATE_MAX_ITEMS]
        return rows


    def _write_workflow_templates(rows: list[dict[str, Any]]) -> None:
        if len(rows) > WORKFLOW_TEMPLATE_MAX_ITEMS:
            rows = rows[:WORKFLOW_TEMPLATE_MAX_ITEMS]
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            template_id = _normalize_workflow_template_id(row.get("id"))
            if not template_id:
                continue
            year = _normalize_workflow_template_year(row.get("year"))
            month = _normalize_workflow_template_month(row.get("month"))
            mfcloud_url = _normalize_workflow_template_url(row.get("mfcloud_url"))
            source_urls = _normalize_workflow_template_source_urls(row.get("source_urls"))
            if not source_urls and mfcloud_url:
                source_urls = [mfcloud_url]
            if source_urls:
                mfcloud_url = source_urls[0]
            normalized.append(
                {
                    "id": template_id,
                    "name": _normalize_workflow_template_name(row.get("name")),
                    "year": year,
                    "month": month,
                    "mfcloud_url": mfcloud_url,
                    "source_urls": source_urls,
                    "steps": _normalize_workflow_template_steps(row.get("steps")),
                    "notes": _normalize_workflow_template_notes(row.get("notes")),
                    "subheading": _normalize_workflow_template_subheading(row.get("subheading")),
                    "rakuten_orders_url": _normalize_workflow_template_url(row.get("rakuten_orders_url")),
                    "source_template_id": _normalize_workflow_template_id(row.get("source_template_id")),
                    "created_at": str(row.get("created_at") or _workflow_template_timestamp_now()),
                    "updated_at": str(row.get("updated_at") or _workflow_template_timestamp_now()),
                }
            )
        core._write_json(_workflow_templates_path(), normalized)


    def _template_name_taken(
        rows: list[dict[str, Any]],
        name: str,
        *,
        allow_existing_id: str | None,
    ) -> bool:
        normalized_name = str(name or "").strip().lower()
        if not normalized_name:
            return False
        for row in rows:
            row_id = str(row.get("id") or "")
            if row_id == str(allow_existing_id or ""):
                continue
            if str(row.get("name") or "").strip().lower() == normalized_name:
                return True
        return False


    def _normalize_workflow_template_payload(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

        raw_template_id = _normalize_workflow_template_id(payload.get("template_id") or payload.get("id"))
        template_mode = _normalize_workflow_template_mode(payload.get("template_mode"))
        template_mode_requested = str(payload.get("template_mode") or "").strip().lower() in WORKFLOW_TEMPLATE_MODES
        base_updated_at = _normalize_workflow_template_timestamp(payload.get("base_updated_at"))

        if template_mode == "copy":
            template_id = ""
        else:
            template_id = raw_template_id

        source_template_id = ""
        if template_mode == "copy":
            source_template_id = _normalize_workflow_template_id(
                payload.get("source_template_id")
                or payload.get("template_source_id")
                or raw_template_id
            )
        if template_mode == "copy" and not source_template_id:
            raise HTTPException(status_code=400, detail="template_source_id is required for copy mode.")
        if template_mode == "edit" and template_mode_requested and template_id and not base_updated_at:
            raise HTTPException(status_code=400, detail="edit mode requires base_updated_at.")

        name = _normalize_workflow_template_name(payload.get("name"))
        if not name:
            raise HTTPException(status_code=400, detail="template name is required.")
        source_urls = _normalize_workflow_template_source_urls(payload.get("source_urls"))
        mfcloud_url = _normalize_workflow_template_url(payload.get("mfcloud_url"))
        steps = _normalize_workflow_template_steps(payload.get("steps"))
        if not source_urls and mfcloud_url:
            source_urls = [mfcloud_url]
        if source_urls:
            mfcloud_url = source_urls[0]
        else:
            mfcloud_url = ""
        year = _normalize_workflow_template_year(payload.get("year"))
        month = _normalize_workflow_template_month(payload.get("month"))

        normalized = {
            "id": template_id or uuid4().hex[:24],
            "name": name,
            "year": year,
            "month": month,
            "mfcloud_url": mfcloud_url,
            "source_urls": source_urls,
            "steps": steps,
            "notes": _normalize_workflow_template_notes(payload.get("notes")),
            "subheading": _normalize_workflow_template_subheading(payload.get("subheading")),
            "rakuten_orders_url": _normalize_workflow_template_url(payload.get("rakuten_orders_url")) or "",
            "template_mode": template_mode,
            "allow_duplicate_name": bool(payload.get("allow_duplicate_name")),
            "base_updated_at": base_updated_at,
            "created_at": "",
            "updated_at": _workflow_template_timestamp_now(),
        }
        if source_template_id:
            normalized["source_template_id"] = source_template_id
        return normalized


    def _workflow_pages_path() -> Path:
        return core._artifact_root() / "_workflow_pages" / "workflow_pages.json"


    def _normalize_workflow_page_id(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw or not WORKFLOW_PAGE_ID_RE.fullmatch(raw):
            return ""
        return raw


    def _normalize_workflow_page_name(value: Any) -> str:
        return " ".join(str(value or "").strip().split())[:WORKFLOW_PAGE_MAX_NAME_CHARS]


    def _normalize_workflow_page_subheading(value: Any) -> str:
        return " ".join(str(value or "").strip().split())[:WORKFLOW_PAGE_MAX_SUBHEADING_CHARS]


    def _normalize_workflow_page_step_version(value: Any) -> int:
        version = core._safe_non_negative_int(value, default=1)
        return version if version >= 1 else 1


    def _normalize_workflow_page_step_versions(
        value: Any,
        *,
        fallback_steps: list[dict[str, Any]],
        fallback_version: int,
        fallback_updated_at: str,
    ) -> list[dict[str, Any]]:
        raw_values = value if isinstance(value, list) else []
        by_version: dict[int, dict[str, Any]] = {}
        for row in raw_values:
            if not isinstance(row, dict):
                continue
            version = _normalize_workflow_page_step_version(row.get("version"))
            steps = _normalize_workflow_template_steps(row.get("steps"))
            if not steps:
                continue
            updated_at = (
                _normalize_workflow_template_timestamp(row.get("updated_at"))
                or fallback_updated_at
                or _workflow_template_timestamp_now()
            )
            by_version[version] = {
                "version": version,
                "steps": steps,
                "updated_at": updated_at,
            }

        normalized_fallback_steps = _normalize_workflow_template_steps(fallback_steps)
        fallback_version = _normalize_workflow_page_step_version(fallback_version)
        if normalized_fallback_steps:
            by_version[fallback_version] = {
                "version": fallback_version,
                "steps": normalized_fallback_steps,
                "updated_at": fallback_updated_at or _workflow_template_timestamp_now(),
            }

        normalized = sorted(by_version.values(), key=lambda row: int(row.get("version") or 0))
        if len(normalized) > WORKFLOW_PAGE_MAX_STEP_VERSIONS:
            normalized = normalized[-WORKFLOW_PAGE_MAX_STEP_VERSIONS:]
        return normalized


    def _read_workflow_pages(*, include_archived: bool = True) -> list[dict[str, Any]]:
        raw = core._read_json(_workflow_pages_path())
        if not isinstance(raw, list):
            return []
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in raw:
            if not isinstance(row, dict):
                continue
            page_id = _normalize_workflow_page_id(row.get("id"))
            if not page_id or page_id in seen:
                continue
            name = _normalize_workflow_page_name(row.get("name"))
            if not name:
                continue
            year = core._safe_non_negative_int(row.get("year"), default=0)
            month = core._safe_non_negative_int(row.get("month"), default=0)
            if not 2000 <= year <= 3000 or not 1 <= month <= 12:
                continue
            source_urls = _normalize_workflow_template_source_urls(row.get("source_urls"))
            mfcloud_url = _normalize_workflow_template_url(row.get("mfcloud_url"))
            if not source_urls and mfcloud_url:
                source_urls = [mfcloud_url]
            if source_urls:
                mfcloud_url = source_urls[0]
            else:
                mfcloud_url = ""
            steps = _normalize_workflow_template_steps(row.get("steps"))
            archived = bool(row.get("archived"))
            archived_at = _normalize_workflow_template_timestamp(row.get("archived_at")) if archived else ""
            if archived and not include_archived:
                continue
            created_at = (
                _normalize_workflow_template_timestamp(row.get("created_at"))
                or _workflow_template_timestamp_now()
            )
            updated_at = (
                _normalize_workflow_template_timestamp(row.get("updated_at"))
                or _workflow_template_timestamp_now()
            )
            step_version = _normalize_workflow_page_step_version(row.get("step_version"))
            step_versions = _normalize_workflow_page_step_versions(
                row.get("step_versions"),
                fallback_steps=steps,
                fallback_version=step_version,
                fallback_updated_at=updated_at,
            )
            if step_versions:
                by_version = {
                    _normalize_workflow_page_step_version(item.get("version")): item
                    for item in step_versions
                    if isinstance(item, dict)
                }
                selected_step_version = _normalize_workflow_page_step_version(step_version)
                selected_steps_row = by_version.get(selected_step_version)
                if selected_steps_row is None:
                    selected_steps_row = step_versions[-1]
                    selected_step_version = _normalize_workflow_page_step_version(
                        selected_steps_row.get("version")
                    )
                steps = _normalize_workflow_template_steps(selected_steps_row.get("steps"))
                step_version = selected_step_version
            rows.append(
                {
                    "id": page_id,
                    "name": name,
                    "subheading": _normalize_workflow_page_subheading(row.get("subheading")),
                    "year": year,
                    "month": month,
                    "mfcloud_url": mfcloud_url,
                    "source_urls": source_urls,
                    "steps": steps,
                    "notes": _normalize_workflow_template_notes(row.get("notes")),
                    "rakuten_orders_url": _normalize_workflow_template_url(row.get("rakuten_orders_url")) or "",
                    "source_template_id": _normalize_workflow_template_id(row.get("source_template_id")),
                    "step_version": step_version,
                    "step_versions": step_versions,
                    "archived": archived,
                    "archived_at": archived_at,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
            seen.add(page_id)
        rows.sort(
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
        if len(rows) > WORKFLOW_PAGE_MAX_ITEMS:
            rows = rows[:WORKFLOW_PAGE_MAX_ITEMS]
        return rows


    def _write_workflow_pages(rows: list[dict[str, Any]]) -> None:
        if len(rows) > WORKFLOW_PAGE_MAX_ITEMS:
            rows = rows[:WORKFLOW_PAGE_MAX_ITEMS]
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            page_id = _normalize_workflow_page_id(row.get("id"))
            if not page_id:
                continue
            name = _normalize_workflow_page_name(row.get("name"))
            if not name:
                continue
            year = core._safe_non_negative_int(row.get("year"), default=0)
            month = core._safe_non_negative_int(row.get("month"), default=0)
            if not 2000 <= year <= 3000 or not 1 <= month <= 12:
                continue
            source_urls = _normalize_workflow_template_source_urls(row.get("source_urls"))
            mfcloud_url = _normalize_workflow_template_url(row.get("mfcloud_url"))
            if not source_urls and mfcloud_url:
                source_urls = [mfcloud_url]
            if source_urls:
                mfcloud_url = source_urls[0]
            else:
                mfcloud_url = ""
            steps = _normalize_workflow_template_steps(row.get("steps"))
            created_at = str(row.get("created_at") or _workflow_template_timestamp_now())
            updated_at = str(row.get("updated_at") or _workflow_template_timestamp_now())
            step_version = _normalize_workflow_page_step_version(row.get("step_version"))
            step_versions = _normalize_workflow_page_step_versions(
                row.get("step_versions"),
                fallback_steps=steps,
                fallback_version=step_version,
                fallback_updated_at=updated_at,
            )
            if step_versions:
                by_version = {
                    _normalize_workflow_page_step_version(item.get("version")): item
                    for item in step_versions
                    if isinstance(item, dict)
                }
                selected_step_version = _normalize_workflow_page_step_version(step_version)
                selected_steps_row = by_version.get(selected_step_version)
                if selected_steps_row is None:
                    selected_steps_row = step_versions[-1]
                    selected_step_version = _normalize_workflow_page_step_version(
                        selected_steps_row.get("version")
                    )
                steps = _normalize_workflow_template_steps(selected_steps_row.get("steps"))
                step_version = selected_step_version
            normalized.append(
                {
                    "id": page_id,
                    "name": name,
                    "subheading": _normalize_workflow_page_subheading(row.get("subheading")),
                    "year": year,
                    "month": month,
                    "mfcloud_url": mfcloud_url,
                    "source_urls": source_urls,
                    "steps": steps,
                    "notes": _normalize_workflow_template_notes(row.get("notes")),
                    "rakuten_orders_url": _normalize_workflow_template_url(row.get("rakuten_orders_url")) or "",
                    "source_template_id": _normalize_workflow_template_id(row.get("source_template_id")),
                    "step_version": step_version,
                    "step_versions": step_versions,
                    "archived": bool(row.get("archived")),
                    "archived_at": _normalize_workflow_template_timestamp(row.get("archived_at")) if bool(row.get("archived")) else "",
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        core._write_json(_workflow_pages_path(), normalized)


    def _workflow_page_name_taken(rows: list[dict[str, Any]], name: str) -> bool:
        normalized_name = str(name or "").strip().lower()
        if not normalized_name:
            return False
        for row in rows:
            if str(row.get("name") or "").strip().lower() == normalized_name:
                return True
        return False


    def _normalize_workflow_page_payload(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
        name = _normalize_workflow_page_name(payload.get("name"))
        if not name:
            raise HTTPException(status_code=400, detail="Workflow page name is required.")
        year = core._safe_non_negative_int(payload.get("year"), default=0)
        month = core._safe_non_negative_int(payload.get("month"), default=0)

        source_urls = _normalize_workflow_template_source_urls(payload.get("source_urls"))
        mfcloud_url = _normalize_workflow_template_url(payload.get("mfcloud_url"))
        if not source_urls and mfcloud_url:
            source_urls = [mfcloud_url]
        if source_urls:
            mfcloud_url = source_urls[0]
        else:
            mfcloud_url = ""

        created_at = _workflow_template_timestamp_now()
        steps = _normalize_workflow_template_steps(payload.get("steps"))
        step_version = 1
        step_versions = _normalize_workflow_page_step_versions(
            payload.get("step_versions"),
            fallback_steps=steps,
            fallback_version=step_version,
            fallback_updated_at=created_at,
        )

        return {
            "id": uuid4().hex[:24],
            "name": name,
            "subheading": _normalize_workflow_page_subheading(payload.get("subheading")),
            "year": year,
            "month": month,
            "mfcloud_url": mfcloud_url,
            "source_urls": source_urls,
            "steps": steps,
            "notes": _normalize_workflow_template_notes(payload.get("notes")),
            "rakuten_orders_url": _normalize_workflow_template_url(payload.get("rakuten_orders_url")) or "",
            "source_template_id": _normalize_workflow_template_id(payload.get("source_template_id")),
            "step_version": step_version,
            "step_versions": step_versions,
            "archived": False,
            "archived_at": "",
            "created_at": created_at,
            "updated_at": created_at,
        }


    def _normalize_workflow_page_update_payload(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

        updates: dict[str, Any] = {}
        if "name" in payload:
            name = _normalize_workflow_page_name(payload.get("name"))
            if not name:
                raise HTTPException(status_code=400, detail="Workflow page name is required.")
            updates["name"] = name
        if "subheading" in payload:
            updates["subheading"] = _normalize_workflow_page_subheading(payload.get("subheading"))
        if "notes" in payload:
            updates["notes"] = _normalize_workflow_template_notes(payload.get("notes"))
        if "rakuten_orders_url" in payload:
            updates["rakuten_orders_url"] = _normalize_workflow_template_url(payload.get("rakuten_orders_url")) or ""
        if "year" in payload:
            year = core._safe_non_negative_int(payload.get("year"), default=0)
            updates["year"] = year
        if "month" in payload:
            month = core._safe_non_negative_int(payload.get("month"), default=0)
            updates["month"] = month
        if "archived" in payload:
            updates["archived"] = bool(payload.get("archived"))
        if "steps" in payload:
            updates["steps"] = _normalize_workflow_template_steps(payload.get("steps"))

        source_urls = None
        if "source_urls" in payload:
            source_urls = _normalize_workflow_template_source_urls(payload.get("source_urls"))
        mfcloud_url_in_payload = "mfcloud_url" in payload
        mfcloud_url = _normalize_workflow_template_url(payload.get("mfcloud_url")) if mfcloud_url_in_payload else None
        if source_urls is not None:
            if not source_urls and mfcloud_url:
                source_urls = [mfcloud_url]
            updates["source_urls"] = source_urls
            updates["mfcloud_url"] = source_urls[0] if source_urls else ""
        elif mfcloud_url_in_payload:
            updates["mfcloud_url"] = mfcloud_url or ""

        return updates

    register_api_workspace_routes(
        router=router,
        actor_from_request=_actor_from_request,
        core=core,
        core_scheduler=core_scheduler,
        read_workspace_state=_read_workspace_state,
        write_workspace_state=_write_workspace_state,
        sanitize_workspace_links=_sanitize_workspace_links,
        merge_workspace_links=_merge_workspace_links,
        sanitize_workspace_pinned_links=_sanitize_workspace_pinned_links,
        merge_workspace_pinned_links=_merge_workspace_pinned_links,
        sanitize_workspace_pinned_link_groups=_sanitize_workspace_pinned_link_groups,
        merge_workspace_pinned_link_groups=_merge_workspace_pinned_link_groups,
        sanitize_workspace_prompts=_sanitize_workspace_prompts,
        merge_workspace_prompts=_merge_workspace_prompts,
        sanitize_workspace_link_notes=_sanitize_workspace_link_notes,
        merge_workspace_link_notes=_merge_workspace_link_notes,
        sanitize_workspace_link_profiles=_sanitize_workspace_link_profiles,
        merge_workspace_link_profiles=_merge_workspace_link_profiles,
        sanitize_workspace_active_prompt_key=_sanitize_workspace_active_prompt_key,
        read_workflow_pages=_read_workflow_pages,
        write_workflow_pages=_write_workflow_pages,
        workflow_page_name_taken=_workflow_page_name_taken,
        normalize_workflow_page_id=_normalize_workflow_page_id,
        workflow_template_timestamp_now=_workflow_template_timestamp_now,
        normalize_workflow_template_timestamp=_normalize_workflow_template_timestamp,
        normalize_workflow_page_payload=_normalize_workflow_page_payload,
        normalize_workflow_page_update_payload=_normalize_workflow_page_update_payload,
        read_workflow_templates=_read_workflow_templates,
        sort_workflow_templates=_sort_workflow_templates,
        template_name_taken=_template_name_taken,
        normalize_workflow_template_payload=_normalize_workflow_template_payload,
        normalize_workflow_template_id=_normalize_workflow_template_id,
        write_workflow_templates=_write_workflow_templates,
        workflow_template_max_items=WORKFLOW_TEMPLATE_MAX_ITEMS,
        workflow_page_max_items=WORKFLOW_PAGE_MAX_ITEMS,
        workflow_template_sort_options=WORKFLOW_TEMPLATE_SORT_OPTIONS,
        workflow_template_max_search_chars=WORKFLOW_TEMPLATE_MAX_SEARCH_CHARS,
    )


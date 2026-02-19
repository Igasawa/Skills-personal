from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse


ActorFromRequest = Callable[[Request], dict[str, str]]


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
        if page_id:
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

        return JSONResponse(
            {"status": "ok", "template": saved, "count": len(existing), "updated": updated},
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

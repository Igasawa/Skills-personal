from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services import core

ARCHIVE_SNAPSHOT_RE = re.compile(r"^\d{8}_\d{6}$")
WORKFLOW_TEMPLATE_SIDEBAR_LABEL_LIMIT = 38
WORKFLOW_TEMPLATE_SIDEBAR_LINK_LIMIT = 30
WORKFLOW_PAGE_SIDEBAR_LABEL_LIMIT = 38
WORKFLOW_PAGE_SIDEBAR_LINK_LIMIT = 60
WORKFLOW_TEMPLATE_STEP_DEFAULT_ACTION = "preflight"
WORKFLOW_TEMPLATE_STEP_DEFAULT_TIMER_MINUTES = 5
WORKFLOW_TEMPLATE_STEP_MIN_TIMER_MINUTES = 1
WORKFLOW_TEMPLATE_STEP_MAX_TIMER_MINUTES = 7 * 24 * 60
WORKFLOW_TEMPLATE_STEP_MAX_EXECUTION_LOG_ITEMS = 20
WORKFLOW_TEMPLATE_STEP_MAX_EXECUTION_LOG_MESSAGE_CHARS = 200
WORKFLOW_TEMPLATE_REQUIRED_STEP_ACTIONS = (
    "preflight",
    "mf_reconcile",
)
WORKFLOW_TEMPLATE_REQUIRED_STEP_TITLES = {
    "preflight": "手順0 準備（ログイン確認・MF連携更新）",
    "mf_reconcile": "手順5 MF突合・下書き作成",
}
WORKFLOW_TEMPLATE_FALLBACK_ACTION_ORDER = (
    "preflight",
    "amazon_download",
    "amazon_print",
    "rakuten_download",
    "rakuten_print",
    "provider_ingest",
    "mf_bulk_upload_task",
    "mf_reconcile",
    "month_close",
    "preflight_mf",
)
WORKFLOW_TEMPLATE_ALLOWED_STEP_ACTIONS = (
    "preflight",
    "preflight_mf",
    "amazon_download",
    "rakuten_download",
    "amazon_print",
    "rakuten_print",
    "provider_ingest",
    "mf_bulk_upload_task",
    "mf_reconcile",
    "month_close",
)
WORKFLOW_PAGE_MAX_STEP_VERSIONS = 30
DEFAULT_SIDEBAR_LINKS = [
    {"href": "/workspace", "label": "HOME", "tab": "workspace", "section": "home"},
    {"href": "/", "label": "WorkFlow：経費精算", "tab": "wizard", "section": "workflow"},
    {"href": "/expense-workflow-copy", "label": "WF作成テンプレート", "tab": "wizard-copy", "section": "admin"},
    {"href": "/errors", "label": "\u7ba1\u7406\u30bb\u30f3\u30bf\u30fc", "tab": "errors", "section": "admin"},
]
ERRORS_INITIAL_TAB_VALUES = {
    "incidents",
    "document-update",
    "document-targets",
    "workflow-archive",
    "kil-review",
}


def _workflow_template_store() -> Path:
    return core._artifact_root() / "_workflow_templates" / "workflow_templates.json"


def _workflow_pages_store() -> Path:
    return core._artifact_root() / "_workflow_pages" / "workflow_pages.json"


def _read_workflow_pages(*, include_archived: bool = False) -> list[dict[str, object]]:
    raw = core._read_json(_workflow_pages_store())
    if not isinstance(raw, list):
        return []

    pages: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        page_id = str(row.get("id") or "").strip()
        if not page_id or page_id in seen:
            continue
        try:
            year = int(row.get("year"))
            month = int(row.get("month"))
        except Exception:
            continue
        if not 2000 <= year <= 3000 or not 1 <= month <= 12:
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        source_urls: list[str] = []
        seen_urls: set[str] = set()
        raw_source_urls = row.get("source_urls") if isinstance(row.get("source_urls"), list) else []
        for source_url in raw_source_urls:
            url = str(source_url or "").strip()
            if not url:
                continue
            key = url.lower()
            if key in seen_urls:
                continue
            seen_urls.add(key)
            source_urls.append(url)
        mfcloud_url = str(row.get("mfcloud_url") or "").strip()
        if not source_urls and mfcloud_url:
            source_urls = [mfcloud_url]
        if source_urls:
            mfcloud_url = source_urls[0]
        archived = bool(row.get("archived"))
        archived_at = str(row.get("archived_at") or "").strip() if archived else ""
        if archived and not include_archived:
            continue
        steps = _normalize_template_steps_for_view(row.get("steps"))
        created_at = str(row.get("created_at") or "").strip()
        updated_at = str(row.get("updated_at") or "").strip()
        step_version = core._safe_non_negative_int(row.get("step_version"), default=1)
        if step_version < 1:
            step_version = 1
        step_versions = _normalize_step_versions_for_view(
            row.get("step_versions"),
            fallback_steps=steps,
            fallback_version=step_version,
            fallback_updated_at=updated_at,
        )
        if step_versions:
            by_version = {
                core._safe_non_negative_int(item.get("version"), default=1): item
                for item in step_versions
                if isinstance(item, dict)
            }
            current = by_version.get(step_version) or step_versions[-1]
            steps = _normalize_template_steps_for_view(current.get("steps"))
            step_version = core._safe_non_negative_int(current.get("version"), default=step_version)
            if step_version < 1:
                step_version = 1

        pages.append(
            {
                "id": page_id,
                "name": name,
                "subheading": str(row.get("subheading") or "").strip(),
                "year": year,
                "month": month,
                "mfcloud_url": mfcloud_url,
                "source_urls": source_urls,
                "steps": steps,
                "notes": str(row.get("notes") or ""),
                "rakuten_orders_url": str(row.get("rakuten_orders_url") or ""),
                "source_template_id": str(row.get("source_template_id") or "").strip(),
                "step_version": step_version,
                "step_versions": step_versions,
                "archived": archived,
                "archived_at": archived_at,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
        seen.add(page_id)

    pages.sort(
        key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
        reverse=True,
    )
    return pages


def _normalize_template_steps_for_view_legacy(value: Any) -> list[dict[str, Any]]:
    raw_values = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    seen_actions: set[str] = set()
    seen_ids: set[str] = set()
    fallback_index = 0
    for index, row in enumerate(raw_values):
        raw_id = ""
        raw_title = ""
        raw_action = ""
        raw_timer_minutes: Any = None
        if isinstance(row, dict):
            raw_id = str(row.get("id") or "").strip()
            raw_title = row.get("title") or row.get("name")
            raw_action = str(row.get("action") or "").strip()
            if "timer_minutes" in row:
                raw_timer_minutes = row.get("timer_minutes")
            elif "timer" in row:
                raw_timer_minutes = row.get("timer")
        else:
            raw_title = row
        action = raw_action if raw_action in WORKFLOW_TEMPLATE_ALLOWED_STEP_ACTIONS else ""
        if not action:
            for candidate in WORKFLOW_TEMPLATE_FALLBACK_ACTION_ORDER[fallback_index:]:
                if candidate not in seen_actions and candidate in WORKFLOW_TEMPLATE_ALLOWED_STEP_ACTIONS:
                    action = candidate
                    break
            if not action:
                action = WORKFLOW_TEMPLATE_STEP_DEFAULT_ACTION
        fallback_index += 1
        if action in seen_actions:
            continue

        title = " ".join(str(raw_title or "").strip().split())
        if not title:
            title = WORKFLOW_TEMPLATE_REQUIRED_STEP_TITLES.get(action, f"手順{index + 1}")
        timer_minutes = core._safe_non_negative_int(raw_timer_minutes, default=WORKFLOW_TEMPLATE_STEP_DEFAULT_TIMER_MINUTES)
        if timer_minutes > WORKFLOW_TEMPLATE_STEP_MAX_TIMER_MINUTES:
            timer_minutes = WORKFLOW_TEMPLATE_STEP_MAX_TIMER_MINUTES
        step_id = raw_id.strip()
        if not step_id:
            step_id = f"step-{index + 1}"
        while step_id in seen_ids:
            step_id = f"{step_id}-{len(seen_ids) + 1}"
        seen_ids.add(step_id)
        seen_actions.add(action)
        normalized.append({"id": step_id, "title": title, "action": action, "timer_minutes": timer_minutes})

    for required_action in WORKFLOW_TEMPLATE_REQUIRED_STEP_ACTIONS:
        if required_action in seen_actions:
            continue
        step_id = f"step-required-{required_action}"
        while step_id in seen_ids:
            step_id = f"{step_id}-{len(seen_ids) + 1}"
        seen_ids.add(step_id)
        normalized.append(
            {
                "id": step_id,
                "title": WORKFLOW_TEMPLATE_REQUIRED_STEP_TITLES.get(required_action, required_action),
                "action": required_action,
                "timer_minutes": WORKFLOW_TEMPLATE_STEP_DEFAULT_TIMER_MINUTES,
            }
        )
        seen_actions.add(required_action)
    return normalized


def _normalize_template_steps_for_view(value: Any) -> list[dict[str, Any]]:
    raw_values = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    seen_actions: set[str] = set()
    seen_ids: set[str] = set()
    fallback_index = 0

    def _normalize_auto_run(raw: Any) -> bool:
        if isinstance(raw, bool):
            return raw
        text = str(raw or "").strip().lower()
        if not text:
            return False
        return text in {"1", "true", "yes", "on"}

    def _normalize_execution_log(raw: Any) -> list[dict[str, str]]:
        rows = raw if isinstance(raw, list) else []
        out: list[dict[str, str]] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            result_raw = str(item.get("result") or "").strip().lower()
            result = "failed" if result_raw == "failed" else "success"
            executed_at = str(item.get("executed_at") or item.get("executedAt") or "").strip()
            message = str(item.get("message") or "").strip()[:WORKFLOW_TEMPLATE_STEP_MAX_EXECUTION_LOG_MESSAGE_CHARS]
            if not executed_at and not message:
                continue
            out.append(
                {
                    "executed_at": executed_at,
                    "result": result,
                    "message": message,
                }
            )
            if len(out) >= WORKFLOW_TEMPLATE_STEP_MAX_EXECUTION_LOG_ITEMS:
                break
        return out

    for index, row in enumerate(raw_values):
        raw_id = ""
        raw_title = ""
        raw_action = ""
        raw_timer_minutes: Any = None
        raw_order: Any = index + 1
        raw_auto_run: Any = False
        raw_execution_log: Any = []
        if isinstance(row, dict):
            raw_id = str(row.get("id") or "").strip()
            raw_title = row.get("title") or row.get("name")
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
        else:
            raw_title = row

        action = raw_action if raw_action in WORKFLOW_TEMPLATE_ALLOWED_STEP_ACTIONS else ""
        if not action:
            for candidate in WORKFLOW_TEMPLATE_FALLBACK_ACTION_ORDER[fallback_index:]:
                if candidate not in seen_actions and candidate in WORKFLOW_TEMPLATE_ALLOWED_STEP_ACTIONS:
                    action = candidate
                    break
            if not action:
                action = WORKFLOW_TEMPLATE_STEP_DEFAULT_ACTION
        fallback_index += 1
        if action in seen_actions:
            continue

        title = " ".join(str(raw_title or "").strip().split())
        if not title:
            title = WORKFLOW_TEMPLATE_REQUIRED_STEP_TITLES.get(action, f"Task {index + 1}")

        timer_minutes: int | None = None
        if raw_timer_minutes is not None and str(raw_timer_minutes).strip():
            timer_minutes = core._safe_non_negative_int(raw_timer_minutes, default=0)
            if timer_minutes > WORKFLOW_TEMPLATE_STEP_MAX_TIMER_MINUTES:
                timer_minutes = WORKFLOW_TEMPLATE_STEP_MAX_TIMER_MINUTES

        auto_run = _normalize_auto_run(raw_auto_run)
        if auto_run and (timer_minutes is None or timer_minutes < WORKFLOW_TEMPLATE_STEP_MIN_TIMER_MINUTES):
            timer_minutes = WORKFLOW_TEMPLATE_STEP_DEFAULT_TIMER_MINUTES

        order = core._safe_non_negative_int(raw_order, default=index + 1)
        if order < 1:
            order = index + 1

        step_id = raw_id.strip()
        if not step_id:
            step_id = f"step-{index + 1}"
        while step_id in seen_ids:
            step_id = f"{step_id}-{len(seen_ids) + 1}"
        seen_ids.add(step_id)
        seen_actions.add(action)
        normalized.append(
            {
                "id": step_id,
                "order": order,
                "title": title,
                "action": action,
                "auto_run": auto_run,
                "timer_minutes": timer_minutes,
                "execution_log": _normalize_execution_log(raw_execution_log),
            }
        )

    for required_action in WORKFLOW_TEMPLATE_REQUIRED_STEP_ACTIONS:
        if required_action in seen_actions:
            continue
        step_id = f"step-required-{required_action}"
        while step_id in seen_ids:
            step_id = f"{step_id}-{len(seen_ids) + 1}"
        seen_ids.add(step_id)
        normalized.append(
            {
                "id": step_id,
                "order": len(normalized) + 1,
                "title": WORKFLOW_TEMPLATE_REQUIRED_STEP_TITLES.get(required_action, required_action),
                "action": required_action,
                "auto_run": False,
                "timer_minutes": None,
                "execution_log": [],
            }
        )
        seen_actions.add(required_action)

    for order, row in enumerate(normalized, start=1):
        row["order"] = order
    return normalized


def _normalize_step_versions_for_view(
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
        version = core._safe_non_negative_int(row.get("version"), default=0)
        if version < 1:
            continue
        steps = _normalize_template_steps_for_view(row.get("steps"))
        if not steps:
            continue
        updated_at = str(row.get("updated_at") or "").strip() or fallback_updated_at
        by_version[version] = {
            "version": version,
            "steps": steps,
            "updated_at": updated_at,
        }
    normalized_fallback_steps = _normalize_template_steps_for_view(fallback_steps)
    if normalized_fallback_steps:
        fallback_ver = core._safe_non_negative_int(fallback_version, default=1)
        if fallback_ver < 1:
            fallback_ver = 1
        by_version[fallback_ver] = {
            "version": fallback_ver,
            "steps": normalized_fallback_steps,
            "updated_at": fallback_updated_at,
        }
    normalized = sorted(by_version.values(), key=lambda row: int(row.get("version") or 0))
    if len(normalized) > WORKFLOW_PAGE_MAX_STEP_VERSIONS:
        normalized = normalized[-WORKFLOW_PAGE_MAX_STEP_VERSIONS:]
    return normalized


def _read_workflow_templates() -> list[dict[str, object]]:
    raw = core._read_json(_workflow_template_store())
    if not isinstance(raw, list):
        return []

    templates: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        template_id = str(row.get("id") or "").strip()
        if not template_id or template_id in seen:
            continue
        try:
            year = int(row.get("year"))
        except Exception:
            year = 0
        try:
            month = int(row.get("month"))
        except Exception:
            month = 0
        source_urls = []
        seen_urls: set[str] = set()
        raw_source_urls = row.get("source_urls") if isinstance(row.get("source_urls"), list) else []
        for source_url in raw_source_urls:
            url = str(source_url or "").strip()
            if not url:
                continue
            key = url.lower()
            if key in seen_urls:
                continue
            seen_urls.add(key)
            source_urls.append(url)
        mfcloud_url = str(row.get("mfcloud_url") or "").strip()
        if not source_urls and mfcloud_url:
            source_urls = [mfcloud_url]
        if source_urls:
            mfcloud_url = source_urls[0]
        templates.append(
            {
                "id": template_id,
                "name": str(row.get("name") or "").strip(),
                "year": year,
                "month": month,
                "mfcloud_url": mfcloud_url,
                "source_urls": source_urls,
                "steps": _normalize_template_steps_for_view(row.get("steps")),
                "notes": str(row.get("notes") or ""),
                "subheading": str(row.get("subheading") or "").strip(),
                "rakuten_orders_url": str(row.get("rakuten_orders_url") or ""),
                "created_at": str(row.get("created_at") or ""),
                "updated_at": str(row.get("updated_at") or ""),
            }
        )
        seen.add(template_id)

    templates.sort(
        key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
        reverse=True,
    )
    return templates


def _workflow_template_sidebar_links() -> list[dict[str, object]]:
    links: list[dict[str, object]] = []
    for template in _read_workflow_templates()[:WORKFLOW_TEMPLATE_SIDEBAR_LINK_LIMIT]:
        template_id = str(template.get("id") or "").strip()
        label = str(template.get("name") or "ワークフロー作成テンプレート").strip()[:WORKFLOW_TEMPLATE_SIDEBAR_LABEL_LIMIT]
        if not template_id:
            continue
        year = int(template.get("year") or 0)
        month = int(template.get("month") or 0)
        if 1 <= month <= 12 and 2000 <= year <= 3000:
            label = f"{label} ({year:04d}-{month:02d})"
        links.append(
            {
                "href": f"/expense-workflow-copy?template={template_id}",
                "label": label,
                "tab": "wizard-copy",
                "section": "admin",
            }
        )

    return links


def _workflow_page_sidebar_links() -> list[dict[str, object]]:
    links: list[dict[str, object]] = []
    for page in _read_workflow_pages(include_archived=False)[:WORKFLOW_PAGE_SIDEBAR_LINK_LIMIT]:
        page_id = str(page.get("id") or "").strip()
        label = str(page.get("name") or "WorkFlow").strip()[:WORKFLOW_PAGE_SIDEBAR_LABEL_LIMIT]
        if not page_id:
            continue
        year = int(page.get("year") or 0)
        month = int(page.get("month") or 0)
        if 1 <= month <= 12 and 2000 <= year <= 3000:
            label = f"{label} ({year:04d}-{month:02d})"
        links.append(
            {
                "href": f"/workflow/{page_id}",
                "label": label,
                "tab": "wizard",
                "section": "workflow",
            }
        )
    return links


def _lookup_workflow_template(template_id: str | None) -> dict[str, object] | None:
    if not template_id:
        return None
    wanted = str(template_id).strip()
    if not wanted:
        return None
    for template in _read_workflow_templates():
        if str(template.get("id")) == wanted:
            return template
    return None


def _lookup_workflow_page(workflow_id: str | None) -> dict[str, object] | None:
    if not workflow_id:
        return None
    wanted = str(workflow_id).strip()
    if not wanted:
        return None
    for workflow_page in _read_workflow_pages(include_archived=False):
        if str(workflow_page.get("id")) == wanted:
            return workflow_page
    return None


def _dashboard_context(active_tab: str) -> dict[str, object]:
    links = list(DEFAULT_SIDEBAR_LINKS)
    for link in _workflow_page_sidebar_links():
        links.append(link)
    deduped = []
    seen = set()
    for link in links:
        href = str(link.get("href", "")).strip()
        if href in seen:
            continue
        deduped.append(link)
        seen.add(href)
    return {
        "active_tab": active_tab,
        "sidebar_links": deduped,
    }


def _sanitize_form_defaults_year_month(defaults: dict[str, object]) -> dict[str, object]:
    year = core._safe_non_negative_int(defaults.get("year"), default=0)
    month = core._safe_non_negative_int(defaults.get("month"), default=0)

    if year < 2000 or year > 3000:
        year = 2000
    if month < 1 or month > 12:
        month = 1

    defaults["year"] = year
    defaults["month"] = month
    return defaults


def create_pages_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/favicon.ico", include_in_schema=False)
    def favicon() -> RedirectResponse:
        return RedirectResponse(url="/static/favicon.svg")

    @router.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        defaults = _sanitize_form_defaults_year_month(core._resolve_form_defaults())
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                **_dashboard_context("wizard"),
                "defaults": defaults,
                "ax_home": str(core._ax_home()),
            },
        )

    @router.get("/workflow/{workflow_id}", response_class=HTMLResponse)
    def workflow_page(request: Request, workflow_id: str) -> HTMLResponse:
        page_config = _lookup_workflow_page(workflow_id)
        if page_config is None:
            raise HTTPException(status_code=404, detail="Workflow page not found.")
        defaults = _sanitize_form_defaults_year_month(core._resolve_form_defaults())
        try:
            defaults["year"] = int(page_config.get("year"))
        except Exception:
            pass
        try:
            defaults["month"] = int(page_config.get("month"))
        except Exception:
            pass
        defaults = _sanitize_form_defaults_year_month(defaults)
        defaults["mfcloud_url"] = str(page_config.get("mfcloud_url") or "")
        defaults["notes"] = str(page_config.get("notes") or "")
        defaults["rakuten_orders_url"] = str(page_config.get("rakuten_orders_url") or "")
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                **_dashboard_context("wizard"),
                "defaults": defaults,
                "workflow_page": page_config,
                "ax_home": str(core._ax_home()),
            },
        )

    @router.get("/expense-workflow-copy", response_class=HTMLResponse)
    def workflow_copy(
        request: Request,
        template: str | None = Query(default=None),
        template_id: str | None = Query(default=None),
    ) -> HTMLResponse:
        defaults = _sanitize_form_defaults_year_month(core._resolve_form_defaults())
        resolved_template_id = template or template_id
        workflow_template = _lookup_workflow_template(resolved_template_id)
        if workflow_template is None:
            template_rows = _read_workflow_templates()
            workflow_template = template_rows[0] if template_rows else None

        template_mode = "edit"
        workflow_template_source_id = str(workflow_template.get("id") or "") if workflow_template else ""
        page_template_id = workflow_template_source_id
        if workflow_template:
            defaults["mfcloud_url"] = str(workflow_template.get("mfcloud_url") or "")
            defaults["notes"] = str(workflow_template.get("notes") or defaults["notes"])
            defaults["rakuten_orders_url"] = str(workflow_template.get("rakuten_orders_url") or "")
        return templates.TemplateResponse(
            request,
            "expense_workflow_copy.html",
            {
                **_dashboard_context("wizard-copy"),
                "defaults": defaults,
                "template_id": page_template_id,
                "template_source_id": workflow_template_source_id,
                "template_mode": template_mode,
                "template_updated_at": str(workflow_template.get("updated_at") or "") if workflow_template else "",
                "workflow_template": workflow_template,
                "ax_home": str(core._ax_home()),
            },
        )

    @router.get("/workflow-pages/archived")
    def workflow_pages_archived() -> RedirectResponse:
        return RedirectResponse(url="/errors?tab=workflow-archive")

    @router.get("/status", response_class=HTMLResponse)
    def status(request: Request) -> HTMLResponse:
        artifacts = core._scan_artifacts()
        archive_history = core._scan_archive_history(limit=20)
        jobs = core._scan_run_jobs()
        running_job = core._get_latest_running_job()
        latest_job = jobs[0] if jobs else None
        latest_job_ym = None
        if isinstance(latest_job, dict):
            params = latest_job.get("params") if isinstance(latest_job.get("params"), dict) else {}
            try:
                y = int(params.get("year"))
                m = int(params.get("month"))
                if 1 <= m <= 12:
                    latest_job_ym = f"{y:04d}-{m:02d}"
            except Exception:
                latest_job_ym = None

        return templates.TemplateResponse(
            request,
            "status.html",
            {
                **_dashboard_context("status"),
                "artifacts": artifacts,
                "archive_history": archive_history,
                "latest_job": latest_job,
                "latest_job_ym": latest_job_ym,
                "running_job": running_job,
                "ax_home": str(core._ax_home()),
            },
        )

    @router.get("/kil-review")
    def kil_review() -> RedirectResponse:
        return RedirectResponse(url="/errors?tab=kil-review")

    @router.get("/workspace", response_class=HTMLResponse)
    def workspace(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "workspace.html",
            {
                **_dashboard_context("workspace"),
                "ax_home": str(core._ax_home()),
            },
        )

    @router.get("/errors", response_class=HTMLResponse)
    def errors(
        request: Request,
        tab: str | None = Query(default=None),
    ) -> HTMLResponse:
        normalized_tab = str(tab or "").strip()
        if normalized_tab not in ERRORS_INITIAL_TAB_VALUES:
            normalized_tab = "incidents"
        return templates.TemplateResponse(
            request,
            "errors.html",
            {
                **_dashboard_context("errors"),
                "errors_initial_tab": normalized_tab,
                "ax_home": str(core._ax_home()),
            },
        )

    @router.get("/runs/{ym}", response_class=HTMLResponse)
    def run_detail(request: Request, ym: str) -> HTMLResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym
        if not root.exists():
            raise HTTPException(status_code=404, detail="Run not found.")

        reports_dir = root / "reports"
        missing_json = reports_dir / "missing_evidence_candidates.json"
        data = core._read_json(missing_json) or {}
        rows = data.get("rows") if isinstance(data, dict) else []
        counts = data.get("counts") if isinstance(data, dict) else {}
        merged_counts = dict(counts or {})
        merged_counts.update(core._derive_order_counts_from_jsonl(root, ym))
        rows = rows if isinstance(rows, list) else []
        for row in rows:
            mf_use_date = str(row.get("mf_use_date") or "").strip() or None
            row["mf_use_date"] = mf_use_date or "-"
            vendor = str(row.get("mf_vendor") or "")
            memo = str(row.get("mf_memo") or "")
            summary = core._compact_mf_summary(vendor, memo)
            row["mf_summary"] = summary if summary else " ".join([vendor, memo]).strip()
            amount = row.get("mf_amount_yen")
            if isinstance(amount, (int, float)):
                row["mf_amount_label"] = f"{int(amount):,}円"
            elif isinstance(amount, str) and amount.strip().isdigit():
                row["mf_amount_label"] = f"{int(amount.strip()):,}円"
            else:
                row["mf_amount_label"] = "-"

        exclusions = core._load_exclusions(reports_dir)
        orders = core._collect_orders(root, ym, exclusions)
        excluded_count = sum(1 for o in orders if o.get("excluded"))
        included_count = max(0, len(orders) - excluded_count)
        merged_counts.update(
            {
                "manual_excluded_orders": len(exclusions),
                "excluded_orders": excluded_count,
                "included_orders": included_count,
            }
        )
        workflow = core._read_workflow(reports_dir)
        amazon_workflow = workflow.get("amazon") if isinstance(workflow.get("amazon"), dict) else {}
        rakuten_workflow = workflow.get("rakuten") if isinstance(workflow.get("rakuten"), dict) else {}

        amazon_pdfs = list((root / "amazon" / "pdfs").glob("*.pdf")) if (root / "amazon" / "pdfs").exists() else []
        rakuten_pdfs = list((root / "rakuten" / "pdfs").glob("*.pdf")) if (root / "rakuten" / "pdfs").exists() else []

        print_script = reports_dir / "print_all.ps1"
        mf_draft_actions = reports_dir / "mf_draft_create_actions.jsonl"
        amazon_print_manifest = reports_dir / "print_manifest.amazon.json"
        rakuten_print_manifest = reports_dir / "print_manifest.rakuten.json"
        amazon_bulk_print_ready = bool(amazon_workflow.get("print_prepared_at")) and amazon_print_manifest.exists()
        rakuten_bulk_print_ready = bool(rakuten_workflow.get("print_prepared_at")) and rakuten_print_manifest.exists()

        return templates.TemplateResponse(
            request,
            "run.html",
            {
                **_dashboard_context("status"),
                "ym": ym,
                "counts": merged_counts,
                "rows": rows[:50],
                "row_total": len(rows),
                "orders": orders,
                "orders_total": len(orders),
                "excluded_count": excluded_count,
                "included_count": included_count,
                "amazon_pdf_count": len(amazon_pdfs),
                "rakuten_pdf_count": len(rakuten_pdfs),
                "has_reports": reports_dir.exists(),
                "print_script": str(print_script) if print_script.exists() else None,
                "amazon_print_prepared": bool(amazon_workflow.get("print_prepared_at")),
                "rakuten_print_prepared": bool(rakuten_workflow.get("print_prepared_at")),
                "amazon_bulk_print_ready": amazon_bulk_print_ready,
                "rakuten_bulk_print_ready": rakuten_bulk_print_ready,
                "mf_draft_actions_exists": mf_draft_actions.exists(),
                "file_labels": {
                    "missing_csv": "未添付候補CSV",
                    "missing_json": "未添付候補JSON",
                    "monthly_thread": "月次メモ",
                    "run_config": "実行設定",
                    "audit_log": "監査ログ(JSONL)",
                    "mf_draft_actions": "MF下書き作成ログ(JSONL)",
                    "print_script": "印刷用スクリプト",
                },
            },
        )

    @router.get("/runs/{ym}/excluded-pdfs", response_class=HTMLResponse)
    def run_excluded_pdfs(request: Request, ym: str) -> HTMLResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym
        if not root.exists():
            raise HTTPException(status_code=404, detail="Run not found.")
        reports_dir = root / "reports"
        exclusions = core._load_exclusions(reports_dir)
        rows = core._collect_excluded_pdfs(root, ym, exclusions)
        available_months = [
            str(item.get("ym"))
            for item in core._scan_artifacts()
            if isinstance(item, dict) and isinstance(item.get("ym"), str)
        ]
        if ym not in available_months:
            available_months.insert(0, ym)
        available_months = list(dict.fromkeys(available_months))
        amazon_count = sum(1 for r in rows if r.get("source") == "amazon")
        rakuten_count = sum(1 for r in rows if r.get("source") == "rakuten")
        return templates.TemplateResponse(
            request,
            "excluded_pdfs.html",
            {
                **_dashboard_context("status"),
                "ym": ym,
                "rows": rows,
                "total": len(rows),
                "amazon_count": amazon_count,
                "rakuten_count": rakuten_count,
                "available_months": available_months,
            },
        )

    @router.get("/runs/{ym}/archived-receipts", response_class=HTMLResponse)
    def run_archived_receipts(request: Request, ym: str) -> HTMLResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym
        if not root.exists():
            raise HTTPException(status_code=404, detail="Run not found.")

        archive_data = core._scan_archived_receipts(root)
        available_months = [
            str(item.get("ym"))
            for item in core._scan_artifacts()
            if isinstance(item, dict) and isinstance(item.get("ym"), str)
        ]
        if ym not in available_months:
            available_months.insert(0, ym)
        available_months = list(dict.fromkeys(available_months))
        return templates.TemplateResponse(
            request,
            "archive_receipts.html",
            {
                **_dashboard_context("status"),
                "ym": ym,
                "rows": archive_data.get("rows") if isinstance(archive_data.get("rows"), list) else [],
                "snapshots": archive_data.get("snapshots") if isinstance(archive_data.get("snapshots"), list) else [],
                "total": int(archive_data.get("receipt_count") or 0),
                "snapshot_count": int(archive_data.get("snapshot_count") or 0),
                "amazon_count": int(archive_data.get("amazon_count") or 0),
                "rakuten_count": int(archive_data.get("rakuten_count") or 0),
                "archive_root": str(archive_data.get("archive_root") or ""),
                "available_months": available_months,
            },
        )

    @router.get("/runs/{ym}/archive-receipts", include_in_schema=False)
    def run_archived_receipts_legacy(request: Request, ym: str) -> RedirectResponse:
        ym = core._safe_ym(ym)
        return RedirectResponse(url=str(request.url_for("run_archived_receipts", ym=ym)))

    @router.get("/files/{ym}/{kind}")
    def download_file(ym: str, kind: str) -> FileResponse:
        ym = core._safe_ym(ym)
        root = core._artifact_root() / ym
        if not root.exists():
            raise HTTPException(status_code=404, detail="Run not found.")

        mapping = {
            "missing_csv": root / "reports" / "missing_evidence_candidates.csv",
            "missing_json": root / "reports" / "missing_evidence_candidates.json",
            "monthly_thread": root / "reports" / "monthly_thread.md",
            "run_config": root / "run_config.resolved.json",
            "audit_log": root / "reports" / "audit_log.jsonl",
            "mf_draft_actions": root / "reports" / "mf_draft_create_actions.jsonl",
            "print_script": root / "reports" / "print_all.ps1",
        }
        if kind not in mapping:
            raise HTTPException(status_code=404, detail="File not found.")
        path = mapping[kind]
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(path)

    @router.get("/files/{ym}/pdf/{source}/{filename}")
    def download_pdf(ym: str, source: str, filename: str) -> FileResponse:
        ym = core._safe_ym(ym)
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=404, detail="File not found.")
        if not filename or not core.SAFE_NAME_RE.match(filename) or not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=404, detail="File not found.")
        root = core._artifact_root() / ym
        path = core._resolve_pdf_path(root, source, filename)
        if not path:
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(path, media_type="application/pdf", filename=Path(path).name)

    @router.get("/files/{ym}/archive/{snapshot}/{source}/{filename}")
    def download_archived_pdf(ym: str, snapshot: str, source: str, filename: str) -> FileResponse:
        ym = core._safe_ym(ym)
        if source not in {"amazon", "rakuten"}:
            raise HTTPException(status_code=404, detail="File not found.")
        if not ARCHIVE_SNAPSHOT_RE.match(str(snapshot or "")):
            raise HTTPException(status_code=404, detail="File not found.")
        if not filename or not core.SAFE_NAME_RE.match(filename) or not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=404, detail="File not found.")

        root = core._artifact_root() / ym
        base_dir = (root / "archive" / snapshot / source / "pdfs").resolve()
        path = (base_dir / filename).resolve()
        try:
            path.relative_to(base_dir)
        except Exception:
            raise HTTPException(status_code=404, detail="File not found.")
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(path, media_type="application/pdf", filename=Path(path).name)

    return router

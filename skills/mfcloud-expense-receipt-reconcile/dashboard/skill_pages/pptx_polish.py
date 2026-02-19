from __future__ import annotations

from collections.abc import Callable
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import core


SIDEBAR_LINK = {
    "href": "/pptx-polish",
    "label": "PowerPoint整形",
    "tab": "pptx-polish",
    "section": "admin",
}


def get_sidebar_links() -> list[dict[str, object]]:
    return [dict(SIDEBAR_LINK)]


def register_routes(
    router: APIRouter,
    templates: Jinja2Templates,
    dashboard_context: Callable[[str], dict[str, object]],
) -> None:
    @router.get("/pptx-polish", response_class=HTMLResponse)
    def pptx_polish(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "pptx_polish.html",
            {
                **dashboard_context("pptx-polish"),
                "ax_home": str(core._ax_home()),
            },
        )

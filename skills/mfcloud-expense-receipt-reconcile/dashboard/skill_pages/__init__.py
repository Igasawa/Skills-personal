from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.templating import Jinja2Templates

from . import pptx_polish


def collect_skill_sidebar_links() -> list[dict[str, object]]:
    return [*pptx_polish.get_sidebar_links()]


def register_skill_pages(
    *,
    router: APIRouter,
    templates: Jinja2Templates,
    dashboard_context: Callable[[str], dict[str, object]],
) -> None:
    pptx_polish.register_routes(
        router=router,
        templates=templates,
        dashboard_context=dashboard_context,
    )

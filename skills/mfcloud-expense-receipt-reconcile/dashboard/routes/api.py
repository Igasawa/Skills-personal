from __future__ import annotations

import subprocess
import sys
from typing import Any

from fastapi import APIRouter
from services import core

from .api_helpers import (
    _actor_from_request,
    _error_reports_root,
    _extract_incident_year_month,
    _provider_source_status_for_ym,
    _review_kil_script_path,
    _run_error_tool,
    _safe_incident_id,
    _try_year_month,
)
from .api_folder_endpoints import register_api_folder_endpoints
from .api_kil_review_routes import register_api_kil_review_routes
from .api_print_endpoints import register_api_print_endpoints
from .api_run_endpoints import register_api_run_endpoints
from .api_workflow_endpoints import register_api_workflow_endpoints
from .api_runs import register_api_run_routes as register_builtin_api_run_routes


def create_api_router() -> APIRouter:
    router = APIRouter()

    def _provider_source_status_for_ym_proxy(year: int, month: int) -> dict[str, Any]:
        return _provider_source_status_for_ym(year, month)

    register_api_folder_endpoints(
        router=router,
        provider_source_status_for_ym=_provider_source_status_for_ym_proxy,
    )
    register_api_print_endpoints(router=router)
    register_api_run_endpoints(router=router)
    register_api_workflow_endpoints(router=router)

    register_builtin_api_run_routes(
        router=router,
        actor_from_request=_actor_from_request,
        try_year_month=_try_year_month,
        run_error_tool=_run_error_tool,
        safe_incident_id=_safe_incident_id,
        extract_incident_year_month=_extract_incident_year_month,
        error_reports_root=_error_reports_root,
        review_kil_script_path=_review_kil_script_path,
    )

    register_api_kil_review_routes(router=router)
    return router

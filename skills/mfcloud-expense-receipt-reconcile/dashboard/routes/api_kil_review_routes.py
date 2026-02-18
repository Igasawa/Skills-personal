from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .api_kil_review_logic import api_get_kil_review_payload


def register_api_kil_review_routes(router: APIRouter) -> None:
    @router.get("/api/kil-review")
    def api_get_kil_review(
        source: str = Query(default="auto"),
        limit: int = Query(default=20, ge=1, le=200),
        only_review: bool = Query(default=False),
    ) -> JSONResponse:
        return api_get_kil_review_payload(source=source, limit=limit, only_review=only_review)



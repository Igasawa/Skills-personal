from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


def create_dashboard_app(
    *,
    base_dir: Path,
    create_pages_router: Callable[[Jinja2Templates], object],
    create_api_router: Callable[[], object],
    start_worker: Callable[[], None] | None = None,
    stop_worker: Callable[[], None] | None = None,
) -> FastAPI:
    if start_worker is not None or stop_worker is not None:
        @asynccontextmanager
        async def _lifespan(_app: FastAPI):
            if stop_worker is not None:
                stop_worker()
            if start_worker is not None:
                start_worker()
            try:
                yield
            finally:
                if stop_worker is not None:
                    stop_worker()

        app = FastAPI(lifespan=_lifespan)
    else:
        app = FastAPI()

    app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")

    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    app.include_router(create_pages_router(templates))
    app.include_router(create_api_router())

    return app

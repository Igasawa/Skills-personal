from __future__ import annotations

from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from routes.api import create_api_router
from routes.pages import create_pages_router
from services import core_scheduler

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.include_router(create_pages_router(templates))
app.include_router(create_api_router())


@app.on_event("startup")
def app_startup() -> None:
    # Timer auto-execution is intentionally disabled for wizard operation.
    core_scheduler.stop_worker()


@app.on_event("shutdown")
def app_shutdown() -> None:
    core_scheduler.stop_worker()

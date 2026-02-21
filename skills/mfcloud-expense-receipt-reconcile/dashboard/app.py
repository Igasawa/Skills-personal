from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
REPO_ROOT = BASE_DIR.parent.parent.parent
SHARED_LIB_DIR = REPO_ROOT / "scripts" / "lib"
if str(SHARED_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_LIB_DIR))

from routes.api import create_api_router
from routes.api_workspace_routes import (
    start_workflow_event_retry_worker,
    stop_workflow_event_retry_worker,
)
from routes.pages import create_pages_router
from services import core_scheduler
from dashboard_app_factory import create_dashboard_app


def _start_background_workers() -> None:
    # Start scheduler and retry workers so scheduled runs can execute unattended.
    core_scheduler.start_worker()
    start_workflow_event_retry_worker()


def _stop_background_workers() -> None:
    stop_workflow_event_retry_worker()
    core_scheduler.stop_worker()

app = create_dashboard_app(
    base_dir=BASE_DIR,
    create_pages_router=create_pages_router,
    create_api_router=create_api_router,
    start_worker=_start_background_workers,
    stop_worker=_stop_background_workers,
)

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
from routes.pages import create_pages_router
from services import core_scheduler
from dashboard_app_factory import create_dashboard_app

app = create_dashboard_app(
    base_dir=BASE_DIR,
    create_pages_router=create_pages_router,
    create_api_router=create_api_router,
    # Timer auto-execution is intentionally disabled for wizard operation.
    stop_worker=core_scheduler.stop_worker,
)

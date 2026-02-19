from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import Any

SERVICES_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = SERVICES_DIR.parent
SKILL_ROOT = DASHBOARD_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from common import (  # noqa: E402
    artifact_root as _artifact_root,
    ax_home as _ax_home,
    dashboard_ui_locale as _dashboard_ui_locale,
    read_json as _read_json,
    read_jsonl as _read_jsonl,
    runs_root as _runs_root,
    safe_non_negative_int as _safe_non_negative_int,
    write_json as _write_json,
    ym_default as _ym_default,
)

YM_RE = re.compile(r"^\d{4}-\d{2}$")
RUN_ID_RE = re.compile(r"^run_\d{8}_\d{6}(?:_\d{6})?$")
ORDER_ID_RE = re.compile(r"^[0-9A-Za-z-]+$")
SAFE_NAME_RE = re.compile(r"^[^/\\\\]+$")

DEFAULT_AMAZON_URL = "https://www.amazon.co.jp/gp/your-account/order-history"
DEFAULT_RAKUTEN_URL = "https://order.my.rakuten.co.jp/?l-id=top_normal_mymenu_order"
DEFAULT_MFCLOUD_ACCOUNTS_URL = "https://expense.moneyforward.com/accounts"
ARCHIVE_ACTION_LABELS = {
    "manual_archive": "アーカイブ",
    "month_close": "月次クローズ",
}


def _archive_action_label(action: Any) -> str:
    key = str(action or "").strip()
    if key in ARCHIVE_ACTION_LABELS:
        return ARCHIVE_ACTION_LABELS[key]
    return ARCHIVE_ACTION_LABELS["manual_archive"]

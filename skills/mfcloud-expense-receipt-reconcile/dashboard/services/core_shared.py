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
    append_audit_event_to_jsonl as _append_audit_event_to_jsonl,
    artifact_root as _artifact_root,
    ax_home as _ax_home,
    coerce_non_negative_int as _coerce_non_negative_int,
    dashboard_ui_locale as _dashboard_ui_locale,
    format_archive_snapshot_label as _format_archive_snapshot_label,
    latest_running_job as _latest_running_job,
    list_run_jobs as _list_run_jobs,
    normalize_audit_actor as _normalize_audit_actor,
    running_mode_for_ym as _running_mode_for_ym,
    running_job_exists as _running_job_exists,
    safe_int_optional as _safe_int_optional,
    scan_archive_history as _scan_archive_history,
    scan_archived_receipts as _scan_archived_receipts,
    read_json as _read_json,
    read_jsonl as _read_jsonl,
    read_workflow_templates_raw as _read_workflow_templates_raw,
    runs_root as _runs_root,
    safe_non_negative_int as _safe_non_negative_int,
    sort_workflow_templates_rows as _sort_workflow_templates_rows,
    workflow_templates_path as _workflow_templates_path,
    write_workflow_templates_raw as _write_workflow_templates_raw,
    write_json as _write_json,
    tail_text as _tail_text,
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

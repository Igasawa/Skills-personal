from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Callable

SKILL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SKILL_ROOT.parent.parent
SHARED_LIB_DIR = REPO_ROOT / "scripts" / "lib"
if str(SHARED_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_LIB_DIR))

from skill_runtime_common import (  # noqa: E402
    as_int as _as_int,
    coalesce as _coalesce,
    dashboard_ui_locale as _dashboard_ui_locale,
    default_storage_state as _default_storage_state,
    ensure_dir as _ensure_dir,
    load_order_exclusions as _load_order_exclusions,
    parse_csv_list as _parse_csv_list,
    read_json as _read_json,
    read_jsonl as _read_jsonl,
    resolve_ax_home as _resolve_ax_home,
    runs_root_for_skill as _runs_root_for_skill,
    safe_non_negative_int as _safe_non_negative_int,
    write_json as _write_json,
    ym_default as _ym_default,
    ym_to_dirname as _ym_to_dirname,
    artifact_root_for_skill as _artifact_root_for_skill,
)
from workflow_template_store_common import (  # noqa: E402
    read_workflow_templates_raw as _read_workflow_templates_raw_for_artifact,
    sort_workflow_templates as _sort_workflow_templates,
    workflow_templates_path as _workflow_templates_path_for_artifact,
    write_workflow_templates_raw as _write_workflow_templates_raw_for_artifact,
)
from run_registry_common import (  # noqa: E402
    append_audit_event as _append_audit_event_to_jsonl,
    coerce_non_negative_int as _coerce_non_negative_int,
    latest_running_job as _latest_running_job_common,
    list_run_jobs as _list_run_jobs_common,
    normalize_actor as _normalize_audit_actor,
    running_job_exists as _running_job_exists_common,
    running_mode_for_ym as _running_mode_for_ym_common,
    safe_int as _safe_int_optional,
    tail_text as _tail_text,
)
from artifact_archive_common import (  # noqa: E402
    format_archive_snapshot_label as _format_archive_snapshot_label,
    scan_archive_history as _scan_archive_history_common,
    scan_archived_receipts as _scan_archived_receipts_common,
)

SKILL_SLUG = "mfcloud-expense-receipt-reconcile"


def ax_home() -> Path:
    return _resolve_ax_home()


def artifact_root() -> Path:
    return _artifact_root_for_skill(SKILL_SLUG)


def runs_root() -> Path:
    return _runs_root_for_skill(SKILL_SLUG)


def ym_default(*args: Any, **kwargs: Any) -> tuple[int, int]:
    return _ym_default(*args, **kwargs)


def dashboard_ui_locale() -> str:
    return _dashboard_ui_locale()


def ym_to_dirname(year: int, month: int) -> str:
    return _ym_to_dirname(year, month)


def coalesce(*values: Any) -> Any:
    return _coalesce(*values)


def parse_csv_list(value: Any) -> list[str]:
    return _parse_csv_list(value)


def as_int(value: Any, *, name: str) -> int:
    return _as_int(value, name=name)


def safe_non_negative_int(value: Any, *, default: int = 0) -> int:
    return _safe_non_negative_int(value, default=default)


def ensure_dir(path: Path) -> Path:
    return _ensure_dir(path)


def default_storage_state(name: str) -> Path:
    return _default_storage_state(name)


def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    return _read_json(path)


def read_jsonl(path: Path, *, required: bool = False, strict: bool = False) -> list[dict[str, Any]]:
    return _read_jsonl(path, required=required, strict=strict)


def load_order_exclusions(path: Path | str | None) -> set[tuple[str, str]]:
    return _load_order_exclusions(path)


def write_json(path: Path, data: Any) -> None:
    _write_json(path, data)


def workflow_templates_path() -> Path:
    return _workflow_templates_path_for_artifact(artifact_root=artifact_root())


def read_workflow_templates_raw() -> list[dict[str, Any]]:
    return _read_workflow_templates_raw_for_artifact(
        artifact_root=artifact_root(),
        read_json=read_json,
    )


def write_workflow_templates_raw(rows: list[dict[str, Any]]) -> None:
    _write_workflow_templates_raw_for_artifact(
        artifact_root=artifact_root(),
        rows=rows,
        write_json=write_json,
    )


def sort_workflow_templates_rows(
    templates: list[dict[str, Any]],
    *,
    sort: str,
    allowed_sorts: set[str] | tuple[str, ...] | None = None,
    default_sort: str = "updated_desc",
) -> list[dict[str, Any]]:
    return _sort_workflow_templates(
        templates,
        sort=sort,
        allowed_sorts=allowed_sorts,
        default_sort=default_sort,
    )


def safe_int_optional(value: Any) -> int | None:
    return _safe_int_optional(value)


def coerce_non_negative_int(value: Any, default: int = 0) -> int:
    return _coerce_non_negative_int(value, default=default)


def normalize_audit_actor(actor: Any) -> dict[str, Any]:
    return _normalize_audit_actor(actor)


def append_audit_event_to_jsonl(
    *,
    path: Path,
    year: int,
    month: int,
    event_type: str,
    action: str,
    status: str,
    actor: Any = None,
    source: str | None = None,
    mode: str | None = None,
    run_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    _append_audit_event_to_jsonl(
        path=path,
        year=year,
        month=month,
        event_type=event_type,
        action=action,
        status=status,
        actor=actor,
        source=source,
        mode=mode,
        run_id=run_id,
        details=details,
    )


def tail_text(path: Path, *, max_bytes: int = 32000) -> str:
    return _tail_text(path, max_bytes=max_bytes)


def running_mode_for_ym(year: int, month: int) -> str | None:
    return _running_mode_for_ym_common(
        year=year,
        month=month,
        runs_root=runs_root(),
        read_json=read_json,
    )


def list_run_jobs(
    *,
    runs_root_fn: Path | None = None,
    read_json_fn: Callable[[Path], Any] | None = None,
) -> list[dict[str, Any]]:
    return _list_run_jobs_common(
        runs_root=runs_root_fn or runs_root(),
        read_json=read_json_fn or read_json,
    )


def running_job_exists(jobs: list[dict[str, Any]]) -> bool:
    return _running_job_exists_common(jobs)


def latest_running_job(jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _latest_running_job_common(jobs)


def format_archive_snapshot_label(name: str) -> str:
    return _format_archive_snapshot_label(name)


def scan_archive_history(
    *,
    ym_matcher,
    archive_action_label,
    limit: int = 30,
) -> list[dict[str, Any]]:
    return _scan_archive_history_common(
        artifact_root=artifact_root(),
        ym_matcher=ym_matcher,
        archive_action_label=archive_action_label,
        limit=limit,
    )


def scan_archived_receipts(
    root: Any,
    *,
    source_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    return _scan_archived_receipts_common(root, source_labels=source_labels)

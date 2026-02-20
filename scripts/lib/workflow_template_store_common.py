from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

WORKFLOW_TEMPLATES_DIRNAME = "_workflow_templates"
WORKFLOW_TEMPLATES_FILENAME = "workflow_templates.json"


def workflow_templates_path(*, artifact_root: Path) -> Path:
    return artifact_root / WORKFLOW_TEMPLATES_DIRNAME / WORKFLOW_TEMPLATES_FILENAME


def read_workflow_templates_raw(
    *,
    artifact_root: Path,
    read_json: Callable[[Path], dict[str, Any] | list[Any] | None],
) -> list[dict[str, Any]]:
    raw = read_json(workflow_templates_path(artifact_root=artifact_root))
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in raw:
        if isinstance(row, dict):
            rows.append(row)
    return rows


def write_workflow_templates_raw(
    *,
    artifact_root: Path,
    rows: list[dict[str, Any]],
    write_json: Callable[[Path, Any], None],
) -> None:
    write_json(workflow_templates_path(artifact_root=artifact_root), rows)


def sort_workflow_templates(
    templates: list[dict[str, Any]],
    *,
    sort: str,
    allowed_sorts: Iterable[str] | None = None,
    default_sort: str = "updated_desc",
) -> list[dict[str, Any]]:
    selected_sort = str(sort or "").strip()
    if allowed_sorts is not None:
        options = {str(item or "").strip() for item in allowed_sorts if str(item or "").strip()}
        if selected_sort not in options:
            selected_sort = default_sort
    if not selected_sort:
        selected_sort = default_sort

    if selected_sort.startswith("updated"):
        key = lambda item: str(item.get("updated_at") or item.get("created_at") or "")
    elif selected_sort.startswith("created"):
        key = lambda item: str(item.get("created_at") or item.get("updated_at") or "")
    elif selected_sort in {"name_asc", "name_desc"}:
        key = lambda item: str(item.get("name") or "").lower()
    else:
        key = lambda item: (int(item.get("year") or 0), int(item.get("month") or 0))

    reverse = selected_sort.endswith("desc")
    return sorted(templates, key=key, reverse=reverse)

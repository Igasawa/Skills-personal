from __future__ import annotations

from typing import Callable

from .api_workspace_routes import (
    start_workflow_event_retry_worker,
    stop_workflow_event_retry_worker,
    set_workflow_event_retry_drain_callback,
)


def start_worker() -> None:
    """Backward-compatible alias for workflow-event retry worker startup."""
    start_workflow_event_retry_worker()


def stop_worker() -> None:
    """Backward-compatible alias for workflow-event retry worker shutdown."""
    stop_workflow_event_retry_worker()


def set_drain_callback(callback: Callable[[], None] | None) -> None:
    set_workflow_event_retry_drain_callback(callback)


__all__ = [
    "start_worker",
    "stop_worker",
    "set_drain_callback",
    "start_workflow_event_retry_worker",
    "stop_workflow_event_retry_worker",
    "set_workflow_event_retry_drain_callback",
]

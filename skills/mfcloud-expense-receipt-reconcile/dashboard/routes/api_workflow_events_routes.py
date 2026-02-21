from __future__ import annotations

from typing import Any

from .api_workspace_routes import register_api_workspace_routes as _register_api_workspace_routes


def register_api_workflow_events_routes(*args: Any, **kwargs: Any) -> None:
    """Register workflow event routes."""
    _register_api_workspace_routes(*args, **kwargs)


__all__ = ["register_api_workflow_events_routes"]


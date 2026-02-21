from __future__ import annotations

from typing import Any

from .api_workspace_routes import register_api_workspace_routes as _register_api_workspace_routes


def register_api_workflow_pages_routes(*args: Any, **kwargs: Any) -> None:
    """Register workflow page routes."""
    _register_api_workspace_routes(*args, **kwargs)


__all__ = ["register_api_workflow_pages_routes"]


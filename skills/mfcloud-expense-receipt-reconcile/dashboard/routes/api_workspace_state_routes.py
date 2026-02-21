from __future__ import annotations

from typing import Any

from .api_workspace_routes import register_api_workspace_routes as _register_api_workspace_routes


def register_api_workspace_state_routes(*args: Any, **kwargs: Any) -> None:
    """Register workspace state routes.

    This module keeps the route-registration API stable while allowing
    callers to import domain-specific entrypoints.
    """
    _register_api_workspace_routes(*args, **kwargs)


register_api_workspace_routes = register_api_workspace_state_routes


__all__ = [
    "register_api_workspace_state_routes",
    "register_api_workspace_routes",
]

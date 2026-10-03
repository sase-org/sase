"""Context-sensitive availability policy for top-level ACE actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ._app_action_availability_agents import check_agents_availability
from ._app_action_availability_artifacts import check_artifacts_availability

CheckAction = Callable[[str, tuple[object, ...]], bool | None]


def check_app_action(
    app: Any,
    action: str,
    parameters: tuple[object, ...],
    fallback: CheckAction,
) -> bool | None:
    """Return whether an app action is available in the current UI context."""
    if action == "start_agent_from_changespec":  # legacy compatibility alias
        action = "start_agent_from_patch"
    decided = check_agents_availability(app, action, parameters)
    if decided is not None:
        return decided
    decided = check_artifacts_availability(app, action, parameters)
    if decided is not None:
        return decided
    return fallback(action, parameters)


__all__: list[str] = ["CheckAction", "check_app_action"]

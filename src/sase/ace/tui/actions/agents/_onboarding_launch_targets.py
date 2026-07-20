"""Launch-target availability helpers for the Agents onboarding panel."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from sase.project_display_names import ProjectDisplayProjection
from sase.status_state_machine import remove_workspace_suffix

_DEFAULT_EXCLUDED_PROJECT_NAMES = frozenset({"home"})
_ELIGIBLE_CHANGESPEC_STATUSES = frozenset({"WIP", "Draft", "Ready", "Mailed"})


class _ChangeSpecLike(Protocol):
    status: str


def _launch_targets_available(
    projects: Iterable[str | ProjectDisplayProjection],
    changespecs: Iterable[_ChangeSpecLike],
    *,
    exclude_project_names: frozenset[str] = _DEFAULT_EXCLUDED_PROJECT_NAMES,
) -> bool:
    """Return whether the ``+`` modal would have a selectable launch row."""
    if any(
        (
            project.project_key
            if isinstance(project, ProjectDisplayProjection)
            else project
        )
        not in exclude_project_names
        for project in projects
    ):
        return True
    return any(
        remove_workspace_suffix(changespec.status) in _ELIGIBLE_CHANGESPEC_STATUSES
        for changespec in changespecs
    )


def discover_agents_onboarding_launch_targets_available() -> bool:
    """Read launch targets from disk-backed discovery helpers."""
    from ....changespec import find_all_changespecs_cached
    from ...modals.project_discovery import list_launchable_projects

    return _launch_targets_available(
        list_launchable_projects(),
        find_all_changespecs_cached(),
    )

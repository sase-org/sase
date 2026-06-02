"""Project discovery helpers for TUI project selection."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import normalize_project_lifecycle_state_filter
from sase.workspace_provider import detect_workflow_type
from sase.workspace_provider.utils import parse_workspace_dir


def _states_for_project_records(include_states: Sequence[str] | str) -> list[str]:
    return normalize_project_lifecycle_state_filter(include_states)


def list_launchable_projects(
    projects_dir: Path | None = None,
    include_states: Sequence[str] | str = ("active",),
) -> list[str]:
    """Return project entries that are valid project-scoped launch targets."""
    projects_base = projects_dir or sase_projects_dir()
    if not projects_base.exists():
        return []

    projects: list[str] = []
    records = list_project_records(
        projects_base,
        _states_for_project_records(include_states),
        include_home=True,
    )
    for record in records:
        if record.state != "active":
            continue
        if not record.project_file:
            continue
        if _is_launchable_project_file(Path(record.project_file)):
            projects.append(record.project_name)

    return projects


def is_launchable_project(
    project_name: str,
    projects_dir: Path | None = None,
    include_states: Sequence[str] | str = ("active",),
) -> bool:
    """Return whether a project entry is a valid project-scoped launch target."""
    if not project_name:
        return False

    projects_base = projects_dir or sase_projects_dir()
    records = list_project_records(
        projects_base,
        _states_for_project_records(include_states),
        include_home=True,
    )
    for record in records:
        if record.project_name != project_name or record.state != "active":
            continue
        if not record.project_file:
            return False
        return _is_launchable_project_file(Path(record.project_file))
    return False


def _is_launchable_project_file(project_file: Path) -> bool:
    workspace_dir = parse_workspace_dir(str(project_file))
    if not workspace_dir:
        return False

    if not Path(workspace_dir).expanduser().exists():
        return False

    try:
        detect_workflow_type(str(project_file))
    except ValueError:
        return False

    return True

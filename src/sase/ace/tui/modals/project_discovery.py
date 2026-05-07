"""Project discovery helpers for TUI project selection."""

from __future__ import annotations

from pathlib import Path

from sase.workspace_provider import detect_workflow_type
from sase.workspace_provider.utils import parse_workspace_dir


def list_launchable_projects(
    projects_dir: Path | None = None,
) -> list[str]:
    """Return project entries that are valid project-scoped launch targets."""
    projects_base = projects_dir or Path.home() / ".sase" / "projects"
    if not projects_base.exists():
        return []

    projects: list[str] = []
    for project_dir in sorted(projects_base.iterdir()):
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name
        if project_name == "home":
            continue

        project_file = project_dir / f"{project_name}.gp"
        if not project_file.is_file():
            continue

        if _is_launchable_project_file(project_file):
            projects.append(project_name)

    return projects


def is_launchable_project(
    project_name: str,
    projects_dir: Path | None = None,
) -> bool:
    """Return whether a project entry is a valid project-scoped launch target."""
    if not project_name or project_name == "home":
        return False

    projects_base = projects_dir or Path.home() / ".sase" / "projects"
    project_file = projects_base / project_name / f"{project_name}.gp"
    if not project_file.is_file():
        return False

    return _is_launchable_project_file(project_file)


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

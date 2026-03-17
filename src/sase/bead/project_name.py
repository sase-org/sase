"""Resolve project names from the current working directory."""

from __future__ import annotations

import os
from pathlib import Path

from sase.workspace_utils import parse_workspace_dir


def _is_workspace_variant(component: str, project_name: str) -> bool:
    """Return True when *component* names a workspace for *project_name*."""
    return component == project_name or component.startswith(f"{project_name}_")


def _cwd_matches_project_workspace(cwd: str, primary: Path, project_name: str) -> bool:
    """Check if *cwd* is under *primary* or one of its project workspace variants."""
    primary_parts = primary.parts
    cwd_parts = Path(cwd).parts

    if len(cwd_parts) < len(primary_parts):
        return False

    for i, primary_component in enumerate(primary_parts):
        cwd_component = cwd_parts[i]
        if primary_component == cwd_component:
            continue
        if _is_workspace_variant(
            primary_component, project_name
        ) and _is_workspace_variant(cwd_component, project_name):
            for j in range(i + 1, len(primary_parts)):
                if cwd_parts[j] != primary_parts[j]:
                    return False
            return True
        return False

    return True


def scan_projects_for_cwd(cwd: str) -> tuple[str, Path] | None:
    """Find ``(project_name, primary_workspace)`` for *cwd* by scanning projects."""
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.is_dir():
        return None

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        gp_file = project_dir / f"{project_name}.gp"
        workspace_dir = parse_workspace_dir(str(gp_file))
        if not workspace_dir:
            continue

        primary = Path(workspace_dir.rstrip("/"))

        if _cwd_matches_project_workspace(cwd, primary, project_name):
            return project_name, primary

    return None


def infer_project_name_from_cwd(cwd: str | None = None) -> str | None:
    """Infer current project name from *cwd* (defaults to ``os.getcwd()``)."""
    cwd_abs = os.path.abspath(cwd or os.getcwd())

    try:
        from sase.workspace_provider import get_workspace_name

        project_name = get_workspace_name(cwd_abs)
        if project_name:
            project_file = (
                Path.home() / ".sase" / "projects" / project_name / f"{project_name}.gp"
            )
            if project_file.exists():
                return project_name
    except Exception:
        pass

    scanned = scan_projects_for_cwd(cwd_abs)
    if scanned is not None:
        return scanned[0]

    return None

"""Resolve project names from the current working directory."""

from __future__ import annotations

import os
from pathlib import Path

from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.core.paths import is_valid_sase_project_name, sase_projects_dir
from sase.workspace_provider.utils import parse_workspace_dir


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
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return None

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        if not is_valid_sase_project_name(project_name):
            continue
        project_file = Path(preferred_project_spec_path(str(project_dir), project_name))
        workspace_dir = parse_workspace_dir(str(project_file))
        if not workspace_dir:
            continue

        primary = Path(workspace_dir.rstrip("/"))

        if _cwd_matches_project_workspace(cwd, primary, project_name):
            return project_name, primary

    return None


def infer_project_name_from_cwd(cwd: str | None = None) -> str | None:
    """Infer current project name from *cwd* (defaults to ``os.getcwd()``).

    Resolution order:
      1. nearest ``.sase/checkout.json`` marker in an ancestor directory
         (set by managed checkouts);
      2. workspace provider ``ws_get_workspace_name`` hook;
      3. scan ``~/.sase/projects/`` for a project whose workspace matches.
    """
    cwd_abs = os.path.abspath(cwd or os.getcwd())

    marker_project = _project_name_from_marker(cwd_abs)
    if marker_project is not None:
        return marker_project

    try:
        from sase.workspace_provider import get_workspace_name

        project_name = get_workspace_name(cwd_abs)
        if project_name and is_valid_sase_project_name(project_name):
            project_name = _canonicalize_project_ref(project_name)
            project_dir = sase_projects_dir() / project_name
            project_file = Path(
                preferred_project_spec_path(str(project_dir), project_name)
            )
            if project_file.exists():
                return project_name
    except Exception:
        pass

    scanned = scan_projects_for_cwd(cwd_abs)
    if scanned is not None:
        return scanned[0]

    return None


def _project_name_from_marker(cwd_abs: str) -> str | None:
    """Resolve project name via the nearest managed-checkout marker."""
    try:
        from sase.workspace_provider import find_marker_from_cwd
    except Exception:
        return None

    try:
        found = find_marker_from_cwd(cwd_abs)
    except Exception:
        return None
    if found is None:
        return None
    _, marker = found
    project_name = marker.project_name.strip()
    if not project_name or not is_valid_sase_project_name(project_name):
        return None

    project_name = _canonicalize_project_ref(project_name)
    project_dir = sase_projects_dir() / project_name
    project_file = Path(preferred_project_spec_path(str(project_dir), project_name))
    if not project_file.exists():
        return None
    return project_name


def _canonicalize_project_ref(project_name: str) -> str:
    try:
        from sase.project_aliases import resolve_project_alias_ref

        canonical = resolve_project_alias_ref(project_name)
    except Exception:
        return project_name
    if canonical and is_valid_sase_project_name(canonical):
        return canonical
    return project_name

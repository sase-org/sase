"""Workspace-aware bead store resolution."""

from __future__ import annotations

import os
from pathlib import Path

from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC
from sase.bead.project_name import infer_project_name_from_cwd, scan_projects_for_cwd
from sase.core.paths import sase_projects_dir
from sase.core.state_write_guard import pytest_path_is_sandboxed


def get_project_beads_dirs() -> list[Path] | None:
    """Find the current project's single readable bead store.

    Returns None if not in a recognized sase project (caller should fall back
    to the walk-up-from-cwd behavior).
    """
    primary = resolve_primary_workspace()
    if primary is None:
        return None
    beads_dir = _current_or_primary_beads_dir(Path.cwd(), primary)
    return [beads_dir] if beads_dir is not None else None


def resolve_primary_workspace_for_project(project_name: str) -> Path | None:
    """Resolve the user-owned primary checkout for an explicit project name."""
    primary = _resolve_from_project_file(project_name)
    if primary is None:
        primary = _resolve_from_workspace_provider(project_name)
    return primary


def get_project_beads_dirs_for_project(project_name: str) -> list[Path] | None:
    """Find the canonical bead store for an explicit project name.

    This bypasses CWD-based project inference so cross-project callers can read
    beads for the project that owns an agent without scanning sibling
    workspaces.
    """
    primary = resolve_primary_workspace_for_project(project_name)
    if primary is None:
        return None
    beads_dir = _canonical_project_beads_dir(primary)
    return [beads_dir] if beads_dir is not None else None


def get_all_project_beads_dirs() -> list[Path]:
    """Find one canonical bead store for every known project under ``~/.sase``."""
    projects_dir = _sase_projects_dir()
    if not projects_dir.is_dir():
        return []

    bead_dirs: list[Path] = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        project_file = Path(preferred_project_spec_path(str(project_dir), project_name))
        if not project_file.exists():
            continue
        project_bead_dirs = get_project_beads_dirs_for_project(project_name)
        if project_bead_dirs:
            bead_dirs.extend(project_bead_dirs)

    return _dedupe_existing_dirs(bead_dirs)


def resolve_primary_workspace() -> Path | None:
    """Resolve the primary workspace directory from CWD.

    Tries three strategies:
      1. Managed checkout marker (``.sase/checkout.json``) in an ancestor
         directory — preferred when CWD is inside a managed checkout.
      2. Workspace provider plugin (``ws_get_workspace_name``).
      3. Scan ``~/.sase/projects/`` and match CWD against each
         project's ``WORKSPACE_DIR`` (including numbered variants
         like ``project_101``).

    Strategy 3 is the fallback for VCS providers (e.g. Mercurial/Google)
    that implement ``vcs_get_workspace_name`` but not the workspace
    provider hook, and for legacy adjacent workspaces with no marker.
    """
    # Strategy 1: managed checkout marker
    marker_primary = _resolve_from_marker()
    if marker_primary is not None and pytest_path_is_sandboxed(marker_primary):
        return marker_primary

    # Strategy 2: workspace/provider-derived project name
    project_name = infer_project_name_from_cwd()

    if project_name:
        result = _resolve_from_project_file(project_name)
        if result is not None and pytest_path_is_sandboxed(result):
            return result
        # If WORKSPACE_DIR is missing/stale in the .gp file, ask the
        # workspace provider directly for workspace #1.
        result = _resolve_from_workspace_provider(project_name)
        if result is not None and pytest_path_is_sandboxed(result):
            return result

    # Strategy 3: scan all projects
    result = _resolve_by_scanning_projects(os.path.abspath(os.getcwd()))
    if result is None or not pytest_path_is_sandboxed(result):
        return None
    return result


def _resolve_from_marker() -> Path | None:
    """Resolve the primary workspace via the nearest checkout marker."""
    try:
        from sase.workspace_provider import find_marker_from_cwd
    except Exception:
        return None

    try:
        found = find_marker_from_cwd(os.getcwd())
    except Exception:
        return None
    if found is None:
        return None
    _, marker = found
    primary_str = marker.primary_workspace_dir.strip()
    if not primary_str:
        return None
    primary = Path(primary_str.rstrip("/"))
    if not primary.is_dir():
        return None
    return primary


def _resolve_from_project_file(project_name: str) -> Path | None:
    """Look up WORKSPACE_DIR from the project's spec file."""
    project_dir = _sase_projects_dir() / project_name
    project_file = Path(preferred_project_spec_path(str(project_dir), project_name))
    if not project_file.exists():
        return None

    from sase.workspace_provider.utils import parse_workspace_dir

    workspace_dir = parse_workspace_dir(str(project_file))
    if not workspace_dir:
        return None

    primary = Path(workspace_dir.rstrip("/"))
    if not primary.is_dir():
        return None

    return primary


def _resolve_from_workspace_provider(project_name: str) -> Path | None:
    """Resolve primary workspace using workspace provider plugins."""
    try:
        from sase.workspace_provider import detect_workflow_type
        from sase.workspace_provider import (
            get_workspace_directory as ws_get_workspace_directory,
        )
        from sase.workspace_provider.utils import parse_workspace_dir

        project_dir = _sase_projects_dir() / project_name
        project_file = Path(preferred_project_spec_path(str(project_dir), project_name))
        workflow_type = detect_workflow_type(str(project_file))
        primary_workspace_dir = parse_workspace_dir(str(project_file)) or ""
        workspace = ws_get_workspace_directory(
            workflow_type, 1, project_name, primary_workspace_dir
        )
        primary = Path(workspace.rstrip("/"))
        if primary.is_dir():
            return primary
    except Exception:
        return None
    return None


def _resolve_by_scanning_projects(cwd: str) -> Path | None:
    """Scan ``~/.sase/projects/`` to find a project whose workspace matches CWD.

    Handles numbered workspace variants (e.g. CWD under ``yserve_101/google3``
    matches project ``yserve`` with ``WORKSPACE_DIR=/…/yserve/google3``).
    """
    scanned = scan_projects_for_cwd(cwd)
    if scanned is None:
        return None
    primary = scanned[1]
    if not primary.is_dir():
        return None
    return primary


def _current_or_primary_beads_dir(cwd: Path, primary_workspace: Path) -> Path | None:
    """Resolve the readable bead store for the current checkout."""
    current = cwd.resolve()
    for parent in [current, *current.parents]:
        current_vc = parent / BEADS_DIRNAME
        if current_vc.is_dir():
            return current_vc
    return _canonical_project_beads_dir(primary_workspace)


def _canonical_project_beads_dir(primary_workspace: Path) -> Path | None:
    """Resolve a project's canonical bead store without sibling enumeration."""
    from sase.sdd.store import resolve_sdd_store

    store = resolve_sdd_store(primary_workspace, 1)
    primary_vc = primary_workspace / BEADS_DIRNAME
    if store.is_in_tree:
        return primary_vc if primary_vc.is_dir() else None

    resolved_beads = store.kind_root("beads")
    if resolved_beads.is_dir():
        return resolved_beads

    primary_non_vc = primary_workspace / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC
    if primary_non_vc.is_dir():
        return primary_non_vc

    if primary_vc.is_dir():
        return primary_vc

    return None


def _dedupe_existing_dirs(paths: list[Path]) -> list[Path]:
    """Return existing directories once, preserving input order."""
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        if not path.is_dir():
            continue
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _sase_projects_dir() -> Path:
    root = os.environ.get("SASE_HOME")
    if root:
        return Path(root).expanduser() / "projects"
    return sase_projects_dir()

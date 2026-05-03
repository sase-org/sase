"""Workspace-aware bead resolution.

Discovers all workspace directories for the current project and provides
a merged read-only view of beads across all of them.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC
from sase.bead.project_name import infer_project_name_from_cwd, scan_projects_for_cwd

LEGACY_BEADS_DIRNAME = ".sase_beads"


def get_project_beads_dirs() -> list[Path] | None:
    """Find all bead store directories across all workspaces of the current project.

    Returns None if not in a recognized sase project (caller should fall back
    to the old walk-up-from-cwd behavior).
    """
    primary = resolve_primary_workspace()
    if primary is None:
        return None
    return _enumerate_workspace_beads_dirs(primary)


def get_project_beads_dirs_for_project(project_name: str) -> list[Path] | None:
    """Find all bead store directories for an explicit project name.

    This bypasses CWD-based project inference so cross-project callers can read
    beads for the project that owns an agent.
    """
    primary = _resolve_from_project_file(project_name)
    if primary is None:
        primary = _resolve_from_workspace_provider(project_name)
    if primary is None:
        return None
    return _enumerate_workspace_beads_dirs(primary)


def get_all_project_beads_dirs() -> list[Path]:
    """Find bead store directories for every known project under ``~/.sase``."""
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.is_dir():
        return []

    bead_dirs: list[Path] = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        project_file = project_dir / f"{project_name}.gp"
        if not project_file.exists():
            continue
        project_bead_dirs = get_project_beads_dirs_for_project(project_name)
        if project_bead_dirs:
            bead_dirs.extend(project_bead_dirs)

    return _dedupe_existing_dirs(bead_dirs)


def resolve_primary_workspace() -> Path | None:
    """Resolve the primary workspace directory from CWD.

    Tries two strategies:
      1. Workspace provider plugin (``ws_get_workspace_name``).
      2. Scan ``~/.sase/projects/`` and match CWD against each
         project's ``WORKSPACE_DIR`` (including numbered variants
         like ``project_101``).

    Strategy 2 is the fallback for VCS providers (e.g. Mercurial/Google)
    that implement ``vcs_get_workspace_name`` but not the workspace
    provider hook.
    """
    # Strategy 1: workspace/provider-derived project name
    project_name = infer_project_name_from_cwd()

    if project_name:
        result = _resolve_from_project_file(project_name)
        if result is not None:
            return result
        # If WORKSPACE_DIR is missing/stale in the .gp file, ask the
        # workspace provider directly for workspace #1.
        result = _resolve_from_workspace_provider(project_name)
        if result is not None:
            return result

    # Strategy 2: scan all projects
    return _resolve_by_scanning_projects(os.path.abspath(os.getcwd()))


def _resolve_from_project_file(project_name: str) -> Path | None:
    """Look up WORKSPACE_DIR from ``~/.sase/projects/<name>/<name>.gp``."""
    project_file = (
        Path.home() / ".sase" / "projects" / project_name / f"{project_name}.gp"
    )
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

        project_file = (
            Path.home() / ".sase" / "projects" / project_name / f"{project_name}.gp"
        )
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


def _enumerate_workspace_beads_dirs(primary_workspace: Path) -> list[Path]:
    """Enumerate beads directories across all workspaces.

    Non-VC mode is primary-only: if ``primary/.sase/sdd/beads`` exists,
    return only that directory.

    VC/read mode checks ``sdd/beads/`` and legacy ``.sase_beads/`` in the
    primary workspace and sibling workspace directories matching
    ``<primary_basename>_<N>``.
    """
    primary_non_vc = primary_workspace / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC
    if primary_non_vc.is_dir():
        return [primary_non_vc]

    workspace_dirs = _enumerate_project_workspace_dirs(primary_workspace)
    current_dirs = [workspace / BEADS_DIRNAME for workspace in workspace_dirs]
    legacy_dirs = [workspace / LEGACY_BEADS_DIRNAME for workspace in workspace_dirs]

    return _dedupe_existing_dirs([*current_dirs, *legacy_dirs])


def _enumerate_project_workspace_dirs(primary_workspace: Path) -> list[Path]:
    """Enumerate the primary workspace and numbered sibling workspaces."""
    parent = primary_workspace.parent
    basename = primary_workspace.name
    pattern = re.compile(rf"^{re.escape(basename)}_\d+$")

    workspaces = [primary_workspace]
    if parent.is_dir():
        for entry in sorted(parent.iterdir()):
            if entry.is_dir() and pattern.match(entry.name):
                workspaces.append(entry)

    return workspaces


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


class MergedBeadView:
    """Read-only view of beads merged across multiple workspaces.

    For each issue ID, takes the version with the most recent ``updated_at``
    timestamp. Dependencies are carried with their owning issue.
    """

    def __init__(self, beads_dirs: list[Path]) -> None:
        self._beads_dirs = beads_dirs

    def __enter__(self) -> MergedBeadView:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def show(self, issue_id: str) -> Issue:
        """Get a single issue by ID. Raises KeyError if not found."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.merged_show(self._beads_dirs, issue_id)

    def list_issues(
        self,
        statuses: list[Status] | None = None,
        issue_types: list[IssueType] | None = None,
        tiers: list[BeadTier] | None = None,
    ) -> list[Issue]:
        """List issues with optional filters."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.merged_list_issues(
            self._beads_dirs,
            statuses=statuses,
            issue_types=issue_types,
            tiers=tiers,
        )

    def ready(self) -> list[Issue]:
        """Return open issues with no active blockers."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.merged_ready(self._beads_dirs)

    def blocked(self) -> list[Issue]:
        """Return issues with at least one active blocker."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.merged_blocked(self._beads_dirs)

    def stats(self) -> dict[str, int]:
        """Return counts by status and type."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.merged_stats(self._beads_dirs)

    def get_epic_children(self, epic_id: str) -> list[Issue]:
        """Get all child issues of an epic."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.merged_get_epic_children(self._beads_dirs, epic_id)

"""Workspace-aware bead resolution.

Discovers all workspace directories for the current project and provides
a merged read-only view of beads across all of them.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from sase.bead import db as db_mod
from sase.bead.jsonl import dict_to_issue
from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC


def get_project_beads_dirs() -> list[Path] | None:
    """Find all .sase_beads/ directories across all workspaces of the current project.

    Returns None if not in a recognized sase project (caller should fall back
    to the old walk-up-from-cwd behavior).
    """
    primary = resolve_primary_workspace()
    if primary is None:
        return None
    return _enumerate_workspace_beads_dirs(primary)


def resolve_primary_workspace() -> Path | None:
    """Resolve the primary workspace directory from CWD.

    Uses the sase workspace provider to detect the project name,
    then looks up WORKSPACE_DIR in the project file.
    """
    try:
        from sase.workspace_provider import get_workspace_name

        project_name = get_workspace_name(os.getcwd())
        if not project_name:
            return None
    except Exception:
        return None

    project_file = (
        Path.home() / ".sase" / "projects" / project_name / f"{project_name}.gp"
    )
    if not project_file.exists():
        return None

    from sase.workspace_utils import parse_workspace_dir

    workspace_dir = parse_workspace_dir(str(project_file))
    if not workspace_dir:
        return None

    primary = Path(workspace_dir.rstrip("/"))
    if not primary.is_dir():
        return None

    return primary


def _enumerate_workspace_beads_dirs(primary_workspace: Path) -> list[Path]:
    """Enumerate beads directories across all workspaces.

    Non-VC mode is primary-only: if ``primary/.sase/sdd/beads`` exists,
    return only that directory.

    VC mode checks ``.sase_beads/`` in the primary workspace and sibling
    workspace directories matching ``<primary_basename>_<N>``.
    """
    primary_non_vc = primary_workspace / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC
    if primary_non_vc.is_dir():
        return [primary_non_vc]

    parent = primary_workspace.parent
    basename = primary_workspace.name
    pattern = re.compile(rf"^{re.escape(basename)}_\d+$")

    beads_dirs: list[Path] = []

    # Primary workspace
    primary_beads = primary_workspace / BEADS_DIRNAME
    if primary_beads.is_dir():
        beads_dirs.append(primary_beads)

    # Workspace shares (VC mode only)
    if parent.is_dir():
        for entry in sorted(parent.iterdir()):
            if entry.is_dir() and pattern.match(entry.name):
                beads = entry / BEADS_DIRNAME
                if beads.is_dir():
                    beads_dirs.append(beads)

    return beads_dirs


class MergedBeadView:
    """Read-only view of beads merged across multiple workspaces.

    For each issue ID, takes the version with the most recent ``updated_at``
    timestamp. Dependencies are carried with their owning issue.
    """

    def __init__(self, beads_dirs: list[Path]) -> None:
        self._conn = _build_merged_db(beads_dirs)

    def __enter__(self) -> MergedBeadView:
        return self

    def __exit__(self, *_: object) -> None:
        self._conn.close()

    def show(self, issue_id: str) -> Issue:
        """Get a single issue by ID. Raises KeyError if not found."""
        issue = db_mod.get_issue(self._conn, issue_id)
        if issue is None:
            raise KeyError(f"Issue not found: {issue_id}")
        return issue

    def list_issues(
        self,
        status: Status | None = None,
        issue_type: IssueType | None = None,
    ) -> list[Issue]:
        """List issues with optional filters."""
        return db_mod.list_issues(self._conn, status=status, issue_type=issue_type)

    def ready(self) -> list[Issue]:
        """Return open issues with no active blockers."""
        return db_mod.ready_issues(self._conn)

    def blocked(self) -> list[Issue]:
        """Return issues with at least one active blocker."""
        return db_mod.blocked_issues(self._conn)

    def stats(self) -> dict[str, int]:
        """Return counts by status and type."""
        return db_mod.stats(self._conn)

    def get_epic_children(self, epic_id: str) -> list[Issue]:
        """Get all child issues of an epic."""
        return db_mod.get_epic_children(self._conn, epic_id)


def _build_merged_db(beads_dirs: list[Path]) -> sqlite3.Connection:
    """Create an in-memory SQLite DB with merged data from all workspaces.

    For each issue ID, takes the version with the most recent ``updated_at``.
    """
    conn = db_mod.create_memory_db()

    # Parse all JSONL files and merge by updated_at
    merged_issues: dict[str, Issue] = {}
    for beads_dir in beads_dirs:
        jsonl_path = beads_dir / "issues.jsonl"
        if not jsonl_path.exists():
            continue
        text = jsonl_path.read_text().strip()
        if not text:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                issue = dict_to_issue(data)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
            existing = merged_issues.get(issue.id)
            if existing is None or issue.updated_at > existing.updated_at:
                merged_issues[issue.id] = issue

    # Insert into DB: epics first (for FK constraints on children)
    sorted_issues = sorted(
        merged_issues.values(),
        key=lambda i: (0 if i.issue_type == IssueType.PLAN else 1, i.id),
    )
    for issue in sorted_issues:
        db_mod.create_issue(conn, issue)
        for dep in issue.dependencies:
            try:
                db_mod.add_dependency(
                    conn,
                    dep.issue_id,
                    dep.depends_on_id,
                    dep.created_at,
                    dep.created_by,
                )
            except Exception:
                pass  # Already exists or FK violation

    return conn

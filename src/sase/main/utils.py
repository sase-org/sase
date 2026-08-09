"""Utility functions for the main entry point."""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path
from typing import NoReturn

from sase.core.paths import is_valid_sase_project_name
from sase.workspace_provider import get_workspace_name

# Type alias for project info return type
ProjectInfo = tuple[str | None, int | None, str | None]


def _get_project_name() -> str | None:
    """Get the project name via the workspace provider.

    Returns:
        The project name, or None if not in a recognized workspace.
    """
    try:
        project_name = get_workspace_name(os.getcwd()) or None
    except Exception:
        return None
    if project_name is not None and not is_valid_sase_project_name(project_name):
        return None
    if project_name is not None:
        try:
            from sase.project_aliases import resolve_project_alias_ref

            project_name = resolve_project_alias_ref(project_name)
        except Exception:
            pass
    if project_name is not None and not is_valid_sase_project_name(project_name):
        return None
    return project_name


def _get_workspace_num(project_name: str) -> int:
    """Determine workspace number from current directory.

    Args:
        project_name: The project name to check for.

    Returns:
        The workspace number (1 for main workspace, 2+ for workspace shares).
    """
    cwd = os.getcwd()
    for n in range(2, 101):
        workspace_suffix = f"{project_name}_{n}"
        if workspace_suffix in cwd:
            return n
    return 1


def kill_agent_runner_group(artifacts_dir: str) -> NoReturn:
    """Kill the agent runner's process group to stop the current agent.

    Reads ``agent_meta.json`` from *artifacts_dir* to discover the agent
    runner's PID, resolves its process-group ID, and sends ``SIGTERM`` to
    the entire group.  This is necessary because Claude Code launches Bash
    tool subprocesses in an isolated process group — killing our own group
    (``os.getpgrp()``) would never reach ``claude`` or the agent runner.

    The caller must write any required marker files **before** calling this
    function.
    """
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        runner_pid: int = meta["pid"]
        runner_pgid = os.getpgid(runner_pid)
    except (FileNotFoundError, KeyError, json.JSONDecodeError, OSError) as exc:
        print(
            f"Error: cannot determine agent runner process group: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Ignore SIGTERM so this process isn't killed if it happens to share
    # the target group (e.g. same-group fallback on some systems).
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    os.killpg(runner_pgid, signal.SIGTERM)
    sys.exit(0)


def ensure_project_file_and_get_workspace_num(
    *,
    create_missing: bool = True,
) -> ProjectInfo:
    """Get project file and workspace num for the current directory.

    By default this bootstraps a missing project file (without a BUG field,
    which can be added later via `sase ace`). Pass ``create_missing=False``
    to make the lookup read-only: when the inferred project has no existing
    ProjectSpec, nothing is created and ``(None, None, None)`` is returned.

    Args:
        create_missing: When True (default), create the project file if it
            doesn't exist yet. When False, only resolve a project whose
            ProjectSpec already exists and never create anything.

    Returns:
        Tuple of (project_file, workspace_num, project_name)
        All None if not in a recognized workspace, the project file does not
        exist and ``create_missing`` is False, or creation failed.
    """
    from sase.workflows.commit.project_file_utils import create_project_file

    project_name = _get_project_name()
    if not project_name:
        return (None, None, None)

    # Construct project file path (prefer canonical .sase, fall back to legacy .gp).
    from sase.ace.patch.project_spec_path import preferred_project_spec_path
    from sase.core.paths import sase_projects_dir

    project_dir = str(sase_projects_dir() / project_name)
    project_file = preferred_project_spec_path(project_dir, project_name)

    # Create the project file if it doesn't exist, unless the caller asked for
    # a read-only lookup (e.g. plain `sase run` launch-context resolution that
    # must not register the current checkout as a SASE project).
    if not os.path.exists(project_file):
        if not create_missing:
            return (None, None, None)
        if not create_project_file(project_name):
            return (None, None, None)

    workspace_num = _get_workspace_num(project_name)
    return (project_file, workspace_num, project_name)

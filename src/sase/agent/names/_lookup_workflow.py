"""Inspect completion of multi-agent workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.agent.names._common import is_process_alive
from sase.agent.names._lookup_artifacts import (
    iter_ace_run_artifact_dirs,
    projects_root,
)


def is_workflow_complete(name: str) -> bool | None:
    """Check whether all agents in a multi-agent workflow have completed.

    Walks ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json``
    directly and only loads files whose ``workflow_name`` matches *name*.
    Bypasses :func:`sase.core.agent_scan_facade.scan_agent_artifacts` on
    purpose: the snapshot facade has to materialize wire records for every
    artifact in the tree before any predicate can run, which previously
    measured as a ~3× regression for this hot path against the
    short-circuiting walk.

    Returns:
        ``True`` — root has ``done.json`` and no child is still alive without one.
        ``False`` — workflow exists but isn't fully complete.
        ``None`` — no agents with ``workflow_name == name`` found (not a workflow).
    """
    projects_dir = projects_root()
    if not projects_dir.exists():
        return None

    # (artifact_dir, agent_meta dict)
    workflow_agents: list[tuple[Path, dict[str, Any]]] = []
    for artifact_dir in iter_ace_run_artifact_dirs():
        meta_path = artifact_dir / "agent_meta.json"
        if not meta_path.exists():
            continue

        try:
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(data, dict):
            continue

        if data.get("workflow_name") != name:
            continue

        workflow_agents.append((artifact_dir, data))

    if not workflow_agents:
        return None

    # Find the root agent (no parent_timestamp).
    root: tuple[Path, dict[str, Any]] | None = None
    children: list[tuple[Path, dict[str, Any]]] = []
    for artifact_dir, meta in workflow_agents:
        if meta.get("parent_timestamp"):
            children.append((artifact_dir, meta))
        else:
            root = (artifact_dir, meta)

    if root is None:
        # No root found — the root's workflow_name may have been
        # stripped by claim_agent_name (it only preserves names on
        # artifacts with done.json, and the root may lack one).
        # Return None so the caller falls through to name-based
        # resolution via find_named_agent.
        return None

    root_dir, root_meta = root
    root_done = (root_dir / "done.json").exists()

    if not root_done:
        if is_process_alive(root_meta, root_dir):
            # Root still running — may write done.json later
            return False
        # Root is dead without done.json (crashed/killed between
        # workflow_state.json write and done.json write). Fall through
        # to check children so the workflow can still resolve as complete
        # when all children are done/dead.
        if not children:
            return False

    # Root is done (or dead without done.json) — check all children
    for child_dir, child_meta in children:
        if (child_dir / "done.json").exists():
            continue
        if is_process_alive(child_meta, child_dir):
            # Child is still alive and hasn't finished
            return False

    return True

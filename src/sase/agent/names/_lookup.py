"""Find named agents and inspect workflow completion status.

Consumes the agent-artifact snapshot produced by
:func:`sase.core.agent_scan_facade.scan_agent_artifacts` so name lookup
benefits from a single backend-dispatched walk of
``~/.sase/projects/*/artifacts/ace-run/*`` rather than independently
re-walking the tree per call.

Process liveness, dismissed-bundle fallback, and dismissal-prefix
semantics stay in Python — Phase 3D moves the read path only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.names._common import (
    NamedAgent,
    is_dismissed_prefixed,
    is_process_alive,
)

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import AgentArtifactRecordWire


def _ace_run_scan_options() -> Any:
    """Return the scan-facade options for ace-run-only name lookups.

    Imported lazily to avoid the agent-scan facade pulling in the TUI
    loader package at ``sase.agent`` import time (the loader package
    transitively depends back on ``sase.agent.names``).
    """
    from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire

    return AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
    )


def _projects_root() -> Path:
    return Path.home() / ".sase" / "projects"


def _meta_dict(record: AgentArtifactRecordWire) -> dict[str, Any]:
    """Project the record's ``agent_meta`` fields needed by ``is_process_alive``.

    ``is_process_alive`` only reads ``pid`` and ``stopped_at``; the wire
    carries both. Returning a dict keeps the helper untouched and avoids
    re-reading ``agent_meta.json`` from disk.
    """
    meta = record.agent_meta
    if meta is None:
        return {}
    out: dict[str, Any] = {}
    if meta.pid is not None:
        out["pid"] = meta.pid
    if meta.stopped_at is not None:
        out["stopped_at"] = meta.stopped_at
    return out


def find_named_agent(name: str, *, only_done: bool = False) -> NamedAgent | None:
    """Find a named agent by scanning all project artifacts.

    Consults the snapshot returned by
    :func:`sase.core.agent_scan_facade.scan_agent_artifacts` for every
    ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json`` whose
    ``"name"`` or ``"workflow_name"`` field matches *name*.

    Prefers running (non-done) agents over completed ones.  Exact ``name``
    matches take priority over ``workflow_name`` matches.  Among workflow
    matches, the most recent (by timestamp) is preferred.

    Args:
        name: The agent name to search for.
        only_done: When True, ignore running candidates and return only
            historical/done matches.

    Returns:
        A NamedAgent if found, or None.
    """
    projects_dir = _projects_root()
    if not projects_dir.exists():
        # Fall through to dismissed-bundle fallback below.
        return _find_named_dismissed_bundle(name)

    from sase.core.agent_scan_facade import scan_agent_artifacts

    snapshot = scan_agent_artifacts(projects_dir, _ace_run_scan_options())

    best_match: NamedAgent | None = None
    best_priority: tuple[int, str] = (0, "")

    for record in snapshot.records:
        if record.workflow_dir_name != "ace-run":
            continue
        meta = record.agent_meta
        if meta is None:
            continue

        exact = meta.name == name
        workflow = meta.workflow_name == name
        if not exact and not workflow:
            continue

        artifact_dir = Path(record.artifact_dir)
        is_done = False
        outcome: str | None = None
        if record.has_done_marker:
            is_done = True
            if record.done is not None:
                outcome = record.done.outcome
        elif is_dismissed_prefixed(name):
            # Dismissal removes done.json but preserves the prefixed
            # agent_meta.json. Treat such artifacts as historical so
            # `%w:260428.foo` and `#resume:260428.foo` still resolve.
            is_done = True
            outcome = "dismissed"

        agent = NamedAgent(
            name=name,
            artifacts_dir=str(artifact_dir),
            is_done=is_done,
            outcome=outcome,
        )

        # Running agents take priority — return immediately,
        # but only if the process is actually alive.  Parent-phase
        # artifacts (e.g. .plan) share the agent name yet never
        # write done.json; without a liveness check we'd return
        # them as "running" and block wait resolution forever.
        # For workflow matches, only return the root agent
        # (no parent_timestamp) to avoid matching intermediate steps.
        if not is_done:
            if not only_done and is_process_alive(_meta_dict(record), artifact_dir):
                if exact or not meta.parent_timestamp:
                    return agent
            continue

        # Done agent — prefer exact matches over workflow matches,
        # and most recent timestamp within each category.
        priority = (1 if exact else 0, record.timestamp)
        if priority > best_priority:
            best_match = agent
            best_priority = priority

    if best_match is None:
        # Fall back to dismissed bundles. After dismissal the artifact
        # directory may be partially or fully gone, but the bundle still
        # carries the prefixed agent_name and cl_name for historical
        # reference.
        bundle_match = _find_named_dismissed_bundle(name)
        if bundle_match is not None:
            return bundle_match

    return best_match


def _find_named_dismissed_bundle(name: str) -> NamedAgent | None:
    """Return a dismissed-bundle match for *name*, or ``None``.

    Scans ``~/.sase/dismissed_bundles`` for a bundle whose ``agent_name``
    or ``workflow_name`` equals *name*. Used as a fallback when artifact
    directories no longer carry the metadata (e.g. dismissed agents whose
    artifact dir was cleaned up).
    """
    try:
        from sase.ace.dismissed_agents import _DISMISSED_BUNDLES_DIR
    except Exception:
        return None

    bundles_dir = _DISMISSED_BUNDLES_DIR
    if not bundles_dir.is_dir():
        return None

    best: NamedAgent | None = None
    best_ts = ""
    try:
        candidates = list(bundles_dir.rglob("*.json"))
    except OSError:
        return None

    for filepath in candidates:
        if not filepath.is_file():
            continue
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        if data.get("agent_name") != name and data.get("workflow_name") != name:
            continue

        raw_suffix = data.get("raw_suffix")
        ts = raw_suffix if isinstance(raw_suffix, str) else filepath.stem
        if ts <= best_ts:
            continue
        artifacts_dir = data.get("artifacts_dir")
        best = NamedAgent(
            name=name,
            artifacts_dir=str(artifacts_dir) if artifacts_dir else str(filepath.parent),
            is_done=True,
            outcome="dismissed",
        )
        best_ts = ts

    return best


def is_workflow_complete(name: str) -> bool | None:
    """Check whether all agents in a multi-agent workflow have completed.

    Consults the snapshot returned by
    :func:`sase.core.agent_scan_facade.scan_agent_artifacts` for agents
    whose ``workflow_name`` matches *name*.

    Returns:
        ``True`` — root has ``done.json`` and no child is still alive without one.
        ``False`` — workflow exists but isn't fully complete.
        ``None`` — no agents with ``workflow_name == name`` found (not a workflow).
    """
    projects_dir = _projects_root()
    if not projects_dir.exists():
        return None

    from sase.core.agent_scan_facade import scan_agent_artifacts

    snapshot = scan_agent_artifacts(projects_dir, _ace_run_scan_options())

    # Collect all agents in this workflow
    workflow_records: list[AgentArtifactRecordWire] = []
    for record in snapshot.records:
        if record.workflow_dir_name != "ace-run":
            continue
        meta = record.agent_meta
        if meta is None:
            continue
        if meta.workflow_name == name:
            workflow_records.append(record)

    if not workflow_records:
        return None

    # Find the root agent (no parent_timestamp)
    root: AgentArtifactRecordWire | None = None
    children: list[AgentArtifactRecordWire] = []
    for record in workflow_records:
        meta = record.agent_meta
        assert meta is not None  # filtered above
        if meta.parent_timestamp:
            children.append(record)
        else:
            root = record

    if root is None:
        # No root found — the root's workflow_name may have been
        # stripped by claim_agent_name (it only preserves names on
        # artifacts with done.json, and the root may lack one).
        # Return None so the caller falls through to name-based
        # resolution via find_named_agent.
        return None

    root_dir = Path(root.artifact_dir)
    root_done = root.has_done_marker

    if not root_done:
        if is_process_alive(_meta_dict(root), root_dir):
            # Root still running — may write done.json later
            return False
        # Root is dead without done.json (crashed/killed between
        # workflow_state.json write and done.json write).  Fall through
        # to check children so the workflow can still resolve as complete
        # when all children are done/dead.
        if not children:
            return False

    # Root is done (or dead without done.json) — check all children
    for child in children:
        child_dir = Path(child.artifact_dir)
        if not child.has_done_marker and is_process_alive(_meta_dict(child), child_dir):
            # Child is still alive and hasn't finished
            return False

    return True


def get_most_recent_agent_name() -> str | None:
    """Return the name of the most recently created named agent.

    Scans ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json``
    for agents with a name, ordered by artifact directory timestamp
    (directory names are timestamps).

    Returns the name of the most recently created one, or ``None`` if
    no named agents exist.
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return None

    candidates: list[tuple[str, str]] = []  # (dir_name, agent_name)
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue

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

            name = data.get("name")
            if not name:
                continue

            # Bare ``%wait`` should never resolve to a dismissed historical
            # agent. Dismissal-prefixed names (``YYmmdd.foo``) are reserved
            # for explicit references (``%w:260428.foo``); skip them so the
            # bare-wait path stays anchored on visible/active agents.
            if isinstance(name, str) and is_dismissed_prefixed(name):
                continue

            candidates.append((artifact_dir.name, name))

    if not candidates:
        return None

    # Sort by directory name descending — most recent first
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

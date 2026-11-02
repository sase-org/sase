"""Connect detached staged recovery to the runner's workspace settlement adapter."""

from __future__ import annotations

import logging
from pathlib import Path

from sase.axe._run_agent_exec_staged_recovery_shared import read_run_metadata
from sase.axe.run_agent_exec_staged_dispatch import retain_failed_adoption_workspace
from sase.axe.run_agent_exec_staged_recovery_facts import (
    observe_runner,
    was_killed_or_discarded,
)


def retain_dead_staged_origin(
    staged_id: str, reason: str, *, artifacts_dir: str
) -> None:
    """Retain a detached origin without preventing the recovery refusal on errors."""
    try:
        _retain_dead_staged_origin(staged_id, reason, artifacts_dir=artifacts_dir)
    except Exception:  # noqa: BLE001 - pending stage still protects the origin.
        logging.getLogger(__name__).warning(
            "Could not settle dead staged origin %s", artifacts_dir, exc_info=True
        )


def _retain_dead_staged_origin(
    staged_id: str, reason: str, *, artifacts_dir: str
) -> None:
    """Publish terminal evidence and settle only the dead origin's exact claim.

    Detached recovery has no runner context. Resolve its project from persisted
    metadata or the origin's artifact location, never the recovering shell's
    environment. A live/unknown runner and explicit user kill keep their existing
    lifecycle; a transferred or dismissed claim cannot be reacquired here.
    """
    from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
    from sase.axe.run_agent_markers import build_done_marker
    from sase.running_field import get_claimed_workspaces
    from sase.turns.settlement import project_name_from_artifacts_dir
    from sase.workflows.utils import get_project_file_path
    from sase.workspace_provider.retention_record import read_workspace_retention_record

    metadata = read_run_metadata(artifacts_dir)
    if observe_runner(metadata) != "dead" or was_killed_or_discarded(
        artifacts_dir, metadata
    ):
        return
    retained = read_workspace_retention_record(artifacts_dir)
    if retained is not None and retained.payload.get("settled_at"):
        return
    project_file = metadata.get("project_file")
    if not isinstance(project_file, str) or not project_file:
        project = project_name_from_artifacts_dir(artifacts_dir)
        if not project:
            return
        project_file = get_project_file_path(project)
    timestamp = Path(artifacts_dir).name
    matching = [
        claim
        for claim in get_claimed_workspaces(project_file)
        if claim.workspace_num == metadata.get("workspace_num")
        and claim.pid == metadata.get("pid")
        and claim.artifacts_timestamp == timestamp
    ]
    if len(matching) != 1:
        return
    claim = matching[0]
    metadata.update(
        project_file=project_file,
        workflow_name=claim.workflow,
        cl_name=claim.cl_name or "",
    )
    # Write visibility before pinning: otherwise the next cleanup sweep can
    # reap a dead pinned claim that has no dismissible terminal marker.
    if not (Path(artifacts_dir) / "done.json").exists():
        done = build_done_marker(
            claim.cl_name or "",
            project_file,
            timestamp,
            timestamp,
            claim.workspace_num,
            str(metadata.get("workspace_dir") or ""),
            str(metadata.get("output_path") or ""),
            "failed",
            agent_name=metadata.get("name"),
            error=f"handoff_not_adopted: {reason}",
        )
        write_done_marker_and_update_index(artifacts_dir, done)
    retain_failed_adoption_workspace(
        staged_id,
        reason,
        artifacts_dir=artifacts_dir,
        run_metadata=metadata,
        notify_on_retain=True,
    )


__all__ = ["retain_dead_staged_origin"]

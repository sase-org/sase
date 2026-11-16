"""Connect detached staged recovery to the runner's workspace settlement adapter."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.axe._run_agent_exec_staged_recovery_shared import read_run_metadata
from sase.axe._run_agent_exec_staged_shared import StagedInlineContinuation
from sase.axe.run_agent_exec_staged_recovery_facts import (
    observe_runner,
    was_killed_or_discarded,
)


def retain_failed_adoption_workspace(
    staged_id: str,
    reason: str,
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation | None = None,
    notify_on_retain: bool = False,
) -> None:
    """Settle a failed origin through shared policy, pinning on probe failure."""
    try:
        _retain_failed_adoption_workspace(
            staged_id,
            reason,
            artifacts_dir=artifacts_dir,
            run_metadata=run_metadata,
            continuation=continuation,
            notify_on_retain=notify_on_retain,
        )
    except Exception as exc:  # noqa: BLE001 - also pin before receipt publication.
        try:
            _hold_failed_adoption_claim(
                artifacts_dir=artifacts_dir,
                run_metadata=run_metadata,
                continuation=continuation,
                error=exc,
            )
        except Exception as hold_exc:  # noqa: BLE001 - receipt remains durable.
            print(
                f"Could not pin staged starter after retention error: {hold_exc}",
                file=sys.stderr,
            )


def _hold_failed_adoption_claim(
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation | None,
    error: Exception,
) -> None:
    """Pin the exact starter claim if policy evidence collection failed."""
    from sase.running_field import get_claimed_workspaces, hold_workspace_claim

    context = getattr(continuation, "ctx", None)
    state = getattr(continuation, "state", None)
    raw_project_file = run_metadata.get("project_file") or os.environ.get(
        "SASE_AGENT_PROJECT_FILE"
    )
    if not raw_project_file:
        raw_project_file = getattr(context, "project_file", None)
    if not isinstance(raw_project_file, str) or not raw_project_file:
        print(
            f"Could not pin staged starter after retention error; "
            f"project identity is unavailable: {error}",
            file=sys.stderr,
        )
        return
    raw_workspace_num = run_metadata.get("workspace_num")
    try:
        workspace_num = int(raw_workspace_num or 0)
    except (TypeError, ValueError):
        workspace_num = 0
    if workspace_num <= 0:
        state_workspace_num = getattr(state, "workspace_num", None)
        workspace_num = (
            state_workspace_num
            if isinstance(state_workspace_num, int)
            and not isinstance(state_workspace_num, bool)
            else 0
        )
    raw_pid = run_metadata.get("pid")
    pid = (
        raw_pid if isinstance(raw_pid, int) and not isinstance(raw_pid, bool) else None
    )
    raw_cl_name = run_metadata.get("cl_name") or run_metadata.get("patch_name")
    cl_name = raw_cl_name if isinstance(raw_cl_name, str) else ""
    if not cl_name:
        context_cl_name = getattr(context, "cl_name", None)
        cl_name = context_cl_name if isinstance(context_cl_name, str) else ""
    workflow_value = run_metadata.get("workflow_name")
    workflow = workflow_value if isinstance(workflow_value, str) else ""
    if not workflow:
        context_workflow = getattr(context, "workflow_name", None)
        workflow = context_workflow if isinstance(context_workflow, str) else ""
    timestamp = Path(artifacts_dir).name
    try:
        candidates = [
            claim
            for claim in get_claimed_workspaces(raw_project_file)
            if claim.workspace_num == workspace_num
            and (claim.cl_name or "") == cl_name
            and (claim.artifacts_timestamp or "") == timestamp
            and (pid is None or claim.pid == pid)
            and (not workflow or claim.workflow == workflow)
        ]
    except Exception as claims_exc:  # noqa: BLE001 - log, never release.
        print(
            f"Could not inspect staged starter claim after retention error: "
            f"{claims_exc}",
            file=sys.stderr,
        )
        return
    if len(candidates) != 1:
        print(
            "Could not pin staged starter after retention error; "
            f"found {len(candidates)} exact claim candidates: {error}",
            file=sys.stderr,
        )
        return
    claim = candidates[0]
    held = hold_workspace_claim(
        raw_project_file,
        claim.workspace_num,
        claim.workflow,
        claim.cl_name or "",
        claim.artifacts_timestamp or "",
        caller_tag="staged-retention-fail-closed",
        expected_pid=claim.pid,
    )
    if not held.success:
        print(
            f"Could not pin staged starter after retention error: "
            f"{held.error or error}",
            file=sys.stderr,
        )


def _retain_failed_adoption_workspace(
    staged_id: str,
    reason: str,
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation | None,
    notify_on_retain: bool,
) -> None:
    """Apply shared policy to the exact staged starter claim and repositories."""
    from sase.running_field import get_claimed_workspaces
    from sase.turns.workspace_retention import (
        WorkspaceRetentionOwner,
        discover_workspace_retention_repos,
        settle_stranded_workspace,
    )

    raw_workspace_num = run_metadata.get("workspace_num")
    try:
        workspace_num = int(raw_workspace_num or 0)
    except (TypeError, ValueError):
        workspace_num = 0
    context = getattr(continuation, "ctx", None)
    state = getattr(continuation, "state", None)
    if workspace_num <= 0:
        state_workspace_num = getattr(state, "workspace_num", None)
        if isinstance(state_workspace_num, int) and not isinstance(
            state_workspace_num, bool
        ):
            workspace_num = state_workspace_num
    raw_pid = run_metadata.get("pid")
    pid = (
        raw_pid
        if isinstance(raw_pid, int) and not isinstance(raw_pid, bool)
        else os.getpid()
    )
    raw_cl_name = run_metadata.get("cl_name") or run_metadata.get("patch_name")
    cl_name = raw_cl_name if isinstance(raw_cl_name, str) else ""
    if not cl_name:
        context_cl_name = getattr(context, "cl_name", None)
        cl_name = context_cl_name if isinstance(context_cl_name, str) else ""
    artifacts_timestamp = Path(artifacts_dir).name
    raw_project_file = run_metadata.get("project_file") or os.environ.get(
        "SASE_AGENT_PROJECT_FILE"
    )
    if not raw_project_file:
        raw_project_file = getattr(context, "project_file", None)
    if not isinstance(raw_project_file, str) or not raw_project_file:
        raise RuntimeError("staged starter has no project-file identity")
    project_file = raw_project_file
    raw_checkout_dir = run_metadata.get("workspace_dir")
    checkout_dir = raw_checkout_dir if isinstance(raw_checkout_dir, str) else None
    if not checkout_dir:
        state_workspace_dir = getattr(state, "workspace_dir", None)
        checkout_dir = (
            state_workspace_dir if isinstance(state_workspace_dir, str) else None
        )
    raw_workflow = run_metadata.get("workflow_name")
    workflow = raw_workflow if isinstance(raw_workflow, str) else ""
    if not workflow:
        context_workflow = getattr(context, "workflow_name", None)
        workflow = context_workflow if isinstance(context_workflow, str) else ""
    if not workflow:
        claims = get_claimed_workspaces(project_file)
        matching = [
            claim
            for claim in claims
            if claim.workspace_num == workspace_num
            and claim.pid == pid
            and (claim.cl_name or "") == cl_name
            and (claim.artifacts_timestamp or "") == artifacts_timestamp
        ]
        if len(matching) == 1:
            workflow = matching[0].workflow

    if not workflow or not artifacts_timestamp:
        return

    repos, origin_repo_ids = discover_workspace_retention_repos(
        artifacts_dir,
        checkout_dir,
    )
    owner = WorkspaceRetentionOwner(
        project_file=project_file,
        workspace_num=workspace_num,
        workflow=workflow,
        cl_name=cl_name,
        artifacts_timestamp=artifacts_timestamp,
        pid=pid,
        artifacts_dir=artifacts_dir,
        checkout_dir=checkout_dir,
        repos=repos,
        origin_repo_ids=origin_repo_ids,
        staged_id=staged_id,
        session_id=(
            str(run_metadata.get("agent_session"))
            if run_metadata.get("agent_session")
            else None
        ),
        turn_id=(str(run_metadata.get("name")) if run_metadata.get("name") else None),
        terminal_reason=reason,
        notify_on_retain=notify_on_retain,
    )
    settle_stranded_workspace(owner)


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


__all__ = [
    "retain_dead_staged_origin",
    "retain_failed_adoption_workspace",
]

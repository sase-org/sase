"""Shared stale-running custody helpers used by more than one sweep module."""

from pathlib import Path

from sase.core.time import local_now
from sase.running_field import (
    WorkspaceClaim,
    get_workspace_directory_for_num,
)
from sase.workspace_provider.occupant import clear_owned_occupant_record


def staged_origin_retains_claim(project_file: str, claim: WorkspaceClaim) -> bool:
    if not claim.artifacts_timestamp:
        return False
    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
        from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME

        artifacts = resolve_agent_artifact_timestamp_path(
            Path(project_file).parent.name, "ace-run", claim.artifacts_timestamp
        )
        # Presence, including malformed evidence, protects custody. Receipt
        # success alone cannot release a claim before successor delivery.
        (artifacts / STAGED_HANDOFF_FILENAME).lstat()
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return True


def pending_retention_retains_claim(project_file: str, claim: WorkspaceClaim) -> bool:
    """Honor an exact-owner pending-retention fact until settlement decides.

    A pending fact protects the exact workspace/workflow/cl/timestamp/pid
    owner while a fresh-interpreter retry or guarded settlement is still
    outstanding. Once a terminal retention record settles, the pending fact
    is stale and no longer blocks TTL-driven cleanup.
    """
    if not claim.artifacts_timestamp:
        return False
    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
        from sase.turns.workspace_retention import (
            pending_retention_matches_owner,
            read_pending_retention,
        )
        from sase.workspace_provider.retention_record import (
            read_workspace_retention_record,
        )

        artifacts = resolve_agent_artifact_timestamp_path(
            Path(project_file).parent.name, "ace-run", claim.artifacts_timestamp
        )
        pending = read_pending_retention(artifacts)
        if pending is None:
            return False
        record = read_workspace_retention_record(artifacts)
        if record is not None and not record.unresolved:
            return False
        from sase.turns.workspace_retention import WorkspaceRetentionOwner

        owner = WorkspaceRetentionOwner(
            project_file=project_file,
            workspace_num=claim.workspace_num,
            workflow=claim.workflow,
            cl_name=claim.cl_name or "",
            artifacts_timestamp=claim.artifacts_timestamp or "",
            pid=claim.pid,
            artifacts_dir=str(artifacts),
        )
        return pending_retention_matches_owner(pending, owner)
    except Exception:
        return False


def settle_stale_retention_record(project_file: str, claim: WorkspaceClaim) -> None:
    """Keep recovery surfaces in sync after releasing a terminal held claim."""
    if not claim.pinned or not claim.artifacts_timestamp:
        return
    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
        from sase.workspace_provider.retention_record import (
            mark_workspace_retention_settled,
        )

        artifacts = resolve_agent_artifact_timestamp_path(
            Path(project_file).parent.name, "ace-run", claim.artifacts_timestamp
        )
        mark_workspace_retention_settled(
            artifacts, reason="stale_cleanup", settled_at=local_now().isoformat()
        )
    except Exception:
        return


def clear_stale_occupant_record(project_file: str, claim: WorkspaceClaim) -> None:
    """Best-effort clear of a stale claim's checkout occupant marker."""
    if claim.workspace_num <= 1:
        return
    try:
        project_name = Path(project_file).parent.name
        workspace_dir, _ = get_workspace_directory_for_num(
            claim.workspace_num, project_name, clean=False
        )
    except Exception:
        return
    clear_owned_occupant_record(
        workspace_dir,
        claim.pid,
        artifacts_timestamp=claim.artifacts_timestamp,
        workflow=claim.workflow,
        cl_name=claim.cl_name,
        workspace_num=claim.workspace_num,
    )

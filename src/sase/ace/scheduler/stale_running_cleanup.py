"""Stale RUNNING entry cleanup utilities for the axe scheduler."""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.core.time import local_now
from sase.running_field import (
    WorkspaceClaim,
    get_claimed_workspaces,
    get_workspace_directory_for_num,
    release_workspace,
)
from sase.workspace_provider.occupant import clear_owned_occupant_record

from ..hooks.processes import is_process_running

_CLAIM_TIMESTAMP_FORMATS = ("%Y%m%d%H%M%S", "%Y%m%d_%H%M%S", "%y%m%d_%H%M%S")
_DEFAULT_HELD_CLAIM_TTL_DAYS = 14


def _held_agent_artifacts_exist(project_file: str, artifacts_timestamp: str) -> bool:
    """Conservatively check whether a held agent still has artifacts."""
    try:
        from sase.core.agent_artifact_paths import (
            ACE_RUN_WORKFLOW_DIR,
            resolve_agent_artifact_timestamp_path,
        )

        project_name = Path(project_file).parent.name
        return resolve_agent_artifact_timestamp_path(
            project_name,
            ACE_RUN_WORKFLOW_DIR,
            artifacts_timestamp,
        ).is_dir()
    except Exception:
        return True


def _held_done_marker_exists(project_file: str, artifacts_timestamp: str) -> bool:
    """Conservatively check whether a held agent has a dismissible done marker.

    Read failures fail closed (assume a marker exists) so a transient path
    error cannot reap a claim that ACE could still surface.
    """
    try:
        from sase.core.agent_artifact_paths import (
            ACE_RUN_WORKFLOW_DIR,
            resolve_agent_artifact_timestamp_path,
        )

        project_name = Path(project_file).parent.name
        artifacts_dir = resolve_agent_artifact_timestamp_path(
            project_name,
            ACE_RUN_WORKFLOW_DIR,
            artifacts_timestamp,
        )
        return (artifacts_dir / "done.json").is_file()
    except Exception:
        return True


def _held_claim_ttl_days() -> int:
    """Return ``workspace.held_claim_ttl_days``, defaulting to 14 on error."""
    try:
        from sase.config import load_merged_config
        from sase.workspace_provider.store import held_claim_ttl_days_from_config

        return held_claim_ttl_days_from_config(load_merged_config())
    except Exception:
        return _DEFAULT_HELD_CLAIM_TTL_DAYS


def _parse_claim_timestamp(artifacts_timestamp: str) -> datetime | None:
    """Parse a RUNNING-field artifacts timestamp, or None if unparseable."""
    for fmt in _CLAIM_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(artifacts_timestamp, fmt)
        except ValueError:
            continue
    return None


def _now() -> datetime:
    return local_now()


def _held_claim_exceeds_ttl(
    artifacts_timestamp: str,
    ttl_days: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a pinned claim's launch stamp is older than the TTL.

    ``ttl_days <= 0`` disables age-based release. Unparseable stamps keep
    today's never-release behavior.
    """
    if ttl_days <= 0:
        return False
    parsed = _parse_claim_timestamp(artifacts_timestamp)
    if parsed is None:
        return False
    current = _now() if now is None else now
    return current - parsed > timedelta(days=ttl_days)


def _monitor_claim_is_releasable(project_file: str, claim: WorkspaceClaim) -> bool:
    """Return whether a dead-pid monitor workspace claim is safe to release.

    A monitor owns its workspace for the length of its command, and a dead
    supervisor pid alone is exactly the state a not-yet-reconciled monitor is
    in. Only release once the owning monitor member's own markers say it is
    terminal; any failure to read that state fails closed (not releasable),
    matching the conservative pinned-artifacts check above.
    """
    if not claim.artifacts_timestamp:
        return True
    try:
        from sase.core.agent_artifact_paths import (
            ACE_RUN_WORKFLOW_DIR,
            resolve_agent_artifact_timestamp_path,
        )
        from sase.monitor.store import read_monitor_marker

        project_name = Path(project_file).parent.name
        artifacts_dir = resolve_agent_artifact_timestamp_path(
            project_name, ACE_RUN_WORKFLOW_DIR, claim.artifacts_timestamp
        )
        record = read_monitor_marker(project_name, str(artifacts_dir))
    except Exception:
        return False
    return record is None or record.is_terminal


def cleanup_stale_running_entries(
    log_fn: Callable[[str, str | None], None] | None = None,
    *,
    skip_monitor_claims: bool = False,
) -> int:
    """Release workspace claims for processes that are no longer running.

    Iterates through all project files and checks each RUNNING entry's PID.
    If the process is no longer running, the workspace claim is released.
    Lifecycle filtering is intentionally not applied: stale claims in disabled
    projects (including legacy archived/closed states) still need cleanup.

    Args:
        log_fn: Optional logging function (message, style).
        skip_monitor_claims: When True, leave every monitor-workflow claim
            (``MONITOR_WORKSPACE_CLAIM_WORKFLOW``) untouched this sweep,
            regardless of pid or terminal state. Set by the caller when it
            could not reconcile dead monitor supervisors first, so a live
            lane's workspace is never handed to another agent on the strength
            of stale reconciliation state. The flag also means the monitor
            package may be unimportable; this sweep does not import or
            touch it.

    Returns:
        Number of stale workspace claims released.
    """
    from sase.gate_turn.claims import (
        GATE_WORKSPACE_CLAIM_WORKFLOW,
        gate_claim_is_releasable,
    )

    if skip_monitor_claims:
        # The caller already committed to leaving monitor claims alone, and
        # the monitor package may be unimportable. Identify those claims by
        # the workflow label without importing sase.monitor.start so they
        # cannot fall through to the generic stale-PID release path.
        monitor_workflow = "ace-monitor"
    else:
        from sase.monitor.start import MONITOR_WORKSPACE_CLAIM_WORKFLOW

        monitor_workflow = MONITOR_WORKSPACE_CLAIM_WORKFLOW

    released_count = 0
    held_ttl_days: int | None = None

    for project_file in _get_all_project_files():
        claims = get_claimed_workspaces(project_file)

        for claim in claims:
            # Protect pending adoption independently of reconciliation ordering.
            # Once pinned, the origin follows the normal held-claim lifecycle,
            # including its configured TTL and explicit dismissal.
            if not claim.pinned and _staged_origin_retains_claim(project_file, claim):
                continue
            hijack_record = _matching_hijack_record(project_file, claim)
            if hijack_record is _HIJACK_LOOKUP_FAILED:
                continue
            if isinstance(hijack_record, dict):
                hijack_released, held_ttl_days = _apply_hijack_custody(
                    project_file,
                    claim,
                    hijack_record,
                    held_ttl_days=held_ttl_days,
                    log_fn=log_fn,
                )
                if hijack_released:
                    released_count += 1
                continue
            is_monitor_claim = claim.workflow == monitor_workflow
            is_gate_claim = claim.workflow == GATE_WORKSPACE_CLAIM_WORKFLOW
            if is_monitor_claim and skip_monitor_claims:
                continue

            if claim.pinned:
                if not claim.artifacts_timestamp:
                    continue
                if is_process_running(claim.pid):
                    continue
                # Terminal holds follow the configured TTL. A staged origin
                # can also be pinned just before its runner crashes without
                # writing done.json; recovery still owns that pending marker
                # and must get a chance to publish terminal evidence.
                if _held_agent_artifacts_exist(
                    project_file, claim.artifacts_timestamp
                ) and (
                    _held_done_marker_exists(project_file, claim.artifacts_timestamp)
                    or _staged_origin_retains_claim(project_file, claim)
                ):
                    if held_ttl_days is None:
                        held_ttl_days = _held_claim_ttl_days()
                    if not _held_claim_exceeds_ttl(
                        claim.artifacts_timestamp, held_ttl_days
                    ):
                        continue
            elif is_process_running(claim.pid):
                continue
            elif is_monitor_claim and not _monitor_claim_is_releasable(
                project_file, claim
            ):
                continue
            elif is_gate_claim and not gate_claim_is_releasable(project_file, claim):
                continue
            if _pending_retention_retains_claim(project_file, claim):
                continue

            released = release_workspace(
                project_file,
                claim.workspace_num,
                claim.workflow,
                claim.cl_name,
                caller_tag="stale-cleanup",
                expected_pid=claim.pid,
                artifacts_timestamp=claim.artifacts_timestamp,
            )
            if not released.success:
                continue
            _settle_stale_retention_record(project_file, claim)
            _clear_stale_occupant_record(project_file, claim)
            released_count += 1

            if log_fn:
                cl_info = f" for PR {claim.cl_name}" if claim.cl_name else ""
                log_fn(
                    f"Released stale{' held' if claim.pinned else ''} "
                    f"workspace #{claim.workspace_num} "
                    f"({claim.workflow}){cl_info} - PID {claim.pid} not running",
                    "cyan",
                )

    return released_count


_HIJACK_LOOKUP_FAILED = object()


def _matching_hijack_record(
    project_file: str, claim: WorkspaceClaim
) -> dict[str, Any] | object | None:
    """Return the active hijack record, or a sentinel when lookup itself failed.

    Lookup failures fail closed: the claim stays until a later sweep can
    prove it is not hijacked.
    """
    try:
        from sase.agent.hijack.custody import matching_active_record

        return matching_active_record(project_file, claim)
    except Exception:
        return _HIJACK_LOOKUP_FAILED


def _apply_hijack_custody(
    project_file: str,
    claim: WorkspaceClaim,
    record: dict[str, Any],
    *,
    held_ttl_days: int | None,
    log_fn: Callable[[str, str | None], None] | None,
) -> tuple[bool, int | None]:
    """Retain or expire one hijack-owned claim. Never fall through to generic release."""
    from sase.agent.hijack.custody import expire_hijack_hold, hijacked_at_exceeds_ttl

    state = str(record.get("state") or "")
    if state in {"requested", "stopping", "resolving"}:
        return False, held_ttl_days
    if state != "held":
        return False, held_ttl_days
    if is_process_running(claim.pid):
        return False, held_ttl_days
    if held_ttl_days is None:
        held_ttl_days = _held_claim_ttl_days()
    hijacked_at = record.get("hijacked_at")
    stamp = hijacked_at if isinstance(hijacked_at, str) else None
    if not hijacked_at_exceeds_ttl(stamp, held_ttl_days):
        return False, held_ttl_days
    try:
        expired = expire_hijack_hold(project_file, claim, record)
    except Exception:
        return False, held_ttl_days
    if not expired:
        return False, held_ttl_days
    _settle_stale_retention_record(project_file, claim)
    _clear_stale_occupant_record(project_file, claim)
    if log_fn:
        cl_info = f" for PR {claim.cl_name}" if claim.cl_name else ""
        log_fn(
            f"Released expired hijack workspace #{claim.workspace_num} "
            f"({claim.workflow}){cl_info} - held claim TTL elapsed",
            "cyan",
        )
    return True, held_ttl_days


def _staged_origin_retains_claim(project_file: str, claim: WorkspaceClaim) -> bool:
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


def _pending_retention_retains_claim(project_file: str, claim: WorkspaceClaim) -> bool:
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


def _settle_stale_retention_record(project_file: str, claim: WorkspaceClaim) -> None:
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
            artifacts, reason="stale_cleanup", settled_at=_now().isoformat()
        )
    except Exception:
        return


def _clear_stale_occupant_record(project_file: str, claim: WorkspaceClaim) -> None:
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


def _get_all_project_files() -> list[str]:
    """Get all project file paths from ~/.sase/projects/.

    Returns:
        List of paths to project spec files for all projects. Prefers the
        canonical ``.sase`` extension and falls back to legacy ``.gp``.
    """
    from sase.ace.patch.project_spec_path import (
        active_project_spec_filename,
        legacy_active_project_spec_filename,
    )

    projects_dir = sase_projects_dir()
    if not projects_dir.exists():
        return []

    project_files: list[str] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        canonical = project_dir / active_project_spec_filename(project_dir.name)
        if canonical.exists():
            project_files.append(str(canonical))
            continue
        legacy = project_dir / legacy_active_project_spec_filename(project_dir.name)
        if legacy.exists():
            project_files.append(str(legacy))

    return project_files

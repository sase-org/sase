"""Stale RUNNING entry cleanup utilities for the axe scheduler."""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.core.time import local_now
from sase.running_field import (
    WorkspaceClaim,
    get_claimed_workspaces,
    get_workspace_directory_for_num,
    release_workspace,
)
from sase.workspace_provider.occupant import clear_occupant_record

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
    from sase.gate_shell.claims import (
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
            is_monitor_claim = claim.workflow == monitor_workflow
            is_gate_claim = claim.workflow == GATE_WORKSPACE_CLAIM_WORKFLOW
            if is_monitor_claim and skip_monitor_claims:
                continue

            if claim.pinned:
                if not claim.artifacts_timestamp:
                    continue
                if is_process_running(claim.pid):
                    continue
                # Keep a pinned dead claim only while it still has a
                # dismissal path (artifacts + done.json) and is younger
                # than the held-claim TTL. No done.json means ACE can
                # never offer dismissal, so the conservative skip would
                # preserve a leak. The claim's own PID is already dead,
                # so no finalizer can still write the marker.
                if _held_agent_artifacts_exist(
                    project_file, claim.artifacts_timestamp
                ) and _held_done_marker_exists(project_file, claim.artifacts_timestamp):
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

            release_workspace(
                project_file,
                claim.workspace_num,
                claim.workflow,
                claim.cl_name,
                caller_tag="stale-cleanup",
            )
            _clear_stale_occupant_record(project_file, claim.workspace_num)
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


def _clear_stale_occupant_record(project_file: str, workspace_num: int) -> None:
    """Best-effort clear of a stale claim's checkout occupant marker."""
    if workspace_num <= 1:
        return
    try:
        project_name = Path(project_file).parent.name
        workspace_dir, _ = get_workspace_directory_for_num(
            workspace_num, project_name, clean=False
        )
    except Exception:
        return
    clear_occupant_record(workspace_dir)


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

"""Stale RUNNING entry sweep for the axe scheduler."""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.core.time import local_now
from sase.running_field import (
    WorkspaceClaim,
    get_claimed_workspaces,
    release_workspace,
)

from ..hooks.processes import is_process_running
from ._stale_running_hijack import (
    HIJACK_LOOKUP_FAILED,
    apply_hijack_custody,
    drain_pending_settlement_repairs,
    matching_hijack_record,
    reconcile_all_resolving_records,
    reconcile_all_latched_records,
    resolving_workspace_retains_claim,
)
from ._stale_running_shared import (
    SweepProcSnapshot,
    clear_stale_occupant_record,
    held_claim_ttl_days as _held_claim_ttl_days,
    pending_retention_retains_claim,
    settle_stale_retention_record,
    staged_origin_retains_claim,
)
from .stale_running_leak import repair_leaked_monitor_claim

_CLAIM_TIMESTAMP_FORMATS = ("%Y%m%d%H%M%S", "%Y%m%d_%H%M%S", "%y%m%d_%H%M%S")


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


def _monitor_claim_is_releasable(
    project_file: str,
    claim: WorkspaceClaim,
    proc_snapshot: SweepProcSnapshot | None = None,
) -> bool:
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
        record = read_monitor_marker(
            project_name,
            str(artifacts_dir),
            proc_snapshot=proc_snapshot.get() if proc_snapshot else None,
        )
    except Exception:
        return False
    return record is None or record.is_terminal


def _gate_claim_exceeds_held_ttl(
    project_file: str,
    claim: WorkspaceClaim,
    held_ttl_days: int,
) -> bool:
    """Return whether a dead-pid non-terminal gate claim outlived the held TTL.

    A gate whose settler died mid-``settling`` — no ``done.json`` and no
    decision record — never reaches a terminal marker, so the plain
    ``gate_claim_is_releasable`` rule would hold its workspace forever. Once
    the claim stamp is older than the held-claim TTL the workspace releases
    while the gate record itself is left untouched. Every unreadable or
    ambiguous state fails closed.
    """
    if not claim.artifacts_timestamp:
        return False
    if is_process_running(claim.pid):
        return False
    try:
        from sase.core.agent_artifact_paths import (
            ACE_RUN_WORKFLOW_DIR,
            resolve_agent_artifact_timestamp_path,
        )
        from sase.gate_turn.store import read_gate_turn_marker

        project_name = Path(project_file).parent.name
        artifacts_dir = resolve_agent_artifact_timestamp_path(
            project_name, ACE_RUN_WORKFLOW_DIR, claim.artifacts_timestamp
        )
        record = read_gate_turn_marker(project_name, str(artifacts_dir))
    except Exception:
        return False
    if record is None or record.is_terminal:
        return False
    return _held_claim_exceeds_ttl(claim.artifacts_timestamp, held_ttl_days)


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
        from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW

        monitor_workflow = MONITOR_WORKSPACE_CLAIM_WORKFLOW

    released_count = 0
    held_ttl_days: int | None = None

    # Reconcile every resolving record once per sweep, whoever holds the
    # claim, then drain pending settlement repairs even when no resolving
    # record remains. Both are fail-closed and best-effort.
    reconcile_all_resolving_records(log_fn=log_fn)
    reconcile_all_latched_records(log_fn=log_fn)
    drain_pending_settlement_repairs()

    unchanged_skips = 0
    proc_snapshot = SweepProcSnapshot()

    def _count_unchanged_skip() -> None:
        nonlocal unchanged_skips
        unchanged_skips += 1

    for project_file in _get_all_project_files():
        claims = get_claimed_workspaces(project_file)

        for claim in claims:
            # Protect pending adoption independently of reconciliation ordering.
            # Once pinned, the origin follows the normal held-claim lifecycle,
            # including its configured TTL and explicit dismissal.
            if not claim.pinned and staged_origin_retains_claim(project_file, claim):
                continue
            hijack_record = matching_hijack_record(project_file, claim)
            if hijack_record is HIJACK_LOOKUP_FAILED:
                continue
            if isinstance(hijack_record, dict):
                hijack_released, held_ttl_days = apply_hijack_custody(
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

            # Already-leaked epic-launch monitor claims settle before the
            # pinned-hold TTL would release them: publish their stray
            # decision sheets, then re-run retention settlement with the
            # corrected starter-evidence scope. A clean result releases
            # here; other dirt keeps the normal pinned path below.
            if (
                claim.pinned
                and is_monitor_claim
                and claim.artifacts_timestamp
                and not is_process_running(claim.pid)
                and repair_leaked_monitor_claim(
                    project_file,
                    claim,
                    log_fn=log_fn,
                    on_skip=_count_unchanged_skip,
                    proc_snapshot=proc_snapshot,
                )
            ):
                released_count += 1
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
                    or staged_origin_retains_claim(project_file, claim)
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
                project_file, claim, proc_snapshot
            ):
                continue
            elif is_gate_claim and not gate_claim_is_releasable(project_file, claim):
                # A settler that died mid-settling never writes a terminal
                # marker, so the rule above would hold its workspace forever.
                # Bound that hold with the held-claim TTL instead; the gate
                # record itself is left untouched.
                if held_ttl_days is None:
                    held_ttl_days = _held_claim_ttl_days()
                if not _gate_claim_exceeds_held_ttl(project_file, claim, held_ttl_days):
                    continue
            if pending_retention_retains_claim(project_file, claim):
                continue
            if resolving_workspace_retains_claim(project_file, claim):
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
            settle_stale_retention_record(project_file, claim)
            clear_stale_occupant_record(project_file, claim)
            released_count += 1

            if log_fn:
                cl_info = f" for PR {claim.cl_name}" if claim.cl_name else ""
                log_fn(
                    f"Released stale{' held' if claim.pinned else ''} "
                    f"workspace #{claim.workspace_num} "
                    f"({claim.workflow}){cl_info} - PID {claim.pid} not running",
                    "cyan",
                )

    if unchanged_skips and log_fn:
        log_fn(
            f"{unchanged_skips} held workspace{'s' if unchanged_skips != 1 else ''} "
            "unchanged; skipped re-settlement",
            "dim",
        )

    return released_count


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

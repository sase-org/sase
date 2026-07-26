"""Public API for SDD repository health and transactional integration."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path

from sase.sdd._repository_health import (
    SddRepositoryHealthError,
    default_git_runner,
    format_git_error,
    inspect_sdd_repository,
    require_sdd_repository_health as _require_sdd_repository_health,
    safe_git_error_text,
    sdd_rollback_mismatch,
    sdd_rollback_observation_delta,
    sdd_state_blockers,
)
from sase.sdd._repository_integration import (
    integrate_sdd_repository_transaction as _integrate_sdd_repository_transaction,
)
from sase.sdd._repository_types import (
    EventLogger,
    GitRunner,
    LockFactory,
    SddIntegrationOutcome,
    SddIntegrationStatus,
    SddRepositoryState,
)

_logger = logging.getLogger(__name__)


def require_sdd_repository_health(
    repo_root: Path,
    *,
    expected_branch: str | None = None,
) -> SddRepositoryState:
    """Fail closed unless *repo_root* is attached and free of Git operations."""
    return _require_sdd_repository_health(
        repo_root,
        expected_branch=expected_branch,
        runner=default_git_runner,
    )


def integrate_sdd_repository(
    repo_root: Path,
    *,
    beads_dir: Path | None = None,
    upstream: str = "@{upstream}",
    fetch: bool = True,
    expected_branch: str | None = None,
    op_prefix: str = "sdd.integrate",
    git_runner: GitRunner | None = None,
    lock_factory: LockFactory | None = None,
    event_logger: EventLogger | None = None,
) -> SddIntegrationOutcome:
    """Fetch and rebase an SDD checkout, restoring it on every failed rebase.

    Successful integrations with an upstream update the shared freshness marker.
    """
    outcome = integrate_sdd_repository_transaction(
        repo_root,
        beads_dir=beads_dir,
        upstream=upstream,
        fetch=fetch,
        expected_branch=expected_branch,
        op_prefix=op_prefix,
        git_runner=git_runner,
        lock_factory=lock_factory,
        event_logger=event_logger,
    )
    if outcome.succeeded and outcome.upstream_present:
        from sase.sdd._integration_marker import mark_bead_integration

        try:
            mark_bead_integration(repo_root.expanduser().resolve())
        except OSError:
            # The marker is a freshness optimization. Its failure must not turn a
            # completed fetch/rebase into an integration failure.
            pass
    return outcome


def integrate_machine_managed_sdd_repository(
    repo_root: Path,
    *,
    beads_dir: Path | None = None,
    upstream: str = "@{upstream}",
    fetch: bool = True,
    expected_branch: str | None = None,
    op_prefix: str = "sdd.integrate",
    git_runner: GitRunner | None = None,
    lock_factory: LockFactory | None = None,
    event_logger: EventLogger | None = None,
    clock: Callable[[], float] | None = None,
    recovery_cooldown_seconds: float | None = None,
) -> SddIntegrationOutcome:
    """Integrate a machine-owned checkout and recover a wedged clone once.

    The ordinary integration API remains fail-closed and non-destructive. Only
    callers that own disposable workspace sidecar checkouts should use this
    operation: it snapshots local state, resets to the configured upstream, and
    retains the snapshot for manual inspection.
    """
    outcome = integrate_sdd_repository(
        repo_root,
        beads_dir=beads_dir,
        upstream=upstream,
        fetch=fetch,
        expected_branch=expected_branch,
        op_prefix=op_prefix,
        git_runner=git_runner,
        lock_factory=lock_factory,
        event_logger=event_logger,
    )
    if outcome.succeeded or outcome.status in {
        SddIntegrationStatus.REMOTE_UNAVAILABLE,
        SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS,
    }:
        if outcome.succeeded:
            _safe_reap_recovery_residue(
                repo_root,
                clock=clock,
                git_runner=git_runner,
                lock_factory=lock_factory,
            )
        return outcome

    from sase.sdd._repository_recovery import (
        recover_machine_managed_sdd_repository,
    )

    recovered = recover_machine_managed_sdd_repository(
        repo_root,
        original=outcome,
        beads_dir=beads_dir,
        expected_branch=expected_branch,
        op_prefix=op_prefix,
        git_runner=git_runner,
        lock_factory=lock_factory,
        clock=clock,
        recovery_cooldown_seconds=recovery_cooldown_seconds,
        event_logger=event_logger,
    )
    if recovered.succeeded and recovered.upstream_present:
        _safe_reap_recovery_residue(
            repo_root,
            clock=clock,
            git_runner=git_runner,
            lock_factory=lock_factory,
        )
        from sase.sdd._integration_marker import mark_bead_integration

        try:
            mark_bead_integration(repo_root.expanduser().resolve())
        except OSError:
            pass
    return recovered


def _safe_reap_recovery_residue(
    repo_root: Path,
    *,
    clock: Callable[[], float] | None,
    git_runner: GitRunner | None,
    lock_factory: LockFactory | None,
) -> None:
    from sase.sdd._repository_recovery_reaper import (
        safe_reap_sdd_recovery_snapshots,
    )

    safe_reap_sdd_recovery_snapshots(
        repo_root,
        now=clock() if clock is not None else None,
        git_runner=git_runner,
        lock_factory=lock_factory,
        op_prefix="sdd.recovery_reap",
        logger=lambda message: _logger.debug(message),
    )


def integrate_sdd_repository_transaction(
    repo_root: Path,
    *,
    beads_dir: Path | None = None,
    upstream: str = "@{upstream}",
    fetch: bool = True,
    expected_branch: str | None = None,
    op_prefix: str = "sdd.integrate",
    git_runner: GitRunner | None = None,
    lock_factory: LockFactory | None = None,
    event_logger: EventLogger | None = None,
) -> SddIntegrationOutcome:
    """Run one transactional fetch/rebase attempt."""
    return _integrate_sdd_repository_transaction(
        repo_root,
        beads_dir=beads_dir,
        upstream=upstream,
        fetch=fetch,
        expected_branch=expected_branch,
        op_prefix=op_prefix,
        git_runner=git_runner or default_git_runner,
        lock_factory=lock_factory,
        event_logger=event_logger,
    )


__all__ = [
    "SddIntegrationOutcome",
    "SddIntegrationStatus",
    "SddRepositoryHealthError",
    "integrate_machine_managed_sdd_repository",
    "integrate_sdd_repository",
    "require_sdd_repository_health",
]

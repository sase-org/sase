"""Remote freshness policy and blocking bead-store integration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal


BeadRefreshMode = Literal["background", "blocking", "off"]


class _BeadStoreRefreshError(RuntimeError):
    """Raised when a blocking refresh cannot integrate the bead store."""


def bead_refresh_mode() -> BeadRefreshMode:
    """Return the configured remote-freshness policy for bead commands."""
    from sase.sdd._integration_marker import bead_refresh_mode as sdd_refresh_mode

    return sdd_refresh_mode()


def integration_is_fresh(repo_root: Path) -> bool:
    """Compatibility wrapper for the SDD-owned integration marker."""
    from sase.sdd._integration_marker import integration_is_fresh

    return integration_is_fresh(repo_root)


def mark_bead_integration(repo_root: Path) -> None:
    """Compatibility wrapper for the SDD-owned integration marker."""
    from sase.sdd._integration_marker import mark_bead_integration as mark_integration

    mark_integration(repo_root)


def refresh_bead_store(
    beads_dir: Path,
    *,
    lock_timeout: float | None,
    find_git_root: Callable[[Path], Path | None],
    has_push_remote: Callable[[Path], bool],
    is_in_tree_beads_dir: Callable[[Path], bool],
) -> None:
    """Synchronously integrate one remote-backed project bead store."""
    beads_dir = beads_dir.expanduser().resolve()
    if is_in_tree_beads_dir(beads_dir):
        return

    repo_root = find_git_root(beads_dir)
    if repo_root is None or not has_push_remote(repo_root):
        return

    from sase.sdd._git_contention import (
        handoff_store_git_write_lock,
        store_git_write_lock,
    )
    from sase.sdd._integration_marker import integration_marker_generation
    from sase.sdd._repository_recovery_markers import (
        clear_failed_integration_marker,
    )
    from sase.sdd._repository_transaction import integrate_sdd_repository

    observed_generation = integration_marker_generation(repo_root)
    with store_git_write_lock(
        repo_root,
        timeout=lock_timeout,
        op="bead.refresh",
        mutates_worktree=True,
    ) as acquired:
        current_generation = integration_marker_generation(repo_root)
        if current_generation is not None and current_generation != observed_generation:
            return
        if not acquired:
            raise _BeadStoreRefreshError(
                f"could not acquire the bead-store refresh lock for {repo_root}"
            )
        outcome = integrate_sdd_repository(
            repo_root,
            beads_dir=beads_dir,
            op_prefix="bead.refresh",
            lock_factory=handoff_store_git_write_lock,
        )
        if outcome.succeeded:
            # Any successful integration ends the clone's failed-integration
            # cooldown, not only the pull path that recorded it.
            clear_failed_integration_marker(
                repo_root,
                lock_factory=handoff_store_git_write_lock,
            )
    if outcome.succeeded:
        return

    detail = outcome.error or f"SDD integration ended with {outcome.status.value}"
    raise _BeadStoreRefreshError(detail)

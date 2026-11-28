"""Pre-mint bead-store refresh for plan-file epic launches."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

from sase.bead._sync_refresh import BeadStoreRefreshError
from sase.bead.cli_work_from_plan_helpers import error_with_resume
from sase.sdd._repository_types import SddIntegrationStatus

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder

PRE_MINT_REFRESH_LOCK_TIMEOUT_SECONDS = 30.0

_TRANSIENT_PRE_MINT_REFRESH_STATUSES = frozenset(
    {
        SddIntegrationStatus.REMOTE_UNAVAILABLE,
        SddIntegrationStatus.TIMED_OUT,
        SddIntegrationStatus.LOCK_UNAVAILABLE,
    }
)


def refresh_store_before_epic_mint(
    *,
    beads_dir: Path,
    archived_path: Path,
    no_push: bool,
    capacity: int | None,
    render: bool,
    parent: str | None,
    timer: LaunchTimingRecorder,
) -> str | None:
    """Integrate the bead store, then return this attempt's launch-base SHA.

    Pre-mint refresh takes ``store_git_write_lock`` on the beads repo. The
    launch path already holds ``epic_plan_launch_lock``, a distinct lock
    acquired first (see ``epic_plan_launch_lock``). Refresh therefore does
    not nest store write locks with itself and must not run while this
    process already holds the beads-repo store write lock.
    """
    from sase.bead.sync import bead_store_head_sha, refresh_bead_store

    with timer.stage("pre_mint_refresh"):
        try:
            refresh_bead_store(
                beads_dir,
                lock_timeout=PRE_MINT_REFRESH_LOCK_TIMEOUT_SECONDS,
            )
        except BeadStoreRefreshError as exc:
            if exc.status in _TRANSIENT_PRE_MINT_REFRESH_STATUSES:
                if render:
                    Console().print(
                        f"[yellow]![/yellow] Bead-store refresh failed "
                        f"({exc.status.value}): {exc}; continuing with the "
                        "local store"
                    )
            else:
                raise error_with_resume(
                    (
                        f"bead store {beads_dir} could not integrate before "
                        f"minting ({exc.status.value}): {exc}; nothing was "
                        "created"
                    ),
                    archived_path,
                    no_push=no_push,
                    parent_override=parent,
                    capacity=capacity,
                ) from exc
        launch_base = bead_store_head_sha(beads_dir)
        timer.fields["launch_base"] = launch_base
        return launch_base


__all__ = [
    "PRE_MINT_REFRESH_LOCK_TIMEOUT_SECONDS",
    "refresh_store_before_epic_mint",
]

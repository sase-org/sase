"""Eager stale-index-lock cleanup using the shared recovery policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import time
from typing import Any

from ._policy import (
    DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS,
    STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS,
    UnixClock,
    git_lock_policy,
    owner_observation,
    unix_ns,
)


def try_remove_stale_index_lock(
    workspace_dir: str | Path,
    *,
    min_age_seconds: float = STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS,
    unix_clock: UnixClock | None = None,
    owner_probe: Callable[..., dict[str, Any]] | None = None,
) -> bool:
    """Remove an aged owner-free index lock using the shared recovery policy."""
    policy = git_lock_policy()
    now = unix_clock or time.time
    context = policy.resolve_index_lock_context(workspace_dir)
    resolved = context.get("resolved_index_lock_path")
    if not isinstance(resolved, str) or not resolved:
        return False
    lock_path = Path(resolved)
    snapshot = policy.snapshot_lock_path(lock_path)
    owner = owner_observation(
        owner_probe or policy.probe_index_lock_owner,
        lock_path=lock_path,
        resolved_git_dir=(
            str(context["resolved_git_dir"])
            if context.get("resolved_git_dir")
            else None
        ),
        resolved_worktree=(
            str(context["resolved_worktree"])
            if context.get("resolved_worktree")
            else None
        ),
        remaining=DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS,
    )
    decision = policy.decide_eager_git_lock_cleanup(
        {
            "now_unix_ns": unix_ns(now),
            "min_age_ns": max(0, int(min_age_seconds * 1_000_000_000)),
            "snapshot": snapshot,
            "owner": owner,
        }
    )
    if str(decision.get("action")) != policy.GIT_LOCK_ACTION_REMOVE_THEN_RETRY:
        return False
    recheck = policy.snapshot_lock_path(lock_path)
    if recheck is None or snapshot is None or recheck != snapshot:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def remove_if_still_eligible(
    *,
    lock_path: Path | None,
    first_snapshot: dict[str, Any] | None,
    probe: Callable[..., dict[str, Any]],
    context: Mapping[str, Any],
    now_unix_ns: int,
    remaining_budget: Callable[[], float],
    deadline_ns: Callable[[], int | None],
    cancelled: Callable[[], bool],
    classification: dict[str, Any],
    path_match: dict[str, Any],
    retry_delays: tuple[float, ...],
    allow_lock_removal: bool,
    identity_disqualified: bool,
) -> tuple[bool, bool]:
    """Unlink *lock_path* when the recovery policy still authorizes removal."""
    policy = git_lock_policy()
    if cancelled() or lock_path is None:
        return False, False
    current = policy.snapshot_lock_path(lock_path)
    if current is None:
        return True, False
    owner = owner_observation(
        probe,
        lock_path=lock_path,
        resolved_git_dir=(
            str(context["resolved_git_dir"])
            if context.get("resolved_git_dir")
            else None
        ),
        resolved_worktree=(
            str(context["resolved_worktree"])
            if context.get("resolved_worktree")
            else None
        ),
        remaining=remaining_budget(),
    )
    decision = policy.decide_git_lock_recovery(
        {
            "schema_version": policy.GIT_LOCK_WIRE_SCHEMA_VERSION,
            "failure": classification,
            "delays": list(retry_delays),
            "allow_lock_removal": allow_lock_removal,
            "attempts": 10_000,
            "now_unix_ns": now_unix_ns,
            "remaining_command_deadline_ns": deadline_ns(),
            "remaining_recovery_budget_ns": max(
                0, int(remaining_budget() * 1_000_000_000)
            ),
            "cancelled": cancelled(),
            "removal_already_attempted": False,
            "identity_disqualified": identity_disqualified,
            "first_snapshot": first_snapshot,
            "current_snapshot": current,
            "path_match": path_match,
            "owner": owner,
        }
    )
    if str(decision.get("action")) == policy.GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL:
        return True, False
    if str(decision.get("action")) != policy.GIT_LOCK_ACTION_REMOVE_THEN_RETRY:
        return False, False
    recheck = policy.snapshot_lock_path(lock_path)
    if recheck is None:
        return True, False
    if recheck != current:
        return False, False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True, False
    except OSError:
        return False, False
    return True, True

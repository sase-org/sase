"""Bounded reset-and-replay recovery for leased machine-owned checkouts.

A replay callback runs inside a live :class:`~sase.workspace_provider.ownership.
OperationContext`. When it raises :class:`ReplayConflict` — a stale Git
operation, a rebase/merge conflict, or a non-fast-forward publication race
that cannot be semantically integrated — the checkout is reset to its
verified upstream tip and the callback runs again, bounded by a small
attempt count. Remote unavailability or lock contention should raise
:class:`ReplayDeferred` instead: those retry without a destructive reset.

Only a live ``LEASED_OPERATIONAL`` context may be reset. Primary ``#0``,
read-only canonical access, user-directed access, and opt-in primary-sidecar
sync are all refused before any Git command runs, because a hard reset would
violate their ownership guarantees.

Callbacks must be idempotent and checkpoint-aware: replay re-runs the whole
callback, so it must tolerate observing its own prior partial effects. Once
an operation has crossed an externally-visible barrier (for example, first
agent spawn during epic creation), it must stop raising ``ReplayConflict``
and use its own resume path instead — this helper has no notion of such
barriers.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.workspace_provider.ownership import (
    AccessKind,
    OperationContext,
    WorkspaceOwnershipError,
)
from sase.workspace_provider.utils import get_default_branch, non_interactive_git_env

DEFAULT_MAX_ATTEMPTS = 3


class ReplayConflict(RuntimeError):
    """A replay callback raises this to request a reset and retry."""


class ReplayDeferred(RuntimeError):
    """A replay callback raises this for remote/lock contention.

    Consumes one attempt but never triggers a destructive reset.
    """


class ResetReplayError(RuntimeError):
    """Reset-and-replay could not complete within its attempt budget."""

    def __init__(
        self,
        detail: str,
        *,
        attempts: int,
        last_error: Exception | None = None,
        recovery_ref: str | None = None,
    ) -> None:
        message = f"reset-and-replay exhausted {attempts} attempt(s): {detail}"
        if recovery_ref:
            message = f"{message}; abandoned HEAD preserved at {recovery_ref}"
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error
        self.recovery_ref = recovery_ref


@dataclass(frozen=True)
class ResetReplayResult:
    """Outcome of a successful :func:`reset_and_replay` call."""

    value: Any
    attempts: int
    reset_performed: bool
    recovery_ref: str | None = None


class _ResetFailure(RuntimeError):
    """Internal signal that the Git-level reset step itself failed."""


def reset_and_replay(
    context: OperationContext,
    repo_root: str | Path,
    operation: Callable[[], Any],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    clear_paths: Sequence[str | Path] = (),
    clock: Callable[[], float] | None = None,
) -> ResetReplayResult:
    """Run *operation*, resetting and replaying it on a signaled conflict.

    Verifies *repo_root* belongs to *context*'s live operational lease
    before anything destructive can happen. ``ReplayConflict`` triggers an
    abort of in-progress Git operations, a fetch, and a hard reset to the
    verified upstream tip before the next attempt. ``ReplayDeferred``
    retries without resetting. Any other exception propagates immediately.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    root = _require_leased_checkout(context, repo_root)

    attempts = 0
    reset_performed = False
    recovery_ref: str | None = None
    while True:
        attempts += 1
        try:
            value = operation()
        except (ReplayConflict, ReplayDeferred) as exc:
            is_conflict = isinstance(exc, ReplayConflict)
            if attempts >= max_attempts:
                raise ResetReplayError(
                    str(exc),
                    attempts=attempts,
                    last_error=exc,
                ) from exc
            if is_conflict:
                try:
                    ref = _reset_leased_checkout(root, clock=clock)
                except _ResetFailure as reset_exc:
                    raise ResetReplayError(
                        str(reset_exc),
                        attempts=attempts,
                        last_error=exc,
                    ) from reset_exc
                reset_performed = True
                recovery_ref = ref or recovery_ref
                if clear_paths:
                    _clear_owned_paths(context, clear_paths)
            continue
        return ResetReplayResult(
            value=value,
            attempts=attempts,
            reset_performed=reset_performed,
            recovery_ref=recovery_ref,
        )


def reset_leased_checkout_to_upstream(
    context: OperationContext,
    repo_root: str | Path,
    *,
    clock: Callable[[], float] | None = None,
) -> str | None:
    """Fetch and hard-reset *repo_root* to its verified upstream tip.

    Authorization is the same as :func:`reset_and_replay`. Returns the
    recovery ref that captured pre-reset HEAD, or ``None`` if HEAD could
    not be snapshotted.
    """

    root = _require_leased_checkout(context, repo_root)
    try:
        return _reset_leased_checkout(root, clock=clock)
    except _ResetFailure as exc:
        raise ResetReplayError(
            str(exc),
            attempts=0,
            last_error=exc,
        ) from exc


def _require_leased_checkout(
    context: OperationContext,
    repo_root: str | Path,
) -> Path:
    if context.access_kind is not AccessKind.LEASED_OPERATIONAL:
        raise WorkspaceOwnershipError(
            "reset-and-replay requires a leased operational context, not "
            f"{context.access_kind.value}"
        )
    if context.is_primary:
        raise WorkspaceOwnershipError("reset-and-replay refuses primary workspace #0")
    if context.claim_pid is None:
        raise WorkspaceOwnershipError(
            "reset-and-replay refuses a checkout with no live workspace claim"
        )
    checkout = context.checkout_dir.expanduser().resolve(strict=False)
    root = Path(repo_root).expanduser().resolve(strict=False)
    if not root.is_relative_to(checkout):
        raise WorkspaceOwnershipError(
            f"reset-and-replay refuses {root}: outside leased checkout {checkout}"
        )
    return root


def _clear_owned_paths(
    context: OperationContext,
    paths: Sequence[str | Path],
) -> None:
    checkout = context.checkout_dir.expanduser().resolve(strict=False)
    for raw in paths:
        resolved = Path(raw).expanduser().resolve(strict=False)
        if not resolved.is_relative_to(checkout):
            raise WorkspaceOwnershipError(
                f"reset-and-replay refuses to clear {resolved}: "
                f"outside leased checkout {checkout}"
            )
        shutil.rmtree(resolved, ignore_errors=True)


def _reset_leased_checkout(
    repo_root: Path,
    *,
    clock: Callable[[], float] | None = None,
) -> str | None:
    """Abort in-progress ops, fetch, hard reset to upstream. Returns a diagnostic ref."""

    _abort_in_progress_operations(repo_root)
    fetch = _run_git(["fetch", "--quiet", "origin"], repo_root)
    if fetch.returncode != 0:
        raise _ResetFailure(f"git fetch failed: {_git_error(fetch)}")
    upstream = _resolve_upstream(repo_root)
    upstream_sha_result = _run_git(
        ["rev-parse", "--verify", upstream],
        repo_root,
    )
    if upstream_sha_result.returncode != 0 or not upstream_sha_result.stdout.strip():
        raise _ResetFailure(
            f"could not resolve upstream {upstream!r}: "
            f"{_git_error(upstream_sha_result)}"
        )
    upstream_sha = upstream_sha_result.stdout.strip()
    recovery_ref = _snapshot_pre_reset_head(repo_root, clock=clock)
    reset = _run_git(["reset", "--hard", upstream_sha], repo_root)
    if reset.returncode != 0:
        raise _ResetFailure(f"git reset --hard failed: {_git_error(reset)}")
    return recovery_ref


def _abort_in_progress_operations(repo_root: Path) -> None:
    git_dir_result = _run_git(["rev-parse", "--git-dir"], repo_root)
    if git_dir_result.returncode != 0:
        raise _ResetFailure(
            f"could not resolve the Git directory: {_git_error(git_dir_result)}"
        )
    git_dir = Path(git_dir_result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        aborted = _run_git(["rebase", "--abort"], repo_root)
        if aborted.returncode != 0:
            raise _ResetFailure(
                f"could not abort the stale rebase: {_git_error(aborted)}"
            )
    if (git_dir / "MERGE_HEAD").exists():
        aborted = _run_git(["merge", "--abort"], repo_root)
        if aborted.returncode != 0:
            raise _ResetFailure(
                f"could not abort the stale merge: {_git_error(aborted)}"
            )
    if (git_dir / "CHERRY_PICK_HEAD").exists():
        aborted = _run_git(["cherry-pick", "--abort"], repo_root)
        if aborted.returncode != 0:
            raise _ResetFailure(
                f"could not abort the stale cherry-pick: {_git_error(aborted)}"
            )


def _resolve_upstream(repo_root: Path) -> str:
    tracking = _run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        repo_root,
    )
    if tracking.returncode == 0 and tracking.stdout.strip():
        return tracking.stdout.strip()
    return get_default_branch(str(repo_root))


def _snapshot_pre_reset_head(
    repo_root: Path,
    *,
    clock: Callable[[], float] | None = None,
) -> str | None:
    head = _run_git(["rev-parse", "HEAD"], repo_root)
    if head.returncode != 0 or not head.stdout.strip():
        return None
    sha = head.stdout.strip()
    now = clock() if clock is not None else time.time()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    ref = f"refs/sase/reset_replay/{stamp}-{sha[:10]}"
    updated = _run_git(["update-ref", ref, sha], repo_root)
    if updated.returncode != 0:
        return None
    return ref


def _run_git(args: list[str], repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=non_interactive_git_env(),
        stdin=subprocess.DEVNULL,
    )


def _git_error(result: subprocess.CompletedProcess[str]) -> str:
    return result.stderr.strip() or result.stdout.strip() or "git command failed"


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "ReplayConflict",
    "ReplayDeferred",
    "ResetReplayError",
    "ResetReplayResult",
    "reset_and_replay",
    "reset_leased_checkout_to_upstream",
]

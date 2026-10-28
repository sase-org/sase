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

from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider.ownership import (
    AccessKind,
    OperationContext,
    WorkspaceOwnershipError,
)
from sase.workspace_provider.snapshot import (
    NestedPreservationError,
    PreservationError,
    preserve_nested_repositories,
    snapshot_git_repo,
)
from sase.workspace_provider.utils import (
    abort_in_progress_git_operations,
    get_default_branch,
    non_interactive_git_env,
)

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
        recovery_locations: Sequence[str] = (),
    ) -> None:
        message = f"reset-and-replay exhausted {attempts} attempt(s): {detail}"
        if recovery_ref:
            message = f"{message}; abandoned HEAD preserved at {recovery_ref}"
        locations = _unique_locations(recovery_locations)
        if locations:
            message = f"{message}; recoverable work preserved at {', '.join(locations)}"
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error
        self.recovery_ref = recovery_ref
        self.recovery_locations = locations


@dataclass(frozen=True)
class ResetRecoveryOutcome:
    """Recovery evidence produced by one direct checkout reset."""

    recovery_ref: str | None = None
    recovery_locations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResetReplayResult:
    """Outcome of a successful :func:`reset_and_replay` call."""

    value: Any
    attempts: int
    reset_performed: bool
    recovery_ref: str | None = None
    recovery_locations: tuple[str, ...] = ()


class _ResetFailure(RuntimeError):
    """Internal signal that the Git-level reset step itself failed."""

    def __init__(
        self,
        detail: str,
        *,
        recovery_ref: str | None = None,
        recovery_locations: Sequence[str] = (),
    ) -> None:
        super().__init__(detail)
        self.recovery_ref = recovery_ref
        self.recovery_locations = _unique_locations(recovery_locations)


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
    recovery_locations: tuple[str, ...] = ()
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
                    recovery_ref=recovery_ref,
                    recovery_locations=recovery_locations,
                ) from exc
            if is_conflict:
                clear_targets = _validate_owned_paths(context, clear_paths)
                try:
                    outcome = _reset_leased_checkout(
                        root,
                        clock=clock,
                        workspace_dir=context.checkout_dir,
                        workspace_num=context.workspace_num,
                        clear_paths=clear_targets,
                    )
                except _ResetFailure as reset_exc:
                    raise ResetReplayError(
                        str(reset_exc),
                        attempts=attempts,
                        last_error=exc,
                        recovery_ref=reset_exc.recovery_ref or recovery_ref,
                        recovery_locations=_merge_locations(
                            recovery_locations, reset_exc.recovery_locations
                        ),
                    ) from reset_exc
                reset_performed = True
                recovery_ref = outcome.recovery_ref or recovery_ref
                recovery_locations = _merge_locations(
                    recovery_locations, outcome.recovery_locations
                )
                if clear_targets:
                    _clear_owned_paths(
                        context,
                        clear_targets,
                        protected_locations=recovery_locations,
                    )
            continue
        return ResetReplayResult(
            value=value,
            attempts=attempts,
            reset_performed=reset_performed,
            recovery_ref=recovery_ref,
            recovery_locations=recovery_locations,
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

    return reset_leased_checkout_to_upstream_with_recovery(
        context, repo_root, clock=clock
    ).recovery_ref


def reset_leased_checkout_to_upstream_with_recovery(
    context: OperationContext,
    repo_root: str | Path,
    *,
    clock: Callable[[], float] | None = None,
) -> ResetRecoveryOutcome:
    """Reset a leased checkout and return both the legacy ref and snapshot locators."""

    root = _require_leased_checkout(context, repo_root)
    try:
        return _reset_leased_checkout(
            root,
            clock=clock,
            workspace_dir=context.checkout_dir,
            workspace_num=context.workspace_num,
        )
    except _ResetFailure as exc:
        raise ResetReplayError(
            str(exc),
            attempts=0,
            last_error=exc,
            recovery_ref=exc.recovery_ref,
            recovery_locations=exc.recovery_locations,
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
    *,
    protected_locations: Sequence[str] = (),
) -> None:
    resolved_paths = _validate_owned_paths(context, paths)
    for location in protected_locations:
        rescue_dir = Path(location).expanduser().resolve(strict=False).parent
        for resolved in resolved_paths:
            if rescue_dir == resolved or rescue_dir.is_relative_to(resolved):
                raise WorkspaceOwnershipError(
                    "reset-and-replay refuses to clear a verified recovery snapshot: "
                    f"{location}"
                )
    for resolved in resolved_paths:
        shutil.rmtree(resolved, ignore_errors=True)


def _validate_owned_paths(
    context: OperationContext,
    paths: Sequence[str | Path],
) -> tuple[Path, ...]:
    checkout = context.checkout_dir.expanduser().resolve(strict=False)
    resolved_paths: list[Path] = []
    for raw in paths:
        resolved = Path(raw).expanduser().resolve(strict=False)
        if not resolved.is_relative_to(checkout) or resolved == checkout:
            raise WorkspaceOwnershipError(
                f"reset-and-replay refuses to clear {resolved}: "
                f"outside leased checkout {checkout} or equal to the checkout root"
            )
        resolved_paths.append(resolved)
    return tuple(resolved_paths)


def _validate_snapshot_clear_boundaries(
    clear_paths: Sequence[str | Path],
    recovery_locations: Sequence[str],
) -> None:
    for location in recovery_locations:
        rescue_dir = Path(location).expanduser().resolve(strict=False).parent
        for raw in clear_paths:
            clear_path = Path(raw).expanduser().resolve(strict=False)
            if rescue_dir == clear_path or rescue_dir.is_relative_to(clear_path):
                raise WorkspaceOwnershipError(
                    "reset-and-replay refuses a clear path containing a verified "
                    f"recovery snapshot: {location}"
                )


def _unique_locations(locations: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(location for location in locations if location))


def _merge_locations(*groups: Sequence[str]) -> tuple[str, ...]:
    return _unique_locations(tuple(location for group in groups for location in group))


def _reset_leased_checkout(
    repo_root: Path,
    *,
    clock: Callable[[], float] | None = None,
    workspace_dir: str | Path,
    workspace_num: int,
    clear_paths: Sequence[str | Path] = (),
) -> ResetRecoveryOutcome:
    """Snapshot, abort, fetch, and reset. Return all recovery locators."""

    recovery_ref: str | None = None
    recovery_locations: tuple[str, ...] = ()
    try:
        try:
            snapshot = snapshot_git_repo(
                repo_root,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                label=repo_root.name or "checkout",
                reason="before reset-and-replay abort/reset",
            )
        except PreservationError as exc:
            raise _ResetFailure(
                f"could not preserve checkout before reset: {exc}"
            ) from exc
        if snapshot is not None:
            recovery_locations = (str(snapshot.manifest_path.resolve()),)
            _validate_snapshot_clear_boundaries(clear_paths, recovery_locations)
        if clear_paths:
            try:
                nested = preserve_nested_repositories(
                    repo_root,
                    workspace_dir=workspace_dir,
                    workspace_num=workspace_num,
                    reason="before reset-and-replay clear of nested repositories",
                    within=clear_paths,
                    already_proven=(repo_root,),
                )
            except NestedPreservationError as exc:
                raise _ResetFailure(
                    f"could not preserve nested repositories before reset: {exc}",
                    recovery_ref=recovery_ref,
                    recovery_locations=_merge_locations(
                        recovery_locations, exc.locations
                    ),
                ) from exc
            except PreservationError as exc:
                raise _ResetFailure(
                    f"could not preserve nested repositories before reset: {exc}",
                    recovery_ref=recovery_ref,
                    recovery_locations=recovery_locations,
                ) from exc
            recovery_locations = _merge_locations(recovery_locations, nested.locations)
            _validate_snapshot_clear_boundaries(clear_paths, recovery_locations)
        recovery_ref = _snapshot_pre_reset_head(repo_root, clock=clock)

        # Pin HEAD only after the strict snapshot proves the tree clean or saves
        # its dirty bytes. The ref remains useful if abort or fetch fails.
        _abort_in_progress_operations(repo_root)
        fetch = _run_git(["fetch", "--quiet", "origin"], repo_root)
        if fetch.returncode != 0:
            raise _ResetFailure(f"git fetch failed: {_git_error(fetch)}")
        upstream = _resolve_upstream(repo_root)
        upstream_sha_result = _run_git(
            ["rev-parse", "--verify", upstream],
            repo_root,
        )
        if (
            upstream_sha_result.returncode != 0
            or not upstream_sha_result.stdout.strip()
        ):
            raise _ResetFailure(
                f"could not resolve upstream {upstream!r}: "
                f"{_git_error(upstream_sha_result)}"
            )
        upstream_sha = upstream_sha_result.stdout.strip()
        reset = _run_git_mutation(["reset", "--hard", upstream_sha], repo_root)
        if reset.returncode != 0:
            raise _ResetFailure(f"git reset --hard failed: {_git_error(reset)}")
        return ResetRecoveryOutcome(
            recovery_ref=recovery_ref,
            recovery_locations=recovery_locations,
        )
    except _ResetFailure as exc:
        raise _ResetFailure(
            str(exc),
            recovery_ref=exc.recovery_ref or recovery_ref,
            recovery_locations=_merge_locations(
                recovery_locations, exc.recovery_locations
            ),
        ) from exc


def _abort_in_progress_operations(repo_root: Path) -> None:
    git_dir_result = _run_git(["rev-parse", "--git-dir"], repo_root)
    if git_dir_result.returncode != 0 or not git_dir_result.stdout.strip():
        raise _ResetFailure(
            f"could not resolve the Git directory: {_git_error(git_dir_result)}"
        )
    git_dir = Path(git_dir_result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir

    def _run(argv: list[str]) -> tuple[int, str]:
        result = _run_git_mutation(argv[1:], repo_root)
        return result.returncode, _git_error(result)

    error = abort_in_progress_git_operations(repo_root, git_dir, _run)
    if error is not None:
        raise _ResetFailure(f"could not abort in-progress git operations: {error}")


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


def _run_git_mutation(
    args: list[str],
    repo_root: Path,
) -> subprocess.CompletedProcess[str]:
    result, _outcome = run_with_git_lock_retry(
        lambda: _run_git(args, repo_root),
        cwd=repo_root,
        argv=["git", *args],
        env=non_interactive_git_env(),
        allow_age_wait=False,
    )
    return result


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
    "ResetRecoveryOutcome",
    "ResetReplayResult",
    "reset_and_replay",
    "reset_leased_checkout_to_upstream",
    "reset_leased_checkout_to_upstream_with_recovery",
]

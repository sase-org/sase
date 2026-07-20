"""Repository health and transactional integration for SDD stores."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re
import subprocess
from typing import Any

from sase.sdd._git import (
    SddGitCommandTimeout,
    network_git_timeout,
)


class SddRepositoryHealthError(RuntimeError):
    """Raised when an SDD Git repository is structurally unsafe to write."""


class SddIntegrationStatus(StrEnum):
    """Typed terminal state for one fetch/rebase transaction."""

    SUCCESS = "success"
    REMOTE_UNAVAILABLE = "remote_unavailable_but_healthy"
    REPAIRED_BEAD_CONFLICTS = "repaired_bead_conflicts"
    ABORTED_UNSUPPORTED_CONFLICTS = "aborted_unsupported_conflicts"
    LOCAL_CHANGES = "local_changes_preserved"
    RECOVERED = "machine_managed_recovered"
    RECOVERY_COOLDOWN = "machine_managed_recovery_cooldown"
    RECOVERY_FAILED = "machine_managed_recovery_failed"
    UNRECOVERABLE = "unrecoverable_repository_state"


@dataclass(frozen=True)
class SddRepositoryState:
    """The local state needed to prove an integration rollback."""

    repo_root: Path
    git_dir: Path
    branch: str | None
    head: str | None
    operation_markers: tuple[str, ...]
    unmerged_paths: tuple[str, ...]
    status_porcelain: str
    valid_worktree: bool

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.valid_worktree:
            blockers.append("not a valid Git worktree")
        if self.branch is None:
            blockers.append("detached HEAD")
        if self.operation_markers:
            blockers.append(
                "in-progress Git operation " + ", ".join(self.operation_markers)
            )
        if self.unmerged_paths:
            blockers.append("unmerged index entries " + ", ".join(self.unmerged_paths))
        return tuple(blockers)


@dataclass(frozen=True)
class SddIntegrationOutcome:
    """Result of integrating an SDD checkout with its configured upstream."""

    status: SddIntegrationStatus
    integrated: bool = False
    upstream_present: bool = False
    restored: bool = False
    error: str | None = None
    resolved_files: tuple[str, ...] = ()
    recovery_ref: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in {
            SddIntegrationStatus.SUCCESS,
            SddIntegrationStatus.REPAIRED_BEAD_CONFLICTS,
            SddIntegrationStatus.RECOVERED,
        }

    @property
    def structurally_healthy(self) -> bool:
        return self.status is not SddIntegrationStatus.UNRECOVERABLE


GitRunner = Callable[..., subprocess.CompletedProcess[str]]
LockFactory = Callable[[Path], AbstractContextManager[bool]]
EventLogger = Callable[..., None]


_OPERATION_PATHS: tuple[tuple[str, str], ...] = (
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
    ("BISECT_LOG", "bisect"),
    ("BISECT_START", "bisect"),
    ("sequencer", "sequencer"),
)
_CREDENTIALS_IN_URL = re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE)


def require_sdd_repository_health(
    repo_root: Path,
    *,
    expected_branch: str | None = None,
) -> SddRepositoryState:
    """Fail closed unless *repo_root* is attached and free of Git operations."""
    root = repo_root.expanduser().resolve()
    state = inspect_sdd_repository(root, default_git_runner)
    blockers = list(state.blockers)
    if expected_branch is not None and state.branch != expected_branch:
        blockers.append(
            f"expected branch {expected_branch!r}, found {state.branch or 'detached HEAD'!r}"
        )
    if blockers:
        raise SddRepositoryHealthError(_health_error(root, blockers))
    return state


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
    if outcome.succeeded or outcome.status is SddIntegrationStatus.REMOTE_UNAVAILABLE:
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
        from sase.sdd._integration_marker import mark_bead_integration

        try:
            mark_bead_integration(repo_root.expanduser().resolve())
        except OSError:
            pass
    return recovered


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
    """Implement one transactional fetch/rebase attempt.

    Network fetch deliberately happens before the cooperative store write lock.
    The lock then covers health inspection, ancestry checks, rebase, semantic
    bead repair, continuation, and rollback verification.
    """
    root = repo_root.expanduser().resolve()
    runner = git_runner or default_git_runner
    if lock_factory is None:
        from sase.sdd._git_contention import store_git_write_lock

        lock_factory = store_git_write_lock

    # A read-only preflight prevents a known-poisoned checkout from having even
    # its remote-tracking refs changed by fetch. State is checked again under
    # the write lock because another actor may start an operation afterward.
    try:
        preflight = inspect_sdd_repository(root, runner)
    except Exception as exc:  # noqa: BLE001 - returned as a typed outcome
        return SddIntegrationOutcome(
            SddIntegrationStatus.UNRECOVERABLE,
            error=f"could not inspect SDD repository {root}: {safe_git_error_text(exc)}",
        )
    preflight_blockers = sdd_state_blockers(preflight, expected_branch)
    if preflight_blockers:
        return SddIntegrationOutcome(
            SddIntegrationStatus.UNRECOVERABLE,
            error=_health_error(root, preflight_blockers),
        )

    fetch_failure: str | None = None
    if fetch:
        fetched = runner(
            root,
            ["fetch", "--prune", "origin"],
            op=f"{op_prefix}.fetch",
            network=True,
        )
        if fetched.returncode != 0:
            fetch_failure = format_git_error("git fetch failed", fetched)

    with lock_factory(root) as acquired:
        if not acquired:
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=(
                    f"SDD repository {root} could not acquire its store write "
                    "lock; retry after the active writer finishes"
                ),
            )
        try:
            starting = inspect_sdd_repository(root, runner)
        except Exception as exc:  # noqa: BLE001 - returned as a typed outcome
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=f"could not inspect SDD repository {root}: {safe_git_error_text(exc)}",
            )

        blockers = sdd_state_blockers(starting, expected_branch)
        if blockers:
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=_health_error(root, blockers),
            )

        if fetch_failure is not None:
            return SddIntegrationOutcome(
                SddIntegrationStatus.REMOTE_UNAVAILABLE,
                error=fetch_failure,
            )

        upstream_result = runner(
            root,
            ["rev-parse", "--verify", upstream],
            op=f"{op_prefix}.upstream",
        )
        if upstream_result.returncode != 0:
            return SddIntegrationOutcome(SddIntegrationStatus.SUCCESS)

        clean_error = _tracked_changes_error(root, runner, op_prefix)
        if clean_error is not None:
            return SddIntegrationOutcome(
                SddIntegrationStatus.LOCAL_CHANGES,
                upstream_present=True,
                error=clean_error,
            )

        ancestor = runner(
            root,
            ["merge-base", "--is-ancestor", upstream, "HEAD"],
            op=f"{op_prefix}.ancestor",
        )
        if ancestor.returncode == 0:
            return SddIntegrationOutcome(
                SddIntegrationStatus.SUCCESS,
                upstream_present=True,
            )
        if ancestor.returncode != 1:
            return SddIntegrationOutcome(
                SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS,
                upstream_present=True,
                restored=True,
                error=format_git_error("could not compare SDD histories", ancestor),
            )

        rebased = runner(
            root,
            ["rebase", upstream],
            op=f"{op_prefix}.rebase",
        )
        if rebased.returncode == 0:
            return _successful_rebase(
                root,
                starting,
                runner,
                upstream_present=True,
                repaired=False,
                resolved_files=(),
                op_prefix=op_prefix,
            )

        return _repair_or_abort_rebase(
            root,
            beads_dir=beads_dir,
            starting=starting,
            primary_failure=format_git_error("git rebase failed", rebased),
            runner=runner,
            op_prefix=op_prefix,
            event_logger=event_logger,
        )


def _repair_or_abort_rebase(
    repo_root: Path,
    *,
    beads_dir: Path | None,
    starting: SddRepositoryState,
    primary_failure: str,
    runner: GitRunner,
    op_prefix: str,
    event_logger: EventLogger | None,
) -> SddIntegrationOutcome:
    from sase.bead.conflict_resolver import resolve_bead_conflicts

    resolved: list[str] = []
    for _ in range(100):
        conflicts = _unmerged_paths(repo_root, runner, op_prefix)
        if not conflicts:
            return _abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=primary_failure,
                runner=runner,
                op_prefix=op_prefix,
            )
        try:
            resolution = resolve_bead_conflicts(repo_root, beads_dir=beads_dir)
        except Exception as exc:  # noqa: BLE001 - rollback owns the error
            message = (
                f"semantic bead conflict resolution failed: {safe_git_error_text(exc)}"
            )
            _emit_resolution(event_logger, False, message, ())
            return _abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=f"{primary_failure}; {message}",
                runner=runner,
                op_prefix=op_prefix,
            )
        _emit_resolution(
            event_logger,
            resolution.ok,
            resolution.message,
            resolution.resolved_files,
        )
        if not resolution.ok:
            return _abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=f"{primary_failure}; {resolution.message}",
                runner=runner,
                op_prefix=op_prefix,
            )
        resolved.extend(resolution.resolved_files)

        continued = runner(
            repo_root,
            ["-c", "core.editor=true", "rebase", "--continue"],
            op=f"{op_prefix}.rebase_continue",
        )
        if continued.returncode == 0:
            return _successful_rebase(
                repo_root,
                starting,
                runner,
                upstream_present=True,
                repaired=True,
                resolved_files=tuple(sorted(dict.fromkeys(resolved))),
                op_prefix=op_prefix,
            )
        primary_failure = format_git_error("git rebase --continue failed", continued)

    return _abort_and_verify(
        repo_root,
        starting=starting,
        primary_failure="too many rebase conflict rounds",
        runner=runner,
        op_prefix=op_prefix,
    )


def _successful_rebase(
    repo_root: Path,
    starting: SddRepositoryState,
    runner: GitRunner,
    *,
    upstream_present: bool,
    repaired: bool,
    resolved_files: tuple[str, ...],
    op_prefix: str,
) -> SddIntegrationOutcome:
    try:
        final = inspect_sdd_repository(repo_root, runner)
    except Exception as exc:  # noqa: BLE001 - attempt rollback below
        return _abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=f"could not verify completed rebase: {safe_git_error_text(exc)}",
            runner=runner,
            op_prefix=op_prefix,
        )
    if final.blockers or final.branch != starting.branch:
        detail = ", ".join(final.blockers) or (
            f"branch changed from {starting.branch!r} to {final.branch!r}"
        )
        return _abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=f"rebase left an unsafe repository: {detail}",
            runner=runner,
            op_prefix=op_prefix,
        )
    if final.status_porcelain != starting.status_porcelain:
        return _abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure="rebase changed the pre-existing worktree or index state",
            runner=runner,
            op_prefix=op_prefix,
        )
    return SddIntegrationOutcome(
        (
            SddIntegrationStatus.REPAIRED_BEAD_CONFLICTS
            if repaired
            else SddIntegrationStatus.SUCCESS
        ),
        integrated=True,
        upstream_present=upstream_present,
        resolved_files=resolved_files,
    )


def _abort_and_verify(
    repo_root: Path,
    *,
    starting: SddRepositoryState,
    primary_failure: str,
    runner: GitRunner,
    op_prefix: str,
) -> SddIntegrationOutcome:
    abort_failure: str | None = None
    try:
        current = inspect_sdd_repository(repo_root, runner)
        rebase_active = any(marker == "rebase" for marker in current.operation_markers)
    except Exception:
        rebase_active = True
    if rebase_active:
        aborted = runner(
            repo_root,
            ["rebase", "--abort"],
            op=f"{op_prefix}.rebase_abort",
        )
        if aborted.returncode != 0:
            abort_failure = format_git_error("git rebase --abort failed", aborted)

    verify_failure: str | None
    try:
        final = inspect_sdd_repository(repo_root, runner)
    except Exception as exc:  # noqa: BLE001 - restoration cannot be proven
        verify_failure = f"could not inspect rollback state: {safe_git_error_text(exc)}"
    else:
        verify_failure = sdd_rollback_mismatch(starting, final)

    error_parts = [primary_failure]
    if abort_failure is not None:
        error_parts.append(abort_failure)
    if verify_failure is not None:
        error_parts.append(f"rollback verification failed: {verify_failure}")
    error = "; ".join(error_parts)
    if verify_failure is not None:
        return SddIntegrationOutcome(
            SddIntegrationStatus.UNRECOVERABLE,
            upstream_present=True,
            error=error,
        )
    return SddIntegrationOutcome(
        SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS,
        upstream_present=True,
        restored=True,
        error=error,
    )


def sdd_rollback_mismatch(
    starting: SddRepositoryState,
    final: SddRepositoryState,
) -> str | None:
    mismatches: list[str] = []
    if final.blockers:
        mismatches.extend(final.blockers)
    if final.branch != starting.branch:
        mismatches.append(f"branch is {final.branch!r}, expected {starting.branch!r}")
    if final.head != starting.head:
        mismatches.append(f"HEAD is {final.head!r}, expected {starting.head!r}")
    if final.operation_markers != starting.operation_markers:
        mismatches.append("Git operation markers differ from the starting state")
    if final.unmerged_paths != starting.unmerged_paths:
        mismatches.append("unmerged index entries differ from the starting state")
    if final.status_porcelain != starting.status_porcelain:
        mismatches.append("worktree or index differs from the starting state")
    return ", ".join(dict.fromkeys(mismatches)) or None


def inspect_sdd_repository(repo_root: Path, runner: GitRunner) -> SddRepositoryState:
    worktree = runner(
        repo_root,
        ["rev-parse", "--is-inside-work-tree"],
        op="sdd.health.worktree",
    )
    valid_worktree = worktree.returncode == 0 and worktree.stdout.strip() == "true"

    git_dir_result = runner(
        repo_root,
        ["rev-parse", "--git-dir"],
        op="sdd.health.git_dir",
    )
    raw_git_dir = (
        git_dir_result.stdout.strip() if git_dir_result.returncode == 0 else ".git"
    )
    git_dir = Path(raw_git_dir or ".git")
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir

    branch_result = runner(
        repo_root,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        op="sdd.health.branch",
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    branch = branch or None

    head_result = runner(
        repo_root,
        ["rev-parse", "--verify", "HEAD"],
        op="sdd.health.head",
    )
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    head = head or None

    markers = tuple(
        dict.fromkeys(
            label
            for relative, label in _OPERATION_PATHS
            if (git_dir / relative).exists()
        )
    )
    unmerged = _unmerged_paths(repo_root, runner, "sdd.health")
    status_result = runner(
        repo_root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        op="sdd.health.status",
    )
    if status_result.returncode != 0:
        valid_worktree = False
    return SddRepositoryState(
        repo_root=repo_root,
        git_dir=git_dir,
        branch=branch,
        head=head,
        operation_markers=markers,
        unmerged_paths=unmerged,
        status_porcelain=status_result.stdout if status_result.returncode == 0 else "",
        valid_worktree=valid_worktree,
    )


def _unmerged_paths(
    repo_root: Path,
    runner: GitRunner,
    op_prefix: str,
) -> tuple[str, ...]:
    result = runner(
        repo_root,
        ["diff", "--name-only", "--diff-filter=U", "-z"],
        op=f"{op_prefix}.conflicts",
    )
    if result.returncode != 0:
        return ()
    return tuple(sorted(path for path in result.stdout.split("\0") if path))


def _tracked_changes_error(
    repo_root: Path,
    runner: GitRunner,
    op_prefix: str,
) -> str | None:
    for args, label in (
        (["diff", "--quiet"], "tracked worktree changes"),
        (["diff", "--cached", "--quiet"], "staged changes"),
    ):
        result = runner(repo_root, args, op=f"{op_prefix}.clean")
        if result.returncode == 1:
            return (
                f"SDD repository {repo_root} needs integration but has {label}; "
                "commit or restore those changes and retry"
            )
        if result.returncode != 0:
            return format_git_error("could not inspect local SDD changes", result)
    return None


def default_git_runner(
    repo_root: Path,
    args: list[str],
    *,
    op: str,
    network: bool = False,
) -> subprocess.CompletedProcess[str]:
    from sase.sdd._git_contention import run_sdd_git_write

    try:
        return run_sdd_git_write(
            args,
            cwd=repo_root,
            op=op,
            timeout=network_git_timeout() if network else None,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, SddGitCommandTimeout) as exc:
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=124,
            stdout="",
            stderr=str(exc),
        )


def _health_error(repo_root: Path, blockers: list[str]) -> str:
    detail = "; ".join(dict.fromkeys(blockers))
    return (
        f"SDD repository {repo_root} is not safe to write: {detail}. "
        "Finish or abort the existing Git operation in that repository, verify "
        "an attached branch and clean index, then retry; SASE did not modify it"
    )


def sdd_state_blockers(
    state: SddRepositoryState,
    expected_branch: str | None,
) -> list[str]:
    blockers = list(state.blockers)
    if expected_branch is not None and state.branch != expected_branch:
        blockers.append(
            f"expected branch {expected_branch!r}, found "
            f"{state.branch or 'detached HEAD'!r}"
        )
    return blockers


def format_git_error(
    message: str,
    result: subprocess.CompletedProcess[str],
) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        return f"{message}: {_redact_credentials(detail)}"
    return f"{message} with exit code {result.returncode}"


def safe_git_error_text(exc: BaseException) -> str:
    return _redact_credentials(str(exc) or type(exc).__name__)


def _redact_credentials(value: str) -> str:
    return _CREDENTIALS_IN_URL.sub(r"\1<redacted>@", value)


def _emit_resolution(
    logger: EventLogger | None,
    ok: bool,
    message: str,
    resolved_files: tuple[str, ...],
) -> None:
    if logger is not None:
        logger(
            "conflict_resolution",
            ok=ok,
            message=message,
            resolved_files=list(resolved_files),
        )


__all__ = [
    "SddIntegrationOutcome",
    "SddIntegrationStatus",
    "SddRepositoryHealthError",
    "integrate_machine_managed_sdd_repository",
    "integrate_sdd_repository",
    "require_sdd_repository_health",
]

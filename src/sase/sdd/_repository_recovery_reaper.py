"""Bounded cleanup for retained machine-managed SDD recovery snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
import time

from sase.sdd._repository_health import default_git_runner, format_git_error
from sase.sdd._repository_types import GitRunner, LockFactory


_DAY_SECONDS = 24 * 60 * 60.0
DEFAULT_RECOVERY_SNAPSHOT_RETENTION_SECONDS = 30 * _DAY_SECONDS
DEFAULT_RECOVERY_REAP_MAX_REMOVALS = 50
RECOVERY_REF_PREFIX = "refs/sase/recovery/"
RECOVERY_STASH_SUBJECT_FRAGMENT = f"sase recovery {RECOVERY_REF_PREFIX}"
_RECOVERY_REF_STAMP = re.compile(r"^refs/sase/recovery/(?P<stamp>\d{8}T\d{6}Z)(?:-|$)")
_STASH_INDEX = re.compile(r"^stash@\{(?P<index>\d+)\}$")


@dataclass(frozen=True)
class _SddRecoveryReapResult:
    """Summary of one recovery-snapshot cleanup pass."""

    scanned_refs: int
    scanned_stashes: int
    removed_refs: tuple[str, ...] = ()
    removed_stashes: tuple[str, ...] = ()
    retained_fresh: tuple[str, ...] = ()
    retained_unreachable: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    capped: bool = False
    lock_acquired: bool = True

    @property
    def removed(self) -> int:
        return len(self.removed_refs) + len(self.removed_stashes)


@dataclass(frozen=True)
class _RecoveryCandidate:
    kind: str
    identifier: str
    target: str
    created_at: float
    is_stash_snapshot: bool


@dataclass(frozen=True)
class _CommitShape:
    parents: tuple[str, ...]
    subject: str


def _reap_sdd_recovery_snapshots(
    repo_root: Path,
    *,
    now: float | None = None,
    retention_seconds: float = DEFAULT_RECOVERY_SNAPSHOT_RETENTION_SECONDS,
    max_removals: int = DEFAULT_RECOVERY_REAP_MAX_REMOVALS,
    git_runner: GitRunner | None = None,
    lock_factory: LockFactory | None = None,
    op_prefix: str = "sdd.recovery_reap",
) -> _SddRecoveryReapResult:
    """Remove stale recovery refs and recovery stashes when remote-safe.

    Recovery snapshots may be the only remaining handle to local bead commits
    after a managed reset. A stale snapshot is removed only when the branch
    history it protects is already reachable from a remote-tracking ref. Dirty
    worktree stash snapshots may age out once their first parent is remote
    reachable; the stash/index commits themselves are recovery payloads.
    """

    root = repo_root.expanduser().resolve()
    runner = git_runner or default_git_runner
    if lock_factory is None:
        from sase.sdd._git_contention import store_git_write_lock_factory

        lock_factory = store_git_write_lock_factory(op=f"{op_prefix}.lock")
    clock = time.time() if now is None else now
    cutoff = clock - max(0.0, retention_seconds)
    removal_budget = max(0, max_removals)

    with lock_factory(root) as acquired:
        if not acquired:
            return _SddRecoveryReapResult(
                scanned_refs=0,
                scanned_stashes=0,
                errors=("could not acquire the store write lock",),
                lock_acquired=False,
            )

        errors: list[str] = []
        refs = _recovery_refs(root, runner, op_prefix, errors)
        stashes = _recovery_stashes(root, runner, op_prefix, errors)
        stash_targets = {candidate.target for candidate in stashes}

        candidates = tuple(refs) + tuple(
            _RecoveryCandidate(
                kind=candidate.kind,
                identifier=candidate.identifier,
                target=candidate.target,
                created_at=candidate.created_at,
                is_stash_snapshot=True,
            )
            for candidate in stashes
        )
        fresh: list[str] = []
        stale: list[_RecoveryCandidate] = []
        for candidate in candidates:
            if candidate.created_at >= cutoff:
                fresh.append(candidate.identifier)
                continue
            stale.append(
                _RecoveryCandidate(
                    kind=candidate.kind,
                    identifier=candidate.identifier,
                    target=candidate.target,
                    created_at=candidate.created_at,
                    is_stash_snapshot=(
                        candidate.is_stash_snapshot
                        or candidate.target in stash_targets
                        or _target_looks_like_recovery_stash(
                            root, candidate.target, runner, op_prefix
                        )
                    ),
                )
            )

        removed_refs: list[str] = []
        removed_stashes: list[str] = []
        retained_unreachable: list[str] = []
        capped = False
        for candidate in sorted(
            stale, key=lambda item: (item.created_at, item.kind, item.identifier)
        ):
            if removal_budget <= 0:
                capped = True
                break
            guard_commit = _guard_commit_for_candidate(
                root,
                candidate,
                runner,
                op_prefix,
                errors,
            )
            if guard_commit is None or not _commit_reachable_from_remote_refs(
                root,
                guard_commit,
                runner,
                op_prefix,
                errors,
            ):
                retained_unreachable.append(candidate.identifier)
                continue
            if candidate.kind == "ref":
                if _delete_recovery_ref(root, candidate, runner, op_prefix, errors):
                    removed_refs.append(candidate.identifier)
                    removal_budget -= 1
                continue
            if _drop_recovery_stash(root, candidate, runner, op_prefix, errors):
                removed_stashes.append(candidate.identifier)
                removal_budget -= 1

        return _SddRecoveryReapResult(
            scanned_refs=len(refs),
            scanned_stashes=len(stashes),
            removed_refs=tuple(removed_refs),
            removed_stashes=tuple(removed_stashes),
            retained_fresh=tuple(fresh),
            retained_unreachable=tuple(retained_unreachable),
            errors=tuple(errors),
            capped=capped,
        )


def _recovery_refs(
    repo_root: Path,
    runner: GitRunner,
    op_prefix: str,
    errors: list[str],
) -> tuple[_RecoveryCandidate, ...]:
    result = runner(
        repo_root,
        [
            "for-each-ref",
            "--format=%(refname)%00%(objectname)%00%(committerdate:unix)",
            RECOVERY_REF_PREFIX,
        ],
        op=f"{op_prefix}.refs",
    )
    if result.returncode != 0:
        errors.append(format_git_error("could not list SDD recovery refs", result))
        return ()
    refs: list[_RecoveryCandidate] = []
    for line in result.stdout.splitlines():
        parts = line.split("\0")
        if len(parts) != 3:
            continue
        refname, target, raw_timestamp = parts
        if not refname.startswith(RECOVERY_REF_PREFIX) or not target:
            continue
        refs.append(
            _RecoveryCandidate(
                kind="ref",
                identifier=refname,
                target=target,
                created_at=_recovery_ref_timestamp(refname, raw_timestamp),
                is_stash_snapshot=False,
            )
        )
    return tuple(refs)


def _recovery_stashes(
    repo_root: Path,
    runner: GitRunner,
    op_prefix: str,
    errors: list[str],
) -> tuple[_RecoveryCandidate, ...]:
    result = runner(
        repo_root,
        ["stash", "list", "--format=%gd%x00%H%x00%ct%x00%gs"],
        op=f"{op_prefix}.stashes",
    )
    if result.returncode != 0:
        errors.append(format_git_error("could not list SDD recovery stashes", result))
        return ()
    stashes: list[_RecoveryCandidate] = []
    for line in result.stdout.splitlines():
        parts = line.split("\0")
        if len(parts) != 4:
            continue
        selector, target, raw_timestamp, subject = parts
        if RECOVERY_STASH_SUBJECT_FRAGMENT not in subject:
            continue
        stashes.append(
            _RecoveryCandidate(
                kind="stash",
                identifier=selector,
                target=target,
                created_at=_float_timestamp(raw_timestamp),
                is_stash_snapshot=True,
            )
        )
    return tuple(stashes)


def _recovery_ref_timestamp(refname: str, fallback: str) -> float:
    match = _RECOVERY_REF_STAMP.match(refname)
    if match is not None:
        try:
            return (
                datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ")
                .replace(tzinfo=UTC)
                .timestamp()
            )
        except ValueError:
            pass
    return _float_timestamp(fallback)


def _float_timestamp(raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _target_looks_like_recovery_stash(
    repo_root: Path,
    target: str,
    runner: GitRunner,
    op_prefix: str,
) -> bool:
    shape = _commit_shape(repo_root, target, runner, op_prefix)
    return (
        shape is not None
        and len(shape.parents) >= 2
        and RECOVERY_STASH_SUBJECT_FRAGMENT in shape.subject
    )


def _guard_commit_for_candidate(
    repo_root: Path,
    candidate: _RecoveryCandidate,
    runner: GitRunner,
    op_prefix: str,
    errors: list[str],
) -> str | None:
    if not candidate.is_stash_snapshot:
        return candidate.target
    shape = _commit_shape(repo_root, candidate.target, runner, op_prefix)
    if shape is None:
        errors.append(
            f"could not inspect recovery snapshot {candidate.identifier} "
            f"at {candidate.target}"
        )
        return None
    return shape.parents[0] if shape.parents else candidate.target


def _commit_shape(
    repo_root: Path,
    target: str,
    runner: GitRunner,
    op_prefix: str,
) -> _CommitShape | None:
    result = runner(
        repo_root,
        ["show", "-s", "--format=%P%x00%s", target],
        op=f"{op_prefix}.commit_shape",
    )
    if result.returncode != 0:
        return None
    parents, _, subject = result.stdout.rstrip("\n").partition("\0")
    return _CommitShape(
        parents=tuple(parent for parent in parents.split() if parent),
        subject=subject,
    )


def _commit_reachable_from_remote_refs(
    repo_root: Path,
    commit: str,
    runner: GitRunner,
    op_prefix: str,
    errors: list[str],
) -> bool:
    result = runner(
        repo_root,
        ["rev-list", "--max-count=1", commit, "--not", "--remotes"],
        op=f"{op_prefix}.remote_reachability",
    )
    if result.returncode != 0:
        errors.append(
            format_git_error(
                f"could not verify remote reachability for {commit}", result
            )
        )
        return False
    return not result.stdout.strip()


def _delete_recovery_ref(
    repo_root: Path,
    candidate: _RecoveryCandidate,
    runner: GitRunner,
    op_prefix: str,
    errors: list[str],
) -> bool:
    result = runner(
        repo_root,
        ["update-ref", "-d", candidate.identifier, candidate.target],
        op=f"{op_prefix}.delete_ref",
    )
    if result.returncode == 0:
        return True
    errors.append(
        format_git_error(
            f"could not delete recovery ref {candidate.identifier}", result
        )
    )
    return False


def _drop_recovery_stash(
    repo_root: Path,
    candidate: _RecoveryCandidate,
    runner: GitRunner,
    op_prefix: str,
    errors: list[str],
) -> bool:
    selector = _current_stash_selector_for_target(
        repo_root,
        candidate.target,
        runner,
        op_prefix,
        errors,
    )
    if selector is None:
        return False
    result = runner(
        repo_root,
        ["stash", "drop", selector],
        op=f"{op_prefix}.drop_stash",
    )
    if result.returncode == 0:
        return True
    errors.append(format_git_error(f"could not drop recovery stash {selector}", result))
    return False


def _current_stash_selector_for_target(
    repo_root: Path,
    target: str,
    runner: GitRunner,
    op_prefix: str,
    errors: list[str],
) -> str | None:
    result = runner(
        repo_root,
        ["stash", "list", "--format=%gd%x00%H"],
        op=f"{op_prefix}.current_stash",
    )
    if result.returncode != 0:
        errors.append(
            format_git_error("could not refresh SDD recovery stashes", result)
        )
        return None
    best_selector: str | None = None
    best_index = -1
    for line in result.stdout.splitlines():
        selector, _, sha = line.partition("\0")
        if sha != target:
            continue
        match = _STASH_INDEX.match(selector)
        index = int(match.group("index")) if match is not None else -1
        if index > best_index:
            best_selector = selector
            best_index = index
    if best_selector is None:
        errors.append(f"recovery stash {target} no longer exists")
    return best_selector


def safe_reap_sdd_recovery_snapshots(
    repo_root: Path,
    *,
    logger: Callable[[str], None],
    now: float | None = None,
    git_runner: GitRunner | None = None,
    lock_factory: LockFactory | None = None,
    op_prefix: str = "sdd.recovery_reap",
) -> None:
    """Best-effort wrapper for opportunistic recovery residue cleanup."""

    try:
        result = _reap_sdd_recovery_snapshots(
            repo_root,
            now=now,
            git_runner=git_runner,
            lock_factory=lock_factory,
            op_prefix=op_prefix,
        )
    except Exception as exc:  # noqa: BLE001 - cleanup must not replace Git outcome
        logger(f"failed to reap SDD recovery snapshots: {exc}")
        return
    if result.errors:
        logger("; ".join(result.errors))


__all__ = [
    "DEFAULT_RECOVERY_REAP_MAX_REMOVALS",
    "DEFAULT_RECOVERY_SNAPSHOT_RETENTION_SECONDS",
    "RECOVERY_REF_PREFIX",
    "RECOVERY_STASH_SUBJECT_FRAGMENT",
    "safe_reap_sdd_recovery_snapshots",
]

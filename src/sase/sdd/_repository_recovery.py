"""Opt-in self-healing for machine-managed SDD sidecar clones."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from sase.sdd._repository_transaction import (
    EventLogger,
    GitRunner,
    LockFactory,
    SddIntegrationOutcome,
    SddIntegrationStatus,
    SddRepositoryState,
    default_git_runner,
    format_git_error,
    inspect_sdd_repository,
    integrate_sdd_repository_transaction,
    sdd_rollback_mismatch,
    safe_git_error_text,
    sdd_state_blockers,
)

_RECOVERY_ATTEMPT_MARKER = "sase-sdd-recovery-attempt.json"
_RECOVERY_WARNING_MARKER = "sase-sdd-recovery-warning.json"
_RECOVERY_REPORT_MARKER = "sase-sdd-recovery-report.json"
_DEFAULT_RECOVERY_COOLDOWN_SECONDS = 300.0
_WARNING_COOLDOWN_SECONDS = 900.0
_REPORT_COOLDOWN_SECONDS = 3600.0


def recovery_failure_signature(
    repo_root: Path,
    outcome: SddIntegrationOutcome,
) -> str:
    """Return a stable clone-and-failure identity for durable rate limits."""
    root = repo_root.expanduser().resolve()
    detail = outcome.error or outcome.status.value
    payload = f"{root}\0{outcome.status.value}\0{detail}".encode(
        "utf-8", errors="replace"
    )
    return hashlib.sha256(payload).hexdigest()


def admit_recovery_notice(
    repo_root: Path,
    signature: str,
    *,
    report: bool = False,
    git_runner: GitRunner | None = None,
    lock_factory: LockFactory | None = None,
    clock: Callable[[], float] | None = None,
) -> bool:
    """Durably admit one warning or axe report for a failure signature."""
    root = repo_root.expanduser().resolve()
    runner = git_runner or default_git_runner
    if lock_factory is None:
        from sase.sdd._git_contention import store_git_write_lock

        lock_factory = store_git_write_lock
    now = (clock or time.time)()
    marker_name = _RECOVERY_REPORT_MARKER if report else _RECOVERY_WARNING_MARKER
    cooldown = _REPORT_COOLDOWN_SECONDS if report else _WARNING_COOLDOWN_SECONDS

    with lock_factory(root) as acquired:
        if not acquired:
            return False
        git_dir = _repository_git_dir(root, runner, op="sdd.recovery.notice")
        if git_dir is None:
            return False
        marker = git_dir / marker_name
        record = _read_marker(marker)
        if record.get("signature") == signature and _timestamp_is_recent(
            record.get("timestamp"), now, cooldown
        ):
            return False
        return _write_marker(
            marker,
            {
                "clone_path": str(root),
                "signature": signature,
                "timestamp": now,
            },
        )


def recover_machine_managed_sdd_repository(
    repo_root: Path,
    *,
    original: SddIntegrationOutcome,
    beads_dir: Path | None,
    expected_branch: str | None,
    op_prefix: str,
    git_runner: GitRunner | None,
    lock_factory: LockFactory | None,
    clock: Callable[[], float] | None,
    recovery_cooldown_seconds: float | None,
    event_logger: EventLogger | None,
) -> SddIntegrationOutcome:
    root = repo_root.expanduser().resolve()
    runner = git_runner or default_git_runner
    if lock_factory is None:
        from sase.sdd._git_contention import store_git_write_lock

        lock_factory = store_git_write_lock
    now = (clock or time.time)()
    cooldown = (
        _machine_recovery_cooldown_seconds()
        if recovery_cooldown_seconds is None
        else max(0.0, recovery_cooldown_seconds)
    )

    with lock_factory(root) as acquired:
        if not acquired:
            return _managed_recovery_failure(
                root,
                original=original,
                detail="could not acquire the store write lock",
                runner=runner,
                expected_branch=expected_branch,
            )
        try:
            starting = inspect_sdd_repository(root, runner)
        except Exception as exc:  # noqa: BLE001 - typed unsafe outcome
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=_recovery_error(
                    original,
                    f"could not inspect the managed clone: {safe_git_error_text(exc)}",
                ),
            )

        branch, branch_error = _managed_recovery_branch(starting)
        if branch_error is not None or branch is None:
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=_recovery_error(
                    original,
                    branch_error or "could not resolve the attached branch",
                ),
            )
        if expected_branch is not None and branch != expected_branch:
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=_recovery_error(
                    original,
                    f"expected branch {expected_branch!r}, found {branch!r}",
                ),
            )

        attempt_marker = starting.git_dir / _RECOVERY_ATTEMPT_MARKER
        attempt_record = _read_marker(attempt_marker)
        if _timestamp_is_recent(attempt_record.get("timestamp"), now, cooldown):
            return SddIntegrationOutcome(
                SddIntegrationStatus.RECOVERY_COOLDOWN,
                upstream_present=original.upstream_present,
                error=original.error,
            )
        if not _write_marker(
            attempt_marker,
            {
                "clone_path": str(root),
                "timestamp": now,
            },
        ):
            return _managed_recovery_failure(
                root,
                original=original,
                detail="could not persist the recovery-attempt marker",
                runner=runner,
                expected_branch=branch,
            )

        upstream_ref, remote, upstream_error = _configured_upstream(
            root,
            branch,
            runner,
            op_prefix,
        )
        if upstream_error is not None or upstream_ref is None or remote is None:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=upstream_error or "could not resolve the configured upstream",
                runner=runner,
                expected_branch=branch,
            )

        branch_head = runner(
            root,
            ["rev-parse", "--verify", f"refs/heads/{branch}"],
            op=f"{op_prefix}.recovery.branch_head",
        )
        if branch_head.returncode != 0 or not branch_head.stdout.strip():
            return _managed_recovery_failure(
                root,
                original=original,
                detail=format_git_error(
                    "could not resolve the managed branch", branch_head
                ),
                runner=runner,
                expected_branch=branch,
            )
        branch_sha = branch_head.stdout.strip()
        recovery_ref = _recovery_ref(root, branch, branch_sha, now)
        ref_error = _update_and_verify_ref(
            root,
            recovery_ref,
            branch_sha,
            runner,
            op_prefix,
        )
        if ref_error is not None:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=ref_error,
                runner=runner,
                expected_branch=branch,
            )

        if starting.operation_markers:
            aborted = runner(
                root,
                ["rebase", "--abort"],
                op=f"{op_prefix}.recovery.rebase_abort",
            )
            if aborted.returncode != 0:
                return _managed_recovery_failure(
                    root,
                    original=original,
                    detail=format_git_error(
                        "could not abort the stale rebase", aborted
                    ),
                    runner=runner,
                    expected_branch=branch,
                    recovery_ref=recovery_ref,
                )
            rebase_error = _verify_rebase_cleared(root, branch, runner)
            if rebase_error is not None:
                return _managed_recovery_failure(
                    root,
                    original=original,
                    detail=rebase_error,
                    runner=runner,
                    expected_branch=branch,
                    recovery_ref=recovery_ref,
                )

        if remote != ".":
            fetched = runner(
                root,
                ["fetch", "--prune", remote],
                op=f"{op_prefix}.recovery.fetch",
                network=True,
            )
            if fetched.returncode != 0:
                return _managed_recovery_failure(
                    root,
                    original=original,
                    detail=format_git_error("git fetch for recovery failed", fetched),
                    runner=runner,
                    expected_branch=branch,
                    recovery_ref=recovery_ref,
                )

        upstream_sha_result = runner(
            root,
            ["rev-parse", "--verify", upstream_ref],
            op=f"{op_prefix}.recovery.upstream",
        )
        if (
            upstream_sha_result.returncode != 0
            or not upstream_sha_result.stdout.strip()
        ):
            return _managed_recovery_failure(
                root,
                original=original,
                detail=format_git_error(
                    "could not resolve the fetched recovery upstream",
                    upstream_sha_result,
                ),
                runner=runner,
                expected_branch=branch,
                recovery_ref=recovery_ref,
            )
        upstream_sha = upstream_sha_result.stdout.strip()

        snapshot_ref, snapshot_error, snapshot_safe = _snapshot_managed_changes(
            root,
            branch=branch,
            recovery_ref=recovery_ref,
            runner=runner,
            op_prefix=op_prefix,
        )
        if snapshot_error is not None:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=snapshot_error,
                runner=runner,
                expected_branch=branch,
                recovery_ref=snapshot_ref or recovery_ref,
                force_unsafe=not snapshot_safe,
            )

        reset = runner(
            root,
            ["reset", "--hard", upstream_ref],
            op=f"{op_prefix}.recovery.reset",
        )
        if reset.returncode != 0:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=format_git_error("could not reset the managed branch", reset),
                runner=runner,
                expected_branch=branch,
                recovery_ref=snapshot_ref,
            )
        reset_error = _verify_managed_reset(
            root,
            branch=branch,
            upstream_sha=upstream_sha,
            runner=runner,
        )
        if reset_error is not None:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=reset_error,
                runner=runner,
                expected_branch=branch,
                recovery_ref=snapshot_ref,
            )

        retried = integrate_sdd_repository_transaction(
            root,
            beads_dir=beads_dir,
            upstream=upstream_ref,
            fetch=False,
            expected_branch=branch,
            op_prefix=f"{op_prefix}.recovery_retry",
            git_runner=runner,
            lock_factory=_already_locked,
            event_logger=event_logger,
        )
        if not retried.succeeded:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=(
                    "integration retry failed: "
                    + (retried.error or retried.status.value)
                ),
                runner=runner,
                expected_branch=branch,
                recovery_ref=snapshot_ref,
            )
        return SddIntegrationOutcome(
            SddIntegrationStatus.RECOVERED,
            integrated=True,
            upstream_present=True,
            resolved_files=retried.resolved_files,
            recovery_ref=snapshot_ref,
        )


def _managed_recovery_branch(
    state: SddRepositoryState,
) -> tuple[str | None, str | None]:
    if not state.valid_worktree:
        return None, "the checkout is not a valid Git worktree"
    operations = set(state.operation_markers)
    if operations - {"rebase"}:
        return None, (
            "automatic recovery refuses unrelated Git operations: "
            + ", ".join(sorted(operations))
        )
    if state.unmerged_paths and operations != {"rebase"}:
        return None, "automatic recovery refuses unmerged entries outside a rebase"
    if not operations:
        if state.branch is None:
            return None, "automatic recovery refuses a detached HEAD"
        return state.branch, None

    head_names: set[str] = set()
    for directory in ("rebase-merge", "rebase-apply"):
        try:
            raw = (state.git_dir / directory / "head-name").read_text(encoding="utf-8")
        except OSError:
            continue
        name = raw.strip()
        if name.startswith("refs/heads/"):
            head_names.add(name.removeprefix("refs/heads/"))
    if len(head_names) != 1:
        return None, "could not prove the original branch for the stale rebase"
    return next(iter(head_names)), None


def _configured_upstream(
    repo_root: Path,
    branch: str,
    runner: GitRunner,
    op_prefix: str,
) -> tuple[str | None, str | None, str | None]:
    upstream = runner(
        repo_root,
        [
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{branch}@{{upstream}}",
        ],
        op=f"{op_prefix}.recovery.upstream_name",
    )
    if upstream.returncode != 0 or not upstream.stdout.strip():
        return (
            None,
            None,
            format_git_error(
                f"branch {branch!r} has no configured upstream",
                upstream,
            ),
        )
    remote = runner(
        repo_root,
        ["config", "--get", f"branch.{branch}.remote"],
        op=f"{op_prefix}.recovery.remote",
    )
    if remote.returncode != 0 or not remote.stdout.strip():
        return (
            None,
            None,
            format_git_error(
                f"branch {branch!r} has no configured upstream remote",
                remote,
            ),
        )
    return upstream.stdout.strip(), remote.stdout.strip(), None


def _recovery_ref(repo_root: Path, branch: str, head: str, now: float) -> str:
    stamp = datetime.fromtimestamp(now, tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_branch = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip(".-") or "branch"
    identity = f"{repo_root}\0{branch}\0{head}\0{now}\0{os.getpid()}"
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:10]
    return f"refs/sase/recovery/{stamp}-{safe_branch}-{suffix}"


def _update_and_verify_ref(
    repo_root: Path,
    recovery_ref: str,
    target: str,
    runner: GitRunner,
    op_prefix: str,
) -> str | None:
    updated = runner(
        repo_root,
        ["update-ref", recovery_ref, target],
        op=f"{op_prefix}.recovery.snapshot_ref",
    )
    if updated.returncode != 0:
        return format_git_error("could not create the recovery ref", updated)
    verified = runner(
        repo_root,
        ["rev-parse", "--verify", recovery_ref],
        op=f"{op_prefix}.recovery.verify_ref",
    )
    if verified.returncode != 0 or verified.stdout.strip() != target:
        return "could not verify the recovery ref; the managed branch was not reset"
    return None


def _verify_rebase_cleared(
    repo_root: Path,
    branch: str,
    runner: GitRunner,
) -> str | None:
    try:
        state = inspect_sdd_repository(repo_root, runner)
    except Exception as exc:  # noqa: BLE001 - fail closed
        return f"could not inspect the aborted rebase: {safe_git_error_text(exc)}"
    problems = sdd_state_blockers(state, branch)
    if state.operation_markers:
        problems.append("rebase markers remain after abort")
    if state.unmerged_paths:
        problems.append("unmerged entries remain after abort")
    if problems:
        return "stale rebase cleanup could not be verified: " + "; ".join(problems)
    return None


def _snapshot_managed_changes(
    repo_root: Path,
    *,
    branch: str,
    recovery_ref: str,
    runner: GitRunner,
    op_prefix: str,
) -> tuple[str | None, str | None, bool]:
    try:
        before = inspect_sdd_repository(repo_root, runner)
    except Exception as exc:  # noqa: BLE001 - fail closed
        return (
            recovery_ref,
            f"could not inspect local changes: {safe_git_error_text(exc)}",
            True,
        )
    blockers = sdd_state_blockers(before, branch)
    if blockers:
        return (
            recovery_ref,
            "cannot snapshot an unsafe checkout: " + "; ".join(blockers),
            True,
        )
    if not before.status_porcelain:
        return recovery_ref, None, True

    tracked = _has_git_changes(
        repo_root,
        ["diff", "--quiet"],
        runner,
        f"{op_prefix}.recovery.snapshot_tracked",
    )
    staged = _has_git_changes(
        repo_root,
        ["diff", "--cached", "--quiet"],
        runner,
        f"{op_prefix}.recovery.snapshot_staged",
    )
    untracked_result = runner(
        repo_root,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        op=f"{op_prefix}.recovery.snapshot_untracked",
    )
    if tracked is None or staged is None or untracked_result.returncode != 0:
        return (
            recovery_ref,
            "could not classify local changes before snapshotting",
            True,
        )
    untracked = {path for path in untracked_result.stdout.split("\0") if path}

    previous_stash = runner(
        repo_root,
        ["rev-parse", "--verify", "refs/stash"],
        op=f"{op_prefix}.recovery.previous_stash",
    )
    previous_stash_sha = (
        previous_stash.stdout.strip() if previous_stash.returncode == 0 else None
    )
    stashed = runner(
        repo_root,
        [
            "stash",
            "push",
            "--include-untracked",
            "--message",
            f"sase recovery {recovery_ref}",
        ],
        op=f"{op_prefix}.recovery.stash",
    )
    stash_result = runner(
        repo_root,
        ["rev-parse", "--verify", "refs/stash"],
        op=f"{op_prefix}.recovery.stash_ref",
    )
    stash_sha = stash_result.stdout.strip() if stash_result.returncode == 0 else None
    stash_created = stash_sha is not None and stash_sha != previous_stash_sha
    if stashed.returncode != 0 or not stash_created or stash_sha is None:
        restore_error = _restore_failed_snapshot(
            repo_root,
            before=before,
            stash_sha=stash_sha if stash_created else None,
            runner=runner,
            op_prefix=op_prefix,
        )
        detail = format_git_error("could not snapshot local changes", stashed)
        if restore_error is not None:
            detail += f"; snapshot rollback failed: {restore_error}"
        return recovery_ref, detail, restore_error is None

    ref_error = _update_and_verify_ref(
        repo_root,
        recovery_ref,
        stash_sha,
        runner,
        op_prefix,
    )
    verify_error = ref_error or _verify_stash_snapshot(
        repo_root,
        stash_sha=stash_sha,
        tracked_or_staged=tracked or staged,
        untracked=untracked,
        runner=runner,
        op_prefix=op_prefix,
    )
    if verify_error is None:
        try:
            after = inspect_sdd_repository(repo_root, runner)
        except Exception as exc:  # noqa: BLE001 - verification failure
            verify_error = (
                f"could not inspect the stashed checkout: {safe_git_error_text(exc)}"
            )
        else:
            if after.blockers or after.branch != branch or after.status_porcelain:
                verify_error = "snapshot did not leave a clean attached checkout"
    if verify_error is None:
        return recovery_ref, None, True

    restore_error = _restore_failed_snapshot(
        repo_root,
        before=before,
        stash_sha=stash_sha,
        runner=runner,
        op_prefix=op_prefix,
    )
    if restore_error is not None:
        verify_error += f"; snapshot rollback failed: {restore_error}"
    return recovery_ref, verify_error, restore_error is None


def _has_git_changes(
    repo_root: Path,
    args: list[str],
    runner: GitRunner,
    op: str,
) -> bool | None:
    result = runner(repo_root, args, op=op)
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    return None


def _verify_stash_snapshot(
    repo_root: Path,
    *,
    stash_sha: str,
    tracked_or_staged: bool,
    untracked: set[str],
    runner: GitRunner,
    op_prefix: str,
) -> str | None:
    if tracked_or_staged:
        diff = runner(
            repo_root,
            ["diff", "--quiet", f"{stash_sha}^1", stash_sha],
            op=f"{op_prefix}.recovery.verify_stash_tracked",
        )
        if diff.returncode != 1:
            return "the recovery snapshot does not contain tracked/index changes"
    if untracked:
        tree = runner(
            repo_root,
            ["ls-tree", "-r", "--name-only", "-z", f"{stash_sha}^3"],
            op=f"{op_prefix}.recovery.verify_stash_untracked",
        )
        snapshot_untracked = {path for path in tree.stdout.split("\0") if path}
        if tree.returncode != 0 or not untracked.issubset(snapshot_untracked):
            return "the recovery snapshot does not contain all untracked changes"
    return None


def _restore_failed_snapshot(
    repo_root: Path,
    *,
    before: SddRepositoryState,
    stash_sha: str | None,
    runner: GitRunner,
    op_prefix: str,
) -> str | None:
    if stash_sha is not None:
        restored = runner(
            repo_root,
            ["stash", "apply", "--index", stash_sha],
            op=f"{op_prefix}.recovery.stash_restore",
        )
        if restored.returncode != 0:
            return format_git_error("git stash apply failed", restored)
    try:
        final = inspect_sdd_repository(repo_root, runner)
    except Exception as exc:  # noqa: BLE001 - restoration cannot be proven
        return f"could not inspect restored local changes: {safe_git_error_text(exc)}"
    return sdd_rollback_mismatch(before, final)


def _verify_managed_reset(
    repo_root: Path,
    *,
    branch: str,
    upstream_sha: str,
    runner: GitRunner,
) -> str | None:
    try:
        state = inspect_sdd_repository(repo_root, runner)
    except Exception as exc:  # noqa: BLE001 - fail closed
        return f"could not inspect the reset checkout: {safe_git_error_text(exc)}"
    problems = sdd_state_blockers(state, branch)
    if state.status_porcelain:
        problems.append("worktree or index is not clean after reset")
    if state.head != upstream_sha:
        problems.append(f"HEAD is {state.head!r}, expected upstream {upstream_sha!r}")
    if problems:
        return "managed reset could not be verified: " + "; ".join(problems)
    return None


def _managed_recovery_failure(
    repo_root: Path,
    *,
    original: SddIntegrationOutcome,
    detail: str,
    runner: GitRunner,
    expected_branch: str | None,
    recovery_ref: str | None = None,
    force_unsafe: bool = False,
) -> SddIntegrationOutcome:
    try:
        state = inspect_sdd_repository(repo_root, runner)
    except Exception:
        healthy = False
    else:
        healthy = not force_unsafe and not sdd_state_blockers(state, expected_branch)
    return SddIntegrationOutcome(
        (
            SddIntegrationStatus.RECOVERY_FAILED
            if healthy
            else SddIntegrationStatus.UNRECOVERABLE
        ),
        upstream_present=original.upstream_present,
        error=_recovery_error(original, detail),
        recovery_ref=recovery_ref,
    )


def _recovery_error(original: SddIntegrationOutcome, detail: str) -> str:
    original_detail = original.error or original.status.value
    return f"{original_detail}; machine-managed recovery failed: {detail}"


def _machine_recovery_cooldown_seconds() -> float:
    try:
        from sase.sdd._integration_marker import bead_refresh_ttl_seconds

        refresh_ttl = bead_refresh_ttl_seconds()
    except Exception:
        refresh_ttl = 0.0
    return max(_DEFAULT_RECOVERY_COOLDOWN_SECONDS, refresh_ttl)


@contextmanager
def _already_locked(_repo_root: Path) -> Iterator[bool]:
    yield True


def _repository_git_dir(
    repo_root: Path,
    runner: GitRunner,
    *,
    op: str,
) -> Path | None:
    result = runner(repo_root, ["rev-parse", "--git-dir"], op=op)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    git_dir = Path(result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    return git_dir


def _read_marker(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_marker(path: Path, value: dict[str, Any]) -> bool:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def _timestamp_is_recent(
    raw_timestamp: Any,
    now: float,
    cooldown_seconds: float,
) -> bool:
    try:
        timestamp = float(raw_timestamp)
    except (TypeError, ValueError):
        return False
    age = now - timestamp
    return age < cooldown_seconds if age >= 0 else True


__all__ = [
    "admit_recovery_notice",
    "recovery_failure_signature",
]

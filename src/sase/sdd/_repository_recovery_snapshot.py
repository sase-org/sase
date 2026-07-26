"""Local-change snapshots for machine-managed SDD recovery."""

from __future__ import annotations

import logging
from pathlib import Path

from sase.sdd._repository_recovery_git import update_and_verify_ref
from sase.sdd._repository_transaction import (
    GitRunner,
    SddRepositoryState,
    format_git_error,
    inspect_sdd_repository,
    safe_git_error_text,
    sdd_rollback_mismatch,
    sdd_rollback_observation_delta,
    sdd_state_blockers,
)

_logger = logging.getLogger(__name__)


def snapshot_managed_changes(
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
    if stashed.returncode == 0 and not stash_created:
        try:
            current = inspect_sdd_repository(repo_root, runner)
        except Exception as exc:  # noqa: BLE001 - fail closed
            return (
                recovery_ref,
                "could not inspect checkout after no-op snapshot: "
                + safe_git_error_text(exc),
                True,
            )
        blockers = sdd_state_blockers(current, branch)
        current_tracked = _has_git_changes(
            repo_root,
            ["diff", "--quiet"],
            runner,
            f"{op_prefix}.recovery.snapshot_noop_tracked",
        )
        current_staged = _has_git_changes(
            repo_root,
            ["diff", "--cached", "--quiet"],
            runner,
            f"{op_prefix}.recovery.snapshot_noop_staged",
        )
        if blockers:
            return (
                recovery_ref,
                "no-op snapshot left an unsafe checkout: " + "; ".join(blockers),
                False,
            )
        owned_drift = sdd_rollback_mismatch(before, current)
        if owned_drift is not None:
            return (
                recovery_ref,
                f"checkout changed while a no-op snapshot was attempted: {owned_drift}",
                True,
            )
        if current_tracked is None or current_staged is None:
            return (
                recovery_ref,
                "could not classify checkout after no-op snapshot",
                True,
            )
        if current_tracked or current_staged:
            return (
                recovery_ref,
                "checkout changed while a no-op recovery snapshot was attempted",
                True,
            )
        _warn_observation_delta(repo_root, before, current)
        return recovery_ref, None, True
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

    ref_error = update_and_verify_ref(
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
    comparison_start = before
    if stash_sha is None:
        try:
            comparison_start = inspect_sdd_repository(repo_root, runner)
        except Exception as exc:  # noqa: BLE001 - restoration cannot be proven
            return (
                "could not inspect local changes before rollback verification: "
                + safe_git_error_text(exc)
            )
        owned_drift = sdd_rollback_mismatch(before, comparison_start)
        if owned_drift is not None:
            return owned_drift
        _warn_observation_delta(repo_root, before, comparison_start)
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
    expected = before if stash_sha is not None else comparison_start
    mismatch = sdd_rollback_mismatch(expected, final)
    if mismatch is None:
        _warn_observation_delta(repo_root, expected, final)
    return mismatch


def _warn_observation_delta(
    repo_root: Path,
    starting: SddRepositoryState,
    final: SddRepositoryState,
) -> None:
    observation_delta = sdd_rollback_observation_delta(starting, final)
    if observation_delta is not None:
        _logger.warning(
            "SDD recovery preserved SASE-owned repository invariants in %s, but %s",
            repo_root,
            observation_delta,
        )

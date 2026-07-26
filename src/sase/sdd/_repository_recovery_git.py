"""Git state helpers for machine-managed SDD repository recovery."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import re

from sase.sdd._repository_transaction import (
    GitRunner,
    SddIntegrationOutcome,
    SddIntegrationStatus,
    SddRepositoryState,
    format_git_error,
    inspect_sdd_repository,
    safe_git_error_text,
    sdd_state_blockers,
)

_DEFAULT_RECOVERY_COOLDOWN_SECONDS = 300.0


def managed_recovery_branch(
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
    if state.unmerged_error is not None:
        # An undetermined probe is not a clean index; recovery is destructive
        # enough that it must not run on an unproven premise.
        return None, (
            "automatic recovery could not determine unmerged entries: "
            + state.unmerged_error
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


def configured_upstream(
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


def recovery_ref(repo_root: Path, branch: str, head: str, now: float) -> str:
    stamp = datetime.fromtimestamp(now, tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_branch = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip(".-") or "branch"
    identity = f"{repo_root}\0{branch}\0{head}\0{now}\0{os.getpid()}"
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:10]
    return f"refs/sase/recovery/{stamp}-{safe_branch}-{suffix}"


def update_and_verify_ref(
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


def verify_rebase_cleared(
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
    if state.unmerged_error is not None:
        problems.append(
            "could not determine unmerged entries after abort: " + state.unmerged_error
        )
    elif state.unmerged_paths:
        problems.append("unmerged entries remain after abort")
    if problems:
        return "stale rebase cleanup could not be verified: " + "; ".join(problems)
    return None


def verify_managed_reset(
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


def managed_recovery_failure(
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
        error=recovery_error(original, detail),
        recovery_ref=recovery_ref,
    )


def recovery_error(original: SddIntegrationOutcome, detail: str) -> str:
    original_detail = original.error or original.status.value
    return f"{original_detail}; machine-managed recovery failed: {detail}"


def machine_recovery_cooldown_seconds() -> float:
    try:
        from sase.sdd._integration_marker import bead_refresh_ttl_seconds

        refresh_ttl = bead_refresh_ttl_seconds()
    except Exception:
        refresh_ttl = 0.0
    return max(_DEFAULT_RECOVERY_COOLDOWN_SECONDS, refresh_ttl)


@contextmanager
def already_locked(_repo_root: Path) -> Iterator[bool]:
    yield True

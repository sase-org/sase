"""Shared types for SDD repository integration and recovery."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import subprocess
from typing import Any, Literal

from sase.bead.relocation import BeadIdRelocation


class SddGitTimeoutResult(subprocess.CompletedProcess[str]):
    """A git result that failed because a timeout expired, not the repo."""

    def __init__(
        self,
        args: Any,
        returncode: int = 124,
        stdout: str = "",
        stderr: str = "",
        timeout_reason: Literal["deadline", "wall_clock"] = "deadline",
    ) -> None:
        super().__init__(args, returncode, stdout, stderr)
        self.timeout_reason: Literal["deadline", "wall_clock"] = timeout_reason


def is_git_timeout(result: object) -> bool:
    """Return whether *result* is a typed git-timeout result."""
    return isinstance(result, SddGitTimeoutResult)


class SddIntegrationStatus(StrEnum):
    """Typed terminal state for one fetch/rebase transaction."""

    SUCCESS = "success"
    REMOTE_UNAVAILABLE = "remote_unavailable_but_healthy"
    REPAIRED_BEAD_CONFLICTS = "repaired_bead_conflicts"
    REPAIRED_SEMANTIC_CONFLICTS = "repaired_semantic_conflicts"
    ABORTED_UNSUPPORTED_CONFLICTS = "aborted_unsupported_conflicts"
    LOCAL_CHANGES = "local_changes_preserved"
    LOCK_UNAVAILABLE = "store_write_lock_unavailable"
    # A git probe or operation timed out before SASE changed the checkout, or
    # SASE's rollback was verified; the checkout is presumed as-found and the
    # attempt should simply be retried later.
    TIMED_OUT = "git_timed_out_state_unknown"
    RECOVERED = "machine_managed_recovered"
    RECOVERY_COOLDOWN = "machine_managed_recovery_cooldown"
    RECOVERY_FAILED = "machine_managed_recovery_failed"
    UNRECOVERABLE = "unrecoverable_repository_state"


@dataclass(frozen=True)
class UnmergedPathsProbe:
    """Three-state answer to "which index entries are unmerged?".

    ``error is None`` means the probe ran and ``paths`` is authoritative — an
    empty tuple then genuinely means "no conflicts". A non-``None`` ``error``
    means the probe could not tell, which is not the same as clean.
    """

    paths: tuple[str, ...] = ()
    error: str | None = None


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
    # ``None`` when the unmerged probe ran; otherwise why it could not tell, in
    # which case ``unmerged_paths`` is empty because it is unknown, not clean.
    unmerged_error: str | None = None

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
        if self.unmerged_error is not None:
            blockers.append(self.unmerged_error)
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
    bead_relocations: tuple[BeadIdRelocation, ...] = ()
    recovery_ref: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in {
            SddIntegrationStatus.SUCCESS,
            SddIntegrationStatus.REPAIRED_BEAD_CONFLICTS,
            SddIntegrationStatus.REPAIRED_SEMANTIC_CONFLICTS,
            SddIntegrationStatus.RECOVERED,
        }

    @property
    def structurally_healthy(self) -> bool:
        return self.status is not SddIntegrationStatus.UNRECOVERABLE


GitRunner = Callable[..., subprocess.CompletedProcess[str]]
LockFactory = Callable[[Path], AbstractContextManager[bool]]
EventLogger = Callable[..., None]

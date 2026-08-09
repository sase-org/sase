"""Data models for editable-install dev updates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from sase.version._models import VersionPackageRecord

DevLatestState = Literal[
    "current",
    "update_available",
    "dirty",
    "diverged",
    "detached",
    "no_upstream",
    "offline",
    "fetch_failed",
    "unavailable",
]

DevPackagePlanStatus = Literal["actionable", "skipped"]
DevUpdateOutcomeStatus = Literal["updated", "skipped", "failed"]
DevReconcileStepKind = Literal[
    "uv_tool_install",
    "rust_prebuild_install",
    "rust_dev_install",
    "rust_install_uv_tool",
    "rust_health_check",
    "rust_lsp_install",
]


@dataclass(frozen=True)
class RepoDiffStat:
    """Line-oriented git diff stats for one repository."""

    files_changed: int
    insertions: int
    deletions: int

    @property
    def is_empty(self) -> bool:
        return self.files_changed == 0 and self.insertions == 0 and self.deletions == 0

    @property
    def has_line_changes(self) -> bool:
        return self.insertions > 0 or self.deletions > 0


@dataclass(frozen=True)
class RepoCommit:
    """One commit applied to a repository during a dev update."""

    short_sha: str
    subject: str


@dataclass(frozen=True)
class RepoCommitLog:
    """A capped applied-commit log plus its authoritative total count."""

    total: int
    commits: tuple[RepoCommit, ...]

    @property
    def extra(self) -> int:
        return max(0, self.total - len(self.commits))


@dataclass(frozen=True)
class DevLatest:
    """Latest-dev information for one editable package."""

    record: VersionPackageRecord
    state: DevLatestState
    reason: str
    current_version: str
    latest_version: str | None
    update_available: bool
    git_root: str | None = None
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    fetch_error: str | None = None


@dataclass(frozen=True)
class DevUpdatePackagePlan:
    """Per-package plan entry."""

    record: VersionPackageRecord
    status: DevPackagePlanStatus
    reason: str
    current_version: str
    latest_version: str | None
    git_root: str | None = None
    upstream: str | None = None
    remote: str | None = None
    remote_branch: str | None = None
    ahead: int | None = None
    behind: int | None = None
    fetch_error: str | None = None


@dataclass(frozen=True)
class DevUpdateRootPlan:
    """Deduped git-root plan shared by one or more packages."""

    git_root: str
    status: DevPackagePlanStatus
    reason: str
    upstream: str | None
    remote: str | None
    remote_branch: str | None
    packages: tuple[str, ...]
    ahead: int | None = None
    behind: int | None = None
    fetch_error: str | None = None


@dataclass(frozen=True)
class DevReconcileStep:
    """A post-fast-forward environment reconciliation command.

    ``env`` is an overlay applied by the executor over the parent environment.
    """

    kind: DevReconcileStepKind
    label: str
    command: tuple[str, ...]
    cwd: str | None = None
    reason: str | None = None
    env: Mapping[str, str] | None = None
    repair_command: tuple[str, ...] = ()
    repair_cwd: str | None = None
    repair_label: str | None = None
    repair_reason: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.command)


@dataclass(frozen=True)
class DevUpdatePlan:
    """Complete editable-install update plan."""

    packages: tuple[DevUpdatePackagePlan, ...]
    roots: tuple[DevUpdateRootPlan, ...]
    reconcile_steps: tuple[DevReconcileStep, ...]

    @property
    def actionable(self) -> tuple[DevUpdatePackagePlan, ...]:
        return tuple(pkg for pkg in self.packages if pkg.status == "actionable")

    @property
    def skipped(self) -> tuple[DevUpdatePackagePlan, ...]:
        return tuple(pkg for pkg in self.packages if pkg.status == "skipped")

    @property
    def actionable_roots(self) -> tuple[DevUpdateRootPlan, ...]:
        return tuple(root for root in self.roots if root.status == "actionable")


@dataclass(frozen=True)
class DevCommandResult:
    """Result returned by an injected dev-update subprocess runner."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class DevCommandRunner(Protocol):
    """Subprocess runner used by ``execute_dev_update``."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> DevCommandResult:
        """Run ``argv``; a non-``None`` ``env`` is a complete child environment."""
        ...


@dataclass(frozen=True)
class DevUpdateOutcome:
    """Per-package execution outcome."""

    record: VersionPackageRecord
    status: DevUpdateOutcomeStatus
    reason: str
    old_version: str | None
    new_version: str | None
    git_root: str | None = None
    diffstat: RepoDiffStat | None = None
    commits: RepoCommitLog | None = None


@dataclass(frozen=True)
class DevExecutedCommand:
    """A command attempted during update execution."""

    label: str
    command: tuple[str, ...]
    cwd: str | None
    returncode: int
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class DevRustPrebuildResult:
    """Outcome of attempting to install cached Rust dev artifacts."""

    attempted: bool = False
    hit: bool = False
    reason: str = "not-attempted"


@dataclass(frozen=True)
class DevUpdateResult:
    """Complete editable-install update result."""

    changed: bool
    outcomes: tuple[DevUpdateOutcome, ...]
    commands: tuple[DevExecutedCommand, ...] = ()
    duration_seconds: float = 0.0
    rust_prebuild: DevRustPrebuildResult = field(default_factory=DevRustPrebuildResult)

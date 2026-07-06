"""Data models for install-mode switching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TargetMode = Literal["dev", "pypi"]
DetectedMode = Literal["managed", "dev", "mixed"]
SwitchRole = Literal["host", "core", "plugin"]
RepoAction = Literal["clone", "reuse", "stays-managed", "none"]
CommandKind = Literal[
    "git_clone",
    "git_fetch",
    "git_merge_ff",
    "uv_tool_install",
    "rust_install_uv_tool",
]
OutcomeStatus = Literal["switched", "stayed-managed", "failed"]


@dataclass(frozen=True)
class SwitchPackagePlan:
    """One package row in a mode-switch preview."""

    name: str
    role: SwitchRole
    current_version: str | None
    target_version: str | None
    source: str
    repo_action: RepoAction = "none"
    checkout_path: str | None = None
    repo_url: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class ModeSwitchCommand:
    """A command that will run during a confirmed mode switch."""

    kind: CommandKind
    label: str
    command: tuple[str, ...]
    cwd: str | None = None
    available: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class SwitchPlan:
    """Complete preview for switching install mode."""

    current_mode: DetectedMode
    target_mode: TargetMode
    dev_root: str | None
    packages: tuple[SwitchPackagePlan, ...]
    commands: tuple[ModeSwitchCommand, ...]
    warnings: tuple[str, ...] = ()
    restore_command: tuple[str, ...] = ()
    backup_path: str | None = None

    @property
    def changed(self) -> bool:
        if self.current_mode == "mixed":
            return True
        return self.current_mode != ("managed" if self.target_mode == "pypi" else "dev")

    @property
    def target_label(self) -> str:
        return mode_label(self.target_mode)

    @property
    def current_label(self) -> str:
        return detected_mode_label(self.current_mode)


@dataclass(frozen=True)
class ModeSwitchOutcome:
    """Per-package result after a successful switch."""

    name: str
    role: SwitchRole
    status: OutcomeStatus
    old_version: str | None
    new_version: str | None
    source: str


@dataclass(frozen=True)
class ModeSwitchResult:
    """Execution result for a mode switch."""

    plan: SwitchPlan
    changed: bool
    outcomes: tuple[ModeSwitchOutcome, ...]
    commands: tuple[ModeSwitchCommand, ...]


def mode_label(mode: TargetMode) -> str:
    if mode == "dev":
        return "Dev (editable)"
    return "PyPI (managed)"


def detected_mode_label(mode: DetectedMode | str) -> str:
    if mode == "dev":
        return "Dev (editable)"
    if mode == "managed":
        return "PyPI (managed)"
    return "Mixed"

"""Typed models shared by agent-CLI detection, planning, and presentation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InstallMethod(StrEnum):
    """How an installed provider CLI is managed."""

    NOT_INSTALLED = "not_installed"
    NPM = "npm"
    HOMEBREW = "homebrew"
    SELF_MANAGED = "self_managed"
    BUNDLED = "bundled"
    UNKNOWN = "unknown"


class UpdateStrategy(StrEnum):
    """The operation SASE can safely use for an agent CLI."""

    NPM = "npm"
    SELF_UPDATE = "self_update"
    MANUAL = "manual"
    NONE = "none"


class UpdateResultStatus(StrEnum):
    """Terminal state of one planned agent-CLI update."""

    UPDATED = "updated"
    ALREADY_CURRENT = "already_current"
    FAILED = "failed"
    SKIPPED = "skipped"


class UpdateTrigger(StrEnum):
    """The SASE entry point that initiated an agent-CLI update run."""

    COMPREHENSIVE = "comprehensive"
    ADMIN_CENTER = "admin_center"
    CLI = "cli"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AgentCliStatus:
    """Detected state and update capability for one provider CLI."""

    name: str
    display_name: str
    binary: str
    executable: str | None
    installed_version: str | None
    latest_version: str | None
    install_method: InstallMethod
    update_available: bool
    docs_url: str | None
    install_hint: str
    package: str | None = None
    latest_version_package: str | None = None
    self_update_argv: tuple[str, ...] = ()
    version_argv: tuple[str, ...] = ("--version",)
    version_regex: str | None = None
    brew_package: str | None = None
    npm_root_writable: bool | None = None
    version_error: str | None = None
    latest_error: str | None = None

    @property
    def installed(self) -> bool:
        return (
            self.executable is not None or self.install_method is InstallMethod.BUNDLED
        )

    @property
    def provider(self) -> str:
        """Alias for callers that label the registry key as a provider."""
        return self.name

    @property
    def cli_name(self) -> str:
        """Alias matching the provider registry's CLI-name terminology."""
        return self.binary


@dataclass(frozen=True)
class AgentCliUpdateEntry:
    """One selected CLI's exact update command or explicit skip reason."""

    status: AgentCliStatus
    strategy: UpdateStrategy
    argv: tuple[str, ...] | None
    skip_reason: str | None = None
    manual_argv: tuple[str, ...] | None = None

    @property
    def name(self) -> str:
        return self.status.name

    @property
    def ready(self) -> bool:
        return self.argv is not None


@dataclass(frozen=True)
class AgentCliUpdatesReady:
    """At least one selected CLI has a safe executable update command."""

    entries: tuple[AgentCliUpdateEntry, ...]
    all_clis: bool

    @property
    def runnable_entries(self) -> tuple[AgentCliUpdateEntry, ...]:
        return tuple(entry for entry in self.entries if entry.ready)


@dataclass(frozen=True)
class AgentCliNothingToUpdate:
    """All selected CLIs are current, unavailable, bundled, or manual-only."""

    entries: tuple[AgentCliUpdateEntry, ...]
    all_clis: bool


@dataclass(frozen=True)
class AgentCliUnknownName:
    """A requested name did not match a registered provider CLI."""

    query: str
    known_names: tuple[str, ...]
    suggestions: tuple[str, ...] = ()


AgentCliUpdatePlan = (
    AgentCliUpdatesReady | AgentCliNothingToUpdate | AgentCliUnknownName
)


@dataclass(frozen=True)
class AgentCliUpdateResult:
    """Execution result for one planned agent CLI."""

    name: str
    display_name: str
    status: UpdateResultStatus
    old_version: str | None
    new_version: str | None
    command: tuple[str, ...] | None
    docs_url: str | None
    suggested_command: tuple[str, ...] | None = None
    elapsed: float = 0.0
    reason: str | None = None
    output_tail: str | None = None


# Short aliases keep call sites readable while retaining descriptive public names.
UpdateReady = AgentCliUpdatesReady
NothingToUpdate = AgentCliNothingToUpdate
UnknownName = AgentCliUnknownName
UpdateEntry = AgentCliUpdateEntry
UpdateResult = AgentCliUpdateResult


__all__ = [
    "AgentCliNothingToUpdate",
    "AgentCliStatus",
    "AgentCliUnknownName",
    "AgentCliUpdateEntry",
    "AgentCliUpdatePlan",
    "AgentCliUpdateResult",
    "AgentCliUpdatesReady",
    "InstallMethod",
    "NothingToUpdate",
    "UnknownName",
    "UpdateEntry",
    "UpdateReady",
    "UpdateResult",
    "UpdateResultStatus",
    "UpdateStrategy",
    "UpdateTrigger",
]

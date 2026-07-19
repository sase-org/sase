"""Shared types for agent cleanup TUI modals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

AgentCleanupAction = Literal[
    "dismiss_panel_done",
    "dismiss_all_done",
    "kill_panel",
    "kill_all",
    "marked",
    "group",
    "tribe",
    "clan",
    "custom",
]
AgentCleanupAgentIdentity = tuple[Any, str, str | None]
AgentCleanupClanKey = tuple[str, str | None]
StatusFilter = Literal["done", "running", "failed", "waiting"]


@dataclass(frozen=True)
class AgentCleanupResult:
    """Selected cleanup action."""

    action: AgentCleanupAction


@dataclass(frozen=True)
class AgentCleanupTribeResult:
    """Selected tribes for tribe-scoped cleanup."""

    tribes: tuple[str, ...]


@dataclass(frozen=True)
class AgentCleanupClanResult:
    """Selected whole clans and individual members for clan cleanup."""

    clans: tuple[AgentCleanupClanKey, ...]
    identities: tuple[AgentCleanupAgentIdentity, ...]


@dataclass(frozen=True)
class AgentCleanupCustomResult:
    """Selected agent identities for custom cleanup."""

    identities: tuple[AgentCleanupAgentIdentity, ...]


@dataclass(frozen=True)
class AgentCleanupPanelState:
    """Counts and availability for the cleanup panel shell."""

    focused_panel_label: str
    panel_running_count: int
    panel_completed_count: int
    panel_failed_count: int
    all_running_count: int
    all_completed_count: int
    all_failed_count: int
    marked_count: int
    group_count: int
    tribe_count: int
    clan_count: int = 0
    focused_clan_label: str | None = None


__all__ = [
    "AgentCleanupAction",
    "AgentCleanupAgentIdentity",
    "AgentCleanupClanKey",
    "AgentCleanupClanResult",
    "AgentCleanupCustomResult",
    "AgentCleanupPanelState",
    "AgentCleanupResult",
    "AgentCleanupTribeResult",
    "StatusFilter",
]

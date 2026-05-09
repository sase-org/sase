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
    "tag",
    "custom",
]
AgentCleanupAgentIdentity = tuple[Any, str, str | None]
StatusFilter = Literal["done", "running", "failed", "waiting"]


@dataclass(frozen=True)
class AgentCleanupResult:
    """Selected cleanup action."""

    action: AgentCleanupAction


@dataclass(frozen=True)
class AgentCleanupTagResult:
    """Selected tags for tag-scoped cleanup."""

    tags: tuple[str, ...]

    @property
    def tag(self) -> str:
        """Compatibility accessor for single-tag callers."""
        if len(self.tags) != 1:
            raise ValueError("AgentCleanupTagResult.tag requires exactly one tag")
        return self.tags[0]


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
    tag_count: int


__all__ = [
    "AgentCleanupAction",
    "AgentCleanupAgentIdentity",
    "AgentCleanupCustomResult",
    "AgentCleanupPanelState",
    "AgentCleanupResult",
    "AgentCleanupTagResult",
    "StatusFilter",
]

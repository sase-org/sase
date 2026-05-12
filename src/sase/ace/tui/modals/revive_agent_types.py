"""Shared types and constants for the revive agent modal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..models.agent import Agent, AgentType

if TYPE_CHECKING:
    from ...agent_query.archive_planner import ArchiveQueryPage, ArchiveQueryResult

# Reuse the same type->color mapping from the agent list widget.
TYPE_COLORS: dict[AgentType, str] = {
    AgentType.RUNNING: "#87AFFF",
    AgentType.WORKFLOW: "#FF87D7",
}

# Per-step-type colors for workflow child entries.
STEP_TYPE_COLORS: dict[str, str] = {
    "agent": "#5FD7FF",
    "bash": "#FFAF5F",
    "python": "#87D787",
    "parallel": "#D7AFFF",
}

STATUS_COLORS: dict[str, str] = {
    "DONE": "#5FD75F",
    "FAILED": "#FF5F5F",
    "WAITING INPUT": "#FF87D7",
}


class ArchiveQueryProvider(Protocol):
    """Archive-backed query and hydration hooks used by the revive modal."""

    def search(
        self,
        query: str,
        *,
        limit: int,
        cursor: int | None = None,
    ) -> ArchiveQueryPage:
        """Return a page of archive summary rows."""
        ...

    def hydrate(self, result: ArchiveQueryResult) -> list[Agent]:
        """Hydrate the selected archive result and related rows."""
        ...


@dataclass
class DismissedEntry:
    """One selectable revive row, either hydrated or archive-summary backed."""

    agent: Agent | None = None
    archive_result: ArchiveQueryResult | None = None

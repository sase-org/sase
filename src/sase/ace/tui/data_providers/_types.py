"""Type contracts shared by ACE data providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ..models.agent import Agent
from ..models.agent_loader import AgentLoadState
from ..provider_contract import AceSnapshot


@dataclass(frozen=True)
class AgentsProviderSnapshot:
    """Agents-tab snapshot returned by either direct or daemon providers."""

    agents: list[Agent]
    workflow_agent_steps: list[Agent]
    load_state: AgentLoadState
    shared_snapshot: AceSnapshot[Agent]
    used_daemon: bool = False
    fallback_reason: str | None = None
    fallback_message: str | None = None
    snapshot_id: str | None = None


@dataclass(frozen=True)
class AgentEventApplyResult:
    """Result of applying daemon agent delta events to an in-memory snapshot."""

    agents: list[Agent]
    resync_required: bool = False
    resync_reason: str | None = None


@dataclass(frozen=True)
class AgentsViewport:
    """Bounded Agents-tab read window used by daemon-backed providers."""

    start_row: int = 0
    visible_rows: int = 40
    prefetch_rows: int = 80

    @property
    def requested_limit(self) -> int:
        return max(1, self.start_row + self.visible_rows + self.prefetch_rows)


class AgentsDataProvider(Protocol):
    """Provider contract for the ACE Agents tab."""

    prefers_daemon: bool

    def load_agents(
        self,
        *,
        patch_snapshot: list[Any] | None = None,
        full_history: bool = False,
        use_artifact_index: bool = True,
        index_freshness: Literal["revalidate", "cached"] = "cached",
        search_query: str | None = None,
        viewport: AgentsViewport | None = None,
    ) -> AgentsProviderSnapshot:
        """Load an Agents-tab snapshot without touching Textual widgets."""


_AgentEventApplyResult = AgentEventApplyResult
_AgentsProviderSnapshot = AgentsProviderSnapshot

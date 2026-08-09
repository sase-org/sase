"""Direct source-store/index-backed Agents-tab provider."""

from __future__ import annotations

from typing import Any

from ._snapshots import agent_snapshot
from ._types import AgentsProviderSnapshot, AgentsViewport


class DirectAgentsDataProvider:
    """Current source-store/index-backed Agents-tab provider."""

    prefers_daemon = False

    def load_agents(
        self,
        *,
        patch_snapshot: list[Any] | None = None,
        full_history: bool = False,
        search_query: str | None = None,
        viewport: AgentsViewport | None = None,
    ) -> AgentsProviderSnapshot:
        from ..models.agent_loader import load_tiered_agents

        del search_query, viewport
        agents, load_state = load_tiered_agents(
            patch_snapshot=patch_snapshot,
            full_history=full_history,
        )
        shared_snapshot = agent_snapshot(
            agents,
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id=None,
            page_count=1,
            full_reload=True,
        )
        return AgentsProviderSnapshot(
            agents=agents,
            workflow_agent_steps=[],
            load_state=load_state,
            shared_snapshot=shared_snapshot,
            used_daemon=False,
        )


_DirectAgentsDataProvider = DirectAgentsDataProvider

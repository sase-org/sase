"""Direct source-store/index-backed Agents-tab provider."""

from __future__ import annotations

from typing import Any
from typing import Literal

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
        use_artifact_index: bool = True,
        index_freshness: Literal["revalidate", "cached"] = "cached",
        search_query: str | None = None,
        viewport: AgentsViewport | None = None,
    ) -> AgentsProviderSnapshot:
        from ..models.agent_loader import load_tiered_agents

        requested_limit = (
            None if full_history or viewport is None else viewport.requested_limit
        )
        agents, load_state = load_tiered_agents(
            patch_snapshot=patch_snapshot,
            full_history=full_history,
            use_artifact_index=use_artifact_index,
            index_freshness=index_freshness,
            search_query=search_query,
            requested_limit=requested_limit,
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
            requested_limit=(
                load_state.requested_limit if load_state.bounded_prefix else None
            ),
            returned_count=load_state.returned_count or len(agents),
            has_more=load_state.has_more,
            bounded_prefix=load_state.bounded_prefix,
            query=search_query,
            surfaces=["list"],
        )
        return AgentsProviderSnapshot(
            agents=agents,
            workflow_agent_steps=[],
            load_state=load_state,
            shared_snapshot=shared_snapshot,
            used_daemon=False,
        )


_DirectAgentsDataProvider = DirectAgentsDataProvider

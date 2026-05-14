"""Daemon-backed Agents-tab provider."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.daemon.client import LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback
from sase.daemon.read_models import AgentProjectionSummary

from ..models.agent import Agent
from ..models.agent_loader import AgentLoadState
from ._conversion import agent_from_summary
from ._daemon_pages import agent_daemon_surfaces, read_agent_page
from ._events import apply_daemon_agent_events
from ._normalize import prepare_daemon_agents
from ._snapshots import agent_snapshot
from ._types import (
    AgentEventApplyResult,
    AgentsProviderSnapshot,
    AgentsDataProvider,
    AgentsViewport,
)


class DaemonAgentsDataProvider:
    """Daemon projection-backed provider for the ACE Agents tab."""

    prefers_daemon = True

    def __init__(
        self,
        *,
        client: LocalDaemonClient | None = None,
        project_ids: Sequence[str] | None = None,
        direct_provider: AgentsDataProvider | None = None,
    ) -> None:
        from ._direct import DirectAgentsDataProvider

        self._client = client
        self._project_ids = list(project_ids) if project_ids is not None else None
        self._direct_provider = direct_provider or DirectAgentsDataProvider()

    def load_agents(
        self,
        *,
        changespec_snapshot: list[Any] | None = None,
        full_history: bool = False,
        search_query: str | None = None,
        viewport: AgentsViewport | None = None,
    ) -> AgentsProviderSnapshot:
        def direct_loader() -> AgentsProviderSnapshot:
            return self._direct_provider.load_agents(
                changespec_snapshot=changespec_snapshot,
                full_history=full_history,
            )

        result: DaemonReadResult[AgentsProviderSnapshot] = read_or_fallback(
            _rollout_surface_for_agents_read(
                full_history=full_history,
                search_query=search_query,
            ),
            client=self._client,
            required_capability="agents.read",
            daemon_loader=lambda client: self._load_daemon_snapshot(
                client,
                full_history=full_history,
                search_query=search_query,
                viewport=viewport,
            ),
            direct_loader=direct_loader,
        )
        if result.used_daemon:
            return result.value
        shared_snapshot = agent_snapshot(
            result.value.agents,
            provider_source="direct_fallback",
            prefers_daemon=True,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
            snapshot_id=result.value.snapshot_id,
            page_count=result.value.shared_snapshot.metadata.get("page_count", 1),
            full_reload=True,
        )
        return AgentsProviderSnapshot(
            agents=result.value.agents,
            workflow_agent_steps=result.value.workflow_agent_steps,
            load_state=result.value.load_state,
            shared_snapshot=shared_snapshot,
            used_daemon=False,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
            snapshot_id=result.value.snapshot_id,
        )

    def _load_daemon_snapshot(
        self,
        client: LocalDaemonClient,
        *,
        full_history: bool,
        search_query: str | None,
        viewport: AgentsViewport | None,
    ) -> AgentsProviderSnapshot:
        summaries: list[AgentProjectionSummary] = []
        snapshot_id: str | None = None
        page_count = 0
        next_cursor: str | None = None
        read_surfaces = agent_daemon_surfaces(
            full_history=full_history,
            search_query=search_query,
        )
        page_limit = (viewport or AgentsViewport()).requested_limit
        for project_id in self._daemon_project_ids():
            for surface in read_surfaces:
                page = read_agent_page(
                    client,
                    surface,
                    project_id=project_id,
                    include_hidden=True,
                    query=search_query,
                    limit=page_limit,
                )
                summaries.extend(page.agents)
                snapshot_id = snapshot_id or page.snapshot_id
                next_cursor = next_cursor or page.next_cursor
                page_count += 1

        agents = prepare_daemon_agents(agent_from_summary(row) for row in summaries)
        shared_snapshot = agent_snapshot(
            agents,
            provider_source="daemon",
            prefers_daemon=True,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id=snapshot_id,
            page_count=page_count,
            full_reload=False,
            requested_limit=page_limit,
            next_cursor=next_cursor,
            query=search_query,
            surfaces=read_surfaces,
        )
        return AgentsProviderSnapshot(
            agents=agents,
            workflow_agent_steps=[],
            load_state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="daemon_projection",
                used_artifact_index=False,
            ),
            shared_snapshot=shared_snapshot,
            used_daemon=True,
            snapshot_id=snapshot_id,
        )

    def apply_event_batch(
        self,
        agents: Sequence[Agent],
        event_batch: dict[str, Any],
    ) -> AgentEventApplyResult:
        """Apply daemon delta events produced for the agents collection."""

        return apply_daemon_agent_events(agents, event_batch)

    def _daemon_project_ids(self) -> list[str]:
        if self._project_ids is not None:
            return list(self._project_ids)
        projects_root = Path.home() / ".sase" / "projects"
        if not projects_root.is_dir():
            return []
        return sorted(path.name for path in projects_root.iterdir() if path.is_dir())


_DaemonAgentsDataProvider = DaemonAgentsDataProvider


def _rollout_surface_for_agents_read(
    *,
    full_history: bool,
    search_query: str | None,
) -> str:
    if search_query:
        return "ace_search"
    if full_history:
        return "ace_archive"
    return "ace_agent_recent"

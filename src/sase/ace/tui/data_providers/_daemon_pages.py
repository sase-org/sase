"""Daemon page-read helpers for agent projections."""

from __future__ import annotations

from dataclasses import dataclass

from sase.daemon.client import LocalDaemonClient
from sase.daemon.read_models import AgentProjectionSummary, agent_list_from_dict


@dataclass(frozen=True)
class _DaemonAgentPage:
    agents: list[AgentProjectionSummary]
    snapshot_id: str | None
    page_count: int
    next_cursor: str | None = None


def agent_daemon_surfaces(
    *,
    full_history: bool,
    search_query: str | None,
) -> list[str]:
    if search_query:
        return ["agent_search"]
    if full_history:
        return ["agent_archive"]
    return ["agent_active", "agent_recent"]


def read_agent_page(
    client: LocalDaemonClient,
    surface: str,
    *,
    project_id: str,
    include_hidden: bool,
    query: str | None,
    limit: int,
) -> _DaemonAgentPage:
    if surface == "agent_active":
        data = client.agent_active(
            project_id=project_id,
            include_hidden=include_hidden,
            query=query,
            limit=limit,
        )
    elif surface == "agent_recent":
        data = client.agent_recent(
            project_id=project_id,
            include_hidden=include_hidden,
            query=query,
            limit=limit,
        )
    elif surface == "agent_archive":
        data = client.agent_archive(
            project_id=project_id,
            include_hidden=include_hidden,
            query=query,
            limit=limit,
        )
    elif surface == "agent_search":
        data = client.agent_search(
            project_id=project_id,
            include_hidden=include_hidden,
            query=query,
            limit=limit,
        )
    else:
        raise ValueError(f"unsupported daemon agent surface: {surface}")
    page = agent_list_from_dict(data)
    return _DaemonAgentPage(
        agents=page.agents,
        snapshot_id=page.snapshot.snapshot_id,
        page_count=1,
        next_cursor=page.page.next_cursor,
    )


def read_ace_agent_snapshot_page(
    client: LocalDaemonClient,
    *,
    include_hidden: bool,
    query: str | None,
    limit: int,
) -> _DaemonAgentPage:
    data = client.ace_agent_snapshot(
        include_hidden=include_hidden,
        query=query,
        limit=limit,
    )
    page = agent_list_from_dict(data)
    return _DaemonAgentPage(
        agents=page.agents,
        snapshot_id=page.snapshot.snapshot_id,
        page_count=1,
        next_cursor=page.page.next_cursor,
    )

"""Shared ACE snapshot construction for data providers."""

from __future__ import annotations

from collections.abc import Sequence

from ..models.agent import Agent
from ..provider_contract import (
    AceFallbackMetadata,
    AceProviderCapabilities,
    AceProviderInfo,
    AceSnapshot,
    make_snapshot,
    trace_provider_snapshot,
)
from ._handles import agent_row_handle


def agent_snapshot(
    agents: Sequence[Agent],
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
    page_count: int,
    full_reload: bool,
    requested_limit: int | None = None,
    returned_count: int | None = None,
    has_more: bool | None = None,
    bounded_prefix: bool | None = None,
    next_cursor: str | None = None,
    query: str | None = None,
    surfaces: Sequence[str] | None = None,
) -> AceSnapshot[Agent]:
    snapshot = make_snapshot(
        surface="agents",
        rows=list(agents),
        row_handles=[agent_row_handle(agent) for agent in agents],
        provider=AceProviderInfo(
            identity=f"agents:{provider_source}",
            surface="agents",
            source=provider_source,
            prefers_daemon=prefers_daemon,
            capabilities=AceProviderCapabilities(
                pages=provider_source == "daemon",
                deltas=provider_source == "daemon",
                lazy_details=provider_source == "daemon",
            ),
            fallback=AceFallbackMetadata(fallback_reason, fallback_message),
        ),
        snapshot_id=snapshot_id,
        page_count=page_count,
        next_cursor=next_cursor,
        full_reload=full_reload,
        metadata={
            "requested_limit": requested_limit,
            "returned_count": returned_count,
            "has_more": has_more,
            "bounded_prefix": bounded_prefix,
            "query": query,
            "surfaces": list(surfaces or ()),
        },
    )
    trace_provider_snapshot(snapshot)
    return snapshot


_agent_snapshot = agent_snapshot

"""Outbox queries shared by commit-publication operations."""

from __future__ import annotations

from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    list_agent_publications,
)


def active_agent_publications(
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    return list_agent_publications(project_key, include_quarantined=False)


def quarantined_count(items: tuple[AgentPublicationOutboxItem, ...]) -> int:
    return sum(item.quarantined and not item.terminal for item in items)


def retired_count(items: tuple[AgentPublicationOutboxItem, ...]) -> int:
    return sum(item.terminal for item in items)

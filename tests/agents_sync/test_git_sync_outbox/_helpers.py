"""Shared builders for git-sync outbox tests."""

from __future__ import annotations

from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    update_agent_publications,
)


def retire_publication(
    item: AgentPublicationOutboxItem,
    error: str = "legacy mismatch",
) -> None:
    for _ in range(2):
        update_agent_publications(
            item.project_key,
            (item.logical_key,),
            error=error,
            increment_attempts=True,
            quarantine_threshold=2,
            terminal_reason=error,
        )

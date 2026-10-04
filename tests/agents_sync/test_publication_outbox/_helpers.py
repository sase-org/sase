"""Shared builders for publication-outbox tests."""

from __future__ import annotations

from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem


def make_outbox_item(
    *,
    local_agent: str = "foo--code",
    global_agent: str = "alice.athena.foo--code",
    revision: str = "a" * 40,
    project_key: str = "proj",
    local_hood: str = "foo",
) -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key=project_key,
        project="Project",
        local_agent=local_agent,
        global_agent=global_agent,
        primary_revision=revision,
        local_hood=local_hood,
    )

from __future__ import annotations

from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    acknowledge_agent_publications,
    enqueue_agent_publication,
    list_agent_publications,
    update_agent_publications,
)


def _item() -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent="foo--code",
        global_agent="alice.athena.foo--code",
        primary_revision="a" * 40,
        local_hood="foo",
    )


def test_outbox_is_idempotent_updates_digest_and_acknowledges(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    first = enqueue_agent_publication(_item())
    repeated = enqueue_agent_publication(_item())

    assert first.logical_key == repeated.logical_key
    assert len(list_agent_publications("proj")) == 1

    updated = update_agent_publications(
        "proj",
        (first.logical_key,),
        hood_digest="digest-v2",
        error="push rejected",
        increment_attempts=True,
    )
    assert len(updated) == 1
    assert updated[0].hood_digest == "digest-v2"
    assert updated[0].attempts == 1
    assert updated[0].last_error == "push rejected"
    assert updated[0].id != first.id

    assert acknowledge_agent_publications("proj", (first.logical_key,)) == ()
    assert list_agent_publications("proj") == ()

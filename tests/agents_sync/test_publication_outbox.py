from __future__ import annotations

import json

from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    acknowledge_agent_publications,
    clear_quarantined_agent_publications,
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


def test_repeated_item_failure_is_quarantined_and_manually_clearable(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    item = enqueue_agent_publication(_item())

    update_agent_publications(
        "proj",
        (item.logical_key,),
        error="bad history",
        increment_attempts=True,
        quarantine_threshold=2,
    )
    assert len(list_agent_publications("proj", include_quarantined=False)) == 1

    quarantined = update_agent_publications(
        "proj",
        (item.logical_key,),
        error="bad history",
        increment_attempts=True,
        quarantine_threshold=2,
    )[0]
    assert quarantined.quarantined
    assert quarantined.quarantined_at is not None
    assert quarantined.attempts == 2
    assert (
        list_agent_publications(
            "proj",
            include_quarantined=False,
        )
        == ()
    )

    cleared = clear_quarantined_agent_publications("proj")[0]
    assert not cleared.quarantined
    assert cleared.quarantined_at is None
    assert cleared.attempts == 0
    assert cleared.last_error is None


def test_schema_v1_backlog_is_read_and_upgraded_without_data_loss(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = _item().to_json_dict()
    row.pop("quarantined")
    row.pop("quarantined_at")
    path.write_text(
        json.dumps({"schema_version": 1, "items": [row]}),
        encoding="utf-8",
    )

    loaded = list_agent_publications("proj")
    assert len(loaded) == 1
    assert not loaded[0].quarantined

    update_agent_publications(
        "proj",
        (loaded[0].logical_key,),
        error="still pending",
    )
    upgraded = json.loads(path.read_text(encoding="utf-8"))
    assert upgraded["schema_version"] == 2
    assert upgraded["items"][0]["quarantined"] is False
    assert upgraded["items"][0]["quarantined_at"] is None

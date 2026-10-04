"""Revive selected retired and quarantined publication-outbox rows."""

from __future__ import annotations

import threading

from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
    revive_agent_publications,
    update_agent_publications,
)
from tests.agents_sync.test_publication_outbox._helpers import make_outbox_item


def _retire(
    item: AgentPublicationOutboxItem,
    error: str = "legacy mismatch",
    *,
    threshold: int = 2,
) -> AgentPublicationOutboxItem:
    retired = item
    for _ in range(threshold):
        updated = update_agent_publications(
            item.project_key,
            (item.logical_key,),
            error=error,
            increment_attempts=True,
            quarantine_threshold=threshold,
            terminal_reason=error,
        )
        retired = next(row for row in updated if row.logical_key == item.logical_key)
    return retired


def test_revive_retired_resets_selected_rows_and_preserves_identity(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    retired_item = enqueue_agent_publication(make_outbox_item())
    created_at = retired_item.created_at
    quarantined_item = enqueue_agent_publication(
        make_outbox_item(
            local_agent="bar--code",
            global_agent="alice.athena.bar--code",
            revision="b" * 40,
        )
    )
    other = enqueue_agent_publication(
        make_outbox_item(
            local_agent="other",
            global_agent="alice.athena.other",
            revision="c" * 40,
            project_key="other",
            local_hood="other",
        )
    )
    _retire(retired_item, "legacy mismatch")
    update_agent_publications(
        "proj",
        (quarantined_item.logical_key,),
        error="push rejected",
        increment_attempts=True,
        quarantine_threshold=1,
    )
    _retire(other, "other project failure")

    revived, diagnostics = revive_agent_publications(
        "proj",
        retry_retired=True,
        retry_quarantined=False,
    )

    assert len(revived) == 1
    assert revived[0].logical_key == retired_item.logical_key
    assert revived[0].created_at == created_at
    assert revived[0].local_hood == "foo"
    assert revived[0].hood_digest == retired_item.hood_digest
    assert revived[0].attempts == 0
    assert revived[0].last_error is None
    assert not revived[0].terminal
    assert revived[0].terminal_reason is None
    assert not revived[0].quarantined
    assert "retried 1 retired publication request" in diagnostics
    assert "legacy mismatch" in diagnostics[1]

    remaining = {item.logical_key: item for item in list_agent_publications("proj")}
    assert remaining[quarantined_item.logical_key].quarantined
    assert remaining[retired_item.logical_key].attempts == 0
    [still_retired] = list_agent_publications("other")
    assert still_retired.terminal
    assert still_retired.terminal_reason == "other project failure"

    again, again_diagnostics = revive_agent_publications(
        "proj",
        retry_retired=True,
        retry_quarantined=False,
    )
    assert again == ()
    assert again_diagnostics == ()


def test_revive_can_select_retired_and_quarantined_together(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    retired_item = enqueue_agent_publication(make_outbox_item())
    quarantined_item = enqueue_agent_publication(
        make_outbox_item(
            local_agent="bar--code",
            global_agent="alice.athena.bar--code",
            revision="b" * 40,
        )
    )
    active = enqueue_agent_publication(
        make_outbox_item(
            local_agent="live",
            global_agent="alice.athena.live",
            revision="c" * 40,
        )
    )
    _retire(retired_item)
    update_agent_publications(
        "proj",
        (quarantined_item.logical_key,),
        error="malformed history",
        increment_attempts=True,
        quarantine_threshold=1,
    )

    revived, diagnostics = revive_agent_publications(
        "proj",
        retry_retired=True,
        retry_quarantined=True,
    )
    keys = {item.logical_key for item in revived}
    assert keys == {retired_item.logical_key, quarantined_item.logical_key}
    assert active.logical_key not in keys
    assert any("retired" in line for line in diagnostics)
    assert any("quarantined" in line for line in diagnostics)
    listed = {item.logical_key: item for item in list_agent_publications("proj")}
    assert listed[active.logical_key].attempts == 0
    assert not listed[retired_item.logical_key].terminal
    assert not listed[quarantined_item.logical_key].quarantined


def test_revive_preserves_a_concurrent_enqueue(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    retired_item = enqueue_agent_publication(make_outbox_item())
    _retire(retired_item)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def revive() -> None:
        try:
            barrier.wait(timeout=10)
            revive_agent_publications(
                "proj",
                retry_retired=True,
                retry_quarantined=False,
            )
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            errors.append(exc)

    def enqueue() -> None:
        try:
            barrier.wait(timeout=10)
            enqueue_agent_publication(
                make_outbox_item(
                    local_agent="worker-new",
                    global_agent="alice.athena.worker-new",
                    revision="d" * 40,
                )
            )
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            errors.append(exc)

    threads = (
        threading.Thread(target=revive, name="revive"),
        threading.Thread(target=enqueue, name="enqueue"),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == []
    keys = {item.logical_key for item in list_agent_publications("proj")}
    assert retired_item.logical_key in keys
    assert ("alice.athena.worker-new", "d" * 40) in keys
    revived = next(
        item
        for item in list_agent_publications("proj")
        if item.logical_key == retired_item.logical_key
    )
    assert not revived.terminal

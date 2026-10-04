"""Enqueue, acknowledge, quarantine, terminal, and concurrent-outbox tests."""

from __future__ import annotations

import threading

from sase.agents_sync.publication_outbox import (
    acknowledge_agent_publications,
    clear_quarantined_agent_publications,
    enqueue_agent_publication,
    list_agent_publications,
    publication_quarantine_diagnostics,
    update_agent_publications,
)
from tests.agents_sync.test_publication_outbox._helpers import make_outbox_item


def _concurrent_enqueue(index: int) -> None:
    enqueue_agent_publication(make_outbox_item(revision="f" * 40))
    enqueue_agent_publication(
        make_outbox_item(
            local_agent=f"worker-{index}",
            global_agent=f"alice.athena.worker-{index}",
            revision=f"{index:040x}",
        )
    )


def test_outbox_is_idempotent_updates_digest_and_acknowledges(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    first = enqueue_agent_publication(make_outbox_item())
    repeated = enqueue_agent_publication(make_outbox_item())

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
    item = enqueue_agent_publication(make_outbox_item())

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


def test_repeated_terminal_failure_retires_without_quarantining(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    item = enqueue_agent_publication(make_outbox_item())
    error = "hood 'foo' has no publishable runs"

    first = update_agent_publications(
        "proj",
        (item.logical_key,),
        error=error,
        increment_attempts=True,
        quarantine_threshold=2,
        terminal_reason=error,
    )[0]

    assert first.attempts == 1
    assert not first.terminal
    assert first.terminal_reason is None
    assert list_agent_publications("proj", include_quarantined=False) == (first,)

    retired = update_agent_publications(
        "proj",
        (item.logical_key,),
        error=error,
        increment_attempts=True,
        quarantine_threshold=2,
        terminal_reason=error,
    )[0]

    assert retired.attempts == 2
    assert retired.terminal
    assert retired.terminal_reason == error
    assert not retired.quarantined
    assert retired.quarantined_at is None
    assert list_agent_publications("proj", include_quarantined=False) == ()


def test_retry_quarantined_keeps_terminal_retired(
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
    terminal_error = "hood 'foo' has no publishable runs"
    for _ in range(2):
        update_agent_publications(
            "proj",
            (retired_item.logical_key,),
            error=terminal_error,
            increment_attempts=True,
            quarantine_threshold=2,
            terminal_reason=terminal_error,
        )
    update_agent_publications(
        "proj",
        (quarantined_item.logical_key,),
        error="malformed history",
        increment_attempts=True,
        quarantine_threshold=1,
    )

    retried = clear_quarantined_agent_publications("proj")
    retired = next(
        item for item in retried if item.logical_key == retired_item.logical_key
    )
    active = next(
        item for item in retried if item.logical_key == quarantined_item.logical_key
    )
    assert retired.terminal and retired.terminal_reason == terminal_error
    assert retired.attempts == 2
    assert not active.quarantined and active.attempts == 0
    assert active.last_error is None

    assert list_agent_publications("proj") == retried


def test_diagnostics_separate_retryable_quarantine_from_retired_requests(
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
    terminal_error = "hood 'foo' has no publishable runs"
    for _ in range(2):
        update_agent_publications(
            "proj",
            (retired_item.logical_key,),
            error=terminal_error,
            increment_attempts=True,
            quarantine_threshold=3,
            terminal_reason=terminal_error,
        )
    update_agent_publications(
        "proj",
        (quarantined_item.logical_key,),
        error="malformed history",
        increment_attempts=True,
        quarantine_threshold=1,
    )

    retired_line, quarantined_line = publication_quarantine_diagnostics("proj")

    assert "retired as unpublishable" in retired_line
    assert terminal_error in retired_line
    assert "`sase agent sync --drop-retired` to drop it" in retired_line
    assert "--retry-quarantined" not in retired_line

    assert "quarantined after 1 attempts" in quarantined_line
    assert "`sase agent sync --retry-quarantined` to retry" in quarantined_line
    assert "--drop-retired" not in quarantined_line


def test_two_workers_enqueue_without_lost_or_duplicate_requests(
    tmp_path,
    monkeypatch,
) -> None:
    state_path = str(tmp_path / "state")
    monkeypatch.setenv("SASE_HOME", state_path)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def enqueue(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            _concurrent_enqueue(index)
        except BaseException as exc:  # noqa: BLE001 - re-raised in test thread
            errors.append(exc)

    threads = tuple(
        threading.Thread(target=enqueue, args=(index,), name=f"enqueue-{index}")
        for index in range(2)
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive(), f"{thread.name} did not finish"

    assert not errors
    queued = list_agent_publications("proj")
    assert len(queued) == 3
    assert len({item.logical_key for item in queued}) == 3

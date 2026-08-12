from __future__ import annotations

from sase.agents_sync.referenced_by_outbox import (
    ReferencedByOutboxItem,
    acknowledge_referenced_by_requests,
    clear_quarantined_referenced_by_requests,
    drop_terminal_referenced_by_requests,
    enqueue_referenced_by_request,
    list_referenced_by_requests,
    referenced_by_quarantine_diagnostics,
    update_referenced_by_requests,
)


def _item(
    *,
    revision: str = "a" * 40,
    artifact_id: str = "plan:202608/example.md",
    uses: int = 1,
    destination: str | None = "https://example.test/prompts/1",
) -> ReferencedByOutboxItem:
    return ReferencedByOutboxItem(
        project_key="proj",
        project="Project",
        global_agent="alice.athena.worker",
        agent_url="https://example.test/agents/worker",
        primary_revision=revision,
        sidecar_role="plans",
        provider="plan",
        artifact_id=artifact_id,
        repo_relpath=artifact_id.removeprefix("plan:"),
        identity_value=None,
        canonical_ref=artifact_id,
        destination=destination,
        uses=uses,
        published_date="2026-08-12",
    )


def test_referenced_by_outbox_is_idempotent_updates_and_acknowledges(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    first = enqueue_referenced_by_request(_item())
    repeated = enqueue_referenced_by_request(
        _item(uses=3, destination="https://example.test/prompts/updated")
    )

    assert first.logical_key == repeated.logical_key
    queued = list_referenced_by_requests("proj")
    assert len(queued) == 1
    assert queued[0].uses == 3
    assert queued[0].destination == "https://example.test/prompts/updated"

    updated = update_referenced_by_requests(
        "proj",
        (first.logical_key,),
        error="push rejected",
        increment_attempts=True,
    )
    assert len(updated) == 1
    assert updated[0].attempts == 1
    assert updated[0].last_error == "push rejected"

    assert acknowledge_referenced_by_requests("proj", (first.logical_key,)) == ()
    assert list_referenced_by_requests("proj") == ()


def test_referenced_by_quarantine_retry_and_terminal_drop(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    retryable = enqueue_referenced_by_request(_item())

    [quarantined] = update_referenced_by_requests(
        "proj",
        (retryable.logical_key,),
        error="lock busy",
        increment_attempts=True,
        quarantine_threshold=1,
    )
    assert quarantined.quarantined
    assert list_referenced_by_requests("proj", include_quarantined=False) == ()
    assert (
        "quarantined after 1 attempts"
        in referenced_by_quarantine_diagnostics("proj")[0]
    )

    [cleared] = clear_quarantined_referenced_by_requests("proj")
    assert not cleared.quarantined
    assert cleared.attempts == 0
    assert cleared.last_error is None

    terminal = enqueue_referenced_by_request(
        _item(revision="b" * 40, artifact_id="plan:202608/missing.md")
    )
    terminal_error = "artifact document is missing"
    for _ in range(2):
        update_referenced_by_requests(
            "proj",
            (terminal.logical_key,),
            error=terminal_error,
            increment_attempts=True,
            quarantine_threshold=3,
            terminal_reason=terminal_error,
        )

    diagnostics = referenced_by_quarantine_diagnostics("proj")
    assert any("retired as unpublishable" in line for line in diagnostics)
    [dropped] = drop_terminal_referenced_by_requests("proj")
    assert dropped.logical_key == terminal.logical_key
    assert dropped.terminal
    assert list_referenced_by_requests("proj") == (cleared,)

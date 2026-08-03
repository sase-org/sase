from __future__ import annotations

import json
import multiprocessing
import os

import pytest
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    PUBLICATION_OUTBOX_SCHEMA_VERSION,
    acknowledge_agent_publications,
    clear_quarantined_agent_publications,
    drop_terminal_agent_publications,
    enqueue_agent_publication,
    enqueue_bead_pages_publication,
    enqueue_plan_header_publication,
    enqueue_sidecar_push_publication,
    list_agent_publications,
    publication_quarantine_diagnostics,
    snapshot_agent_publications_from_path,
    update_agent_publications,
)


def _concurrent_enqueue(state_path: str, index: int) -> None:
    os.environ["SASE_HOME"] = state_path
    enqueue_agent_publication(_item(revision="f" * 40))
    enqueue_agent_publication(
        _item(
            local_agent=f"worker-{index}",
            global_agent=f"alice.athena.worker-{index}",
            revision=f"{index:040x}",
        )
    )


def _item(
    *,
    local_agent: str = "foo--code",
    global_agent: str = "alice.athena.foo--code",
    revision: str = "a" * 40,
) -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=local_agent,
        global_agent=global_agent,
        primary_revision=revision,
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


def test_repeated_terminal_failure_retires_without_quarantining(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    item = enqueue_agent_publication(_item())
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
    retired_item = enqueue_agent_publication(_item())
    quarantined_item = enqueue_agent_publication(
        _item(
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
    retired_item = enqueue_agent_publication(_item())
    quarantined_item = enqueue_agent_publication(
        _item(
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
    row.pop("terminal")
    row.pop("terminal_reason")
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
    assert upgraded["schema_version"] == PUBLICATION_OUTBOX_SCHEMA_VERSION
    assert upgraded["items"][0]["quarantined"] is False
    assert upgraded["items"][0]["quarantined_at"] is None
    assert upgraded["items"][0]["terminal"] is False
    assert upgraded["items"][0]["terminal_reason"] is None


def test_schema_v2_backlog_loads_without_terminal_state_and_upgrades(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = _item().to_json_dict()
    row.pop("terminal")
    row.pop("terminal_reason")
    path.write_text(
        json.dumps({"schema_version": 2, "items": [row]}),
        encoding="utf-8",
    )

    [loaded] = list_agent_publications("proj")
    assert not loaded.terminal
    assert loaded.terminal_reason is None

    update_agent_publications("proj", (loaded.logical_key,), error="still pending")
    upgraded = json.loads(path.read_text(encoding="utf-8"))
    assert upgraded["schema_version"] == PUBLICATION_OUTBOX_SCHEMA_VERSION
    assert upgraded["items"][0]["terminal"] is False
    assert upgraded["items"][0]["terminal_reason"] is None


def test_lock_free_snapshot_reads_schema_v1_without_writing(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = _item().to_json_dict()
    row.pop("quarantined")
    row.pop("quarantined_at")
    row.pop("terminal")
    row.pop("terminal_reason")
    payload = json.dumps({"schema_version": 1, "items": [row]})
    path.write_text(payload, encoding="utf-8")

    [loaded] = snapshot_agent_publications_from_path(path, "proj")

    assert loaded.logical_key == _item().logical_key
    assert loaded.attempts == 0
    assert loaded.quarantined is False
    assert path.read_text(encoding="utf-8") == payload
    assert not path.with_suffix(".json.lock").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attempts", True),
        ("attempts", "3"),
        ("attempts", -1),
        ("quarantined", 1),
        ("quarantined", "false"),
    ],
)
def test_typed_snapshot_rejects_malformed_consumed_fields(
    tmp_path,
    monkeypatch,
    field,
    value,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = _item().to_json_dict()
    row[field] = value
    path.write_text(
        json.dumps({"schema_version": 2, "items": [row]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match=field):
        snapshot_agent_publications_from_path(path, "proj")


def test_schema_v2_snapshot_requires_quarantine_state(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = _item().to_json_dict()
    row.pop("quarantined")
    path.write_text(
        json.dumps({"schema_version": 2, "items": [row]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="quarantined"):
        snapshot_agent_publications_from_path(path, "proj")


def _typed_requests() -> tuple[AgentPublicationOutboxItem, ...]:
    return (
        _item(),
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            kind="bead_pages",
            bead_id="proj-ab.2",
            lineage_root="proj-ab",
            primary_revision="b" * 40,
        ),
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            kind="plan_header",
            plan_ref="plans:202608/example.md",
            primary_revision="c" * 40,
            commit_message=("feat: example\n\nSASE_PLAN: plans:202608/example.md"),
        ),
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            kind="sidecar_push",
            sidecar_kind="beads",
        ),
    )


def _enqueue_typed_request(
    request: AgentPublicationOutboxItem,
) -> AgentPublicationOutboxItem:
    if request.kind == "agent_hood":
        return enqueue_agent_publication(request)
    if request.kind == "bead_pages":
        return enqueue_bead_pages_publication(
            project_key=request.project_key,
            project=request.project,
            bead_id=request.bead_id,
            primary_revision=request.primary_revision,
        )
    if request.kind == "plan_header":
        return enqueue_plan_header_publication(
            project_key=request.project_key,
            project=request.project,
            plan_ref=request.plan_ref,
            primary_revision=request.primary_revision,
            commit_message=request.commit_message,
        )
    return enqueue_sidecar_push_publication(
        project_key=request.project_key,
        project=request.project,
        sidecar_kind=request.sidecar_kind,
    )


@pytest.mark.parametrize(
    "publication_request",
    _typed_requests(),
    ids=lambda item: item.kind,
)
def test_every_publication_kind_round_trips_and_preserves_retry_lifecycle(
    tmp_path,
    monkeypatch,
    publication_request,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    first = _enqueue_typed_request(publication_request)
    repeated = _enqueue_typed_request(publication_request)

    assert repeated.logical_key == first.logical_key
    assert list_agent_publications("proj") == (repeated,)

    failed = update_agent_publications(
        "proj",
        (publication_request.logical_key,),
        error="temporary failure",
        increment_attempts=True,
        quarantine_threshold=2,
    )[0]
    assert failed.attempts == 1
    assert not failed.quarantined

    quarantined = update_agent_publications(
        "proj",
        (publication_request.logical_key,),
        error="temporary failure",
        increment_attempts=True,
        quarantine_threshold=2,
    )[0]
    assert quarantined.quarantined
    assert list_agent_publications("proj", include_quarantined=False) == ()

    clear_quarantined_agent_publications("proj")
    terminal_error = "permanently invalid"
    update_agent_publications(
        "proj",
        (publication_request.logical_key,),
        error=terminal_error,
        increment_attempts=True,
        terminal_reason=terminal_error,
    )
    retired = update_agent_publications(
        "proj",
        (publication_request.logical_key,),
        error=terminal_error,
        increment_attempts=True,
        terminal_reason=terminal_error,
    )[0]
    assert retired.terminal

    assert drop_terminal_agent_publications("proj") == (retired,)
    assert list_agent_publications("proj") == ()

    _enqueue_typed_request(publication_request)
    assert (
        acknowledge_agent_publications(
            "proj",
            (publication_request.logical_key,),
        )
        == ()
    )


def test_schema_v3_agent_request_loads_as_agent_hood_with_same_logical_key(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    row = _item().to_json_dict()
    row.pop("kind")
    row.pop("rank")
    path.write_text(
        json.dumps({"schema_version": 3, "items": [row]}),
        encoding="utf-8",
    )

    [loaded] = list_agent_publications("proj")

    assert loaded.kind == "agent_hood"
    assert loaded.logical_key == _item().logical_key


def test_queue_orders_requests_by_explicit_dependency_rank(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    for request in reversed(_typed_requests()):
        _enqueue_typed_request(request)

    queued = list_agent_publications("proj")

    assert [item.kind for item in queued] == [
        "agent_hood",
        "bead_pages",
        "plan_header",
        "sidecar_push",
    ]
    assert [item.ordering_rank for item in queued] == [0, 1, 2, 3]


def test_two_processes_enqueue_without_lost_or_duplicate_requests(
    tmp_path,
    monkeypatch,
) -> None:
    state_path = str(tmp_path / "state")
    context = multiprocessing.get_context("fork")
    processes = tuple(
        context.Process(target=_concurrent_enqueue, args=(state_path, index))
        for index in range(2)
    )
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    monkeypatch.setenv("SASE_HOME", state_path)
    queued = list_agent_publications("proj")
    assert len(queued) == 3
    assert len({item.logical_key for item in queued}) == 3

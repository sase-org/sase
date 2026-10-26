"""Bounded-retry outbox tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.models import TargetSelection
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    acknowledge_agent_publications,
    enqueue_agent_publication,
    list_agent_publications,
    update_agent_publications,
)
from sase.agents_sync.publication_outbox_store import mutate_publication_outbox
from sase.core.agent_identity_facade import AgentOwnerIdentity

from tests.agents_sync.git_sync_fixtures import target
from tests.agents_sync.test_git_sync_outbox._helpers import retire_publication


def test_bounded_retry_replays_failed_push_then_drains_two_batches_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync._commit_publication_types import CommitPublicationOutcome

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    first = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="first",
            global_agent="alice.athena.first",
            primary_revision="a" * 40,
            local_hood="first",
        )
    )
    second = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="second",
            global_agent="alice.athena.second",
            primary_revision="b" * 40,
            local_hood="second",
        )
    )
    retire_publication(first)
    retire_publication(second, "second hood mismatch")

    def set_order(items):
        return tuple(
            replace(
                item,
                created_at=1.0 if item.logical_key == first.logical_key else 2.0,
            )
            for item in items
        )

    mutate_publication_outbox("proj", set_order)
    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((sync_target,), ()),
    )
    monkeypatch.setattr(
        git_sync,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )
    drained_batches: list[tuple[tuple[str, str], ...]] = []

    def drain(project_key: str, selected_keys: tuple[tuple[str, str], ...]):
        drained_batches.append(selected_keys)
        if len(drained_batches) == 1:
            return CommitPublicationOutcome(error="git push failed")
        acknowledge_agent_publications(project_key, selected_keys)
        return CommitPublicationOutcome(published=True, drained=len(selected_keys))

    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.drain_selected_agent_publications",
        drain,
    )

    [failed] = git_sync.sync_agents(
        ("proj",),
        retry_quarantined=True,
        retry_retired=True,
        retry_limit=1,
    )
    [replayed] = git_sync.sync_agents(
        ("proj",),
        retry_quarantined=True,
        retry_retired=True,
        retry_limit=1,
    )
    [next_batch] = git_sync.sync_agents(
        ("proj",),
        retry_quarantined=True,
        retry_retired=True,
        retry_limit=1,
    )
    [no_op] = git_sync.sync_agents(
        ("proj",),
        retry_quarantined=True,
        retry_retired=True,
        retry_limit=1,
    )

    assert failed.error == "git push failed"
    assert "revived retired" in failed.diagnostics[0]
    assert "legacy mismatch" in failed.diagnostics[0]
    assert (
        "selected=1 resumed=0 revived=1 completed=0 remaining=2"
        in failed.diagnostics[-1]
    )
    assert replayed.error is None
    assert (
        "selected=1 resumed=1 revived=0 completed=1 remaining=1"
        in replayed.diagnostics[-1]
    )
    assert next_batch.error is None
    assert (
        "selected=1 resumed=0 revived=1 completed=1 remaining=0"
        in next_batch.diagnostics[-1]
    )
    assert "no-op" in no_op.diagnostics[0]
    assert drained_batches == [
        (first.logical_key,),
        (first.logical_key,),
        (second.logical_key,),
    ]
    assert list_agent_publications("proj") == ()


def test_bounded_retry_leaves_referenced_by_queue_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
    from sase.agents_sync.referenced_by_outbox import (
        ReferencedByOutboxItem,
        enqueue_referenced_by_request,
        list_referenced_by_requests,
        update_referenced_by_requests,
    )

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    hood = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="worker",
            global_agent="alice.athena.worker",
            primary_revision="a" * 40,
            local_hood="worker",
        )
    )
    update_agent_publications(
        "proj",
        (hood.logical_key,),
        error="agents sync lock is busy",
        increment_attempts=True,
        quarantine_threshold=1,
    )
    referenced = enqueue_referenced_by_request(
        ReferencedByOutboxItem(
            project_key="proj",
            project="Project",
            global_agent="alice.athena.worker",
            agent_url="https://example.test/agents/worker",
            primary_revision="a" * 40,
            sidecar_role="plans",
            provider="plan",
            artifact_id="plan:202608/example.md",
            repo_relpath="202608/example.md",
            identity_value=None,
            canonical_ref="plan:202608/example.md",
            destination="https://example.test/prompts/1",
            uses=1,
            published_date="2026-08-12",
        )
    )
    update_referenced_by_requests(
        "proj",
        (referenced.logical_key,),
        error="write-back failed",
        increment_attempts=True,
        quarantine_threshold=1,
    )
    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((sync_target,), ()),
    )
    monkeypatch.setattr(
        git_sync,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )

    def acknowledge_selected(project_key, selected_keys):
        acknowledge_agent_publications(project_key, selected_keys)
        return CommitPublicationOutcome(published=True, drained=len(selected_keys))

    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.drain_selected_agent_publications",
        acknowledge_selected,
    )

    [outcome] = git_sync.sync_agents(
        ("proj",),
        retry_quarantined=True,
        retry_limit=1,
    )

    assert outcome.error is None
    assert list_agent_publications("proj") == ()
    [still_queued] = list_referenced_by_requests("proj")
    assert still_queued.logical_key == referenced.logical_key
    assert still_queued.quarantined
    assert still_queued.last_error == "write-back failed"


def test_bounded_retry_exact_key_selects_timeout_and_preserves_unrelated_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
    from sase.agents_sync.referenced_by_outbox import (
        ReferencedByOutboxItem,
        enqueue_referenced_by_request,
        list_referenced_by_requests,
        update_referenced_by_requests,
    )

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    active = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="active",
            global_agent="alice.athena.active",
            primary_revision="a" * 40,
            local_hood="active",
        )
    )
    timeout = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="timeout",
            global_agent="alice.athena.timeout",
            primary_revision="c" * 40,
            local_hood="timeout",
        )
    )
    quarantined = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="lock",
            global_agent="alice.athena.lock",
            primary_revision="d" * 40,
            local_hood="lock",
        )
    )
    retired = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="retired",
            global_agent="alice.athena.retired",
            primary_revision="e" * 40,
            local_hood="retired",
        )
    )
    update_agent_publications(
        "proj",
        (timeout.logical_key,),
        error="agent-hood publication did not complete within 120s",
        increment_attempts=True,
        quarantine_threshold=1,
    )
    update_agent_publications(
        "proj",
        (quarantined.logical_key,),
        error="agents sync lock is busy",
        increment_attempts=True,
        quarantine_threshold=1,
    )
    retire_publication(retired)
    referenced = enqueue_referenced_by_request(
        ReferencedByOutboxItem(
            project_key="proj",
            project="Project",
            global_agent="alice.athena.timeout",
            agent_url="https://example.test/agents/timeout",
            primary_revision="c" * 40,
            sidecar_role="plans",
            provider="plan",
            artifact_id="plan:202608/example.md",
            repo_relpath="202608/example.md",
            identity_value=None,
            canonical_ref="plan:202608/example.md",
            destination="https://example.test/prompts/1",
            uses=1,
            published_date="2026-08-12",
        )
    )
    update_referenced_by_requests(
        "proj",
        (referenced.logical_key,),
        error="write-back failed",
        increment_attempts=True,
        quarantine_threshold=1,
    )
    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((sync_target,), ()),
    )
    monkeypatch.setattr(
        git_sync,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )
    drained_batches: list[tuple[tuple[str, str], ...]] = []

    def acknowledge_selected(project_key, selected_keys):
        drained_batches.append(selected_keys)
        acknowledge_agent_publications(project_key, selected_keys)
        return CommitPublicationOutcome(published=True, drained=len(selected_keys))

    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.drain_selected_agent_publications",
        acknowledge_selected,
    )

    [hit] = git_sync.sync_agents(
        ("proj",),
        retry_quarantined=True,
        retry_retired=True,
        retry_limit=1,
        retry_error_classes=("timeout",),
        retry_key=timeout.logical_key,
    )
    [miss] = git_sync.sync_agents(
        ("proj",),
        retry_quarantined=True,
        retry_retired=True,
        retry_limit=1,
        retry_error_classes=("timeout",),
        retry_key=("alice.athena.gone", "b" * 40),
    )

    formatted = f"{timeout.global_agent}@{timeout.primary_revision}"
    assert hit.error is None
    assert any(f"key={formatted}" in line for line in hit.diagnostics)
    assert drained_batches == [(timeout.logical_key,)]
    remaining = {item.logical_key: item for item in list_agent_publications("proj")}
    assert timeout.logical_key not in remaining
    assert remaining[active.logical_key].attempts == 0
    assert remaining[quarantined.logical_key].quarantined
    assert remaining[retired.logical_key].terminal
    [still_referenced] = list_referenced_by_requests("proj")
    assert still_referenced.logical_key == referenced.logical_key
    assert still_referenced.quarantined
    assert miss.error is None
    assert (
        "no matching publication request alice.athena.gone@" + "b" * 40
        in miss.diagnostics[0]
    )
    assert drained_batches == [(timeout.logical_key,)]
    assert {item.logical_key for item in list_agent_publications("proj")} == set(
        remaining
    )

"""Tests for the Rust-backed publication recovery policy facade."""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_completion import (
    _publication_request_completion,
    snapshot_prompt_file_present,
)
from sase.agents_sync.publication_outbox_models import AgentPublicationOutboxItem
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.agent_publication_recovery import (
    PROMPT_STATUS_ALREADY_ARCHIVED,
    PROMPT_STATUS_NOT_APPLICABLE,
    PROMPT_STATUS_UNAVAILABLE,
    PUBLICATION_ERROR_LOCK_BUSY,
    PUBLICATION_ERROR_TIMEOUT,
    PUBLICATION_FAILURE_SCOPE_HOOD,
    PUBLICATION_FAILURE_SCOPE_REPOSITORY,
    PUBLICATION_KIND_RUN,
    PUBLICATION_KIND_SESSION,
    PUBLICATION_LIFECYCLE_ACTIVE,
    PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
    classify_deferred_prompt_obligation,
    classify_publication_error,
    decide_publication_failure_accounting,
    decide_publication_request_completion,
    select_publication_drain,
    select_publication_retries,
)
from tests.agents_sync.git_sync_fixtures import plant_fulfilled_publication


def test_select_publication_retries_revives_only_requested_classes() -> None:
    selected = select_publication_retries(
        (
            {
                "global_agent": "alice.athena.foo",
                "primary_revision": "a" * 40,
                "terminal": True,
                "quarantined": False,
                "last_error": "legacy mismatch",
                "terminal_reason": "legacy mismatch",
            },
            {
                "global_agent": "alice.athena.bar",
                "primary_revision": "b" * 40,
                "terminal": False,
                "quarantined": True,
                "last_error": "push rejected",
                "terminal_reason": None,
            },
            {
                "global_agent": "alice.athena.live",
                "primary_revision": "c" * 40,
                "terminal": False,
                "quarantined": False,
                "last_error": None,
                "terminal_reason": None,
            },
        ),
        retry_retired=True,
        retry_quarantined=False,
    )

    assert len(selected) == 1
    assert selected[0].global_agent == "alice.athena.foo"
    assert selected[0].prior_class == "retired"
    assert selected[0].prior_failure == "legacy mismatch"
    assert selected[0].error_class == "other"


def test_select_publication_retries_applies_limit_after_error_class_filter() -> None:
    selected = select_publication_retries(
        (
            {
                "global_agent": "alice.athena.timeout",
                "primary_revision": "a" * 40,
                "terminal": False,
                "quarantined": True,
                "last_error": "agent-hood publication did not complete within 120s",
                "created_at": 2.0,
            },
            {
                "global_agent": "alice.athena.other",
                "primary_revision": "b" * 40,
                "terminal": True,
                "quarantined": False,
                "last_error": "legacy mismatch",
                "terminal_reason": "legacy mismatch",
                "created_at": 1.0,
            },
            {
                "global_agent": "alice.athena.lock",
                "primary_revision": "c" * 40,
                "terminal": False,
                "quarantined": True,
                "last_error": "agents sync lock is busy",
                "created_at": 3.0,
            },
        ),
        retry_retired=True,
        retry_quarantined=True,
        limit=1,
        error_classes=(PUBLICATION_ERROR_TIMEOUT, PUBLICATION_ERROR_LOCK_BUSY),
    )
    assert len(selected) == 1
    assert selected[0].global_agent == "alice.athena.timeout"
    assert selected[0].error_class == PUBLICATION_ERROR_TIMEOUT


def test_classify_publication_error_covers_uncommitted_index_changes() -> None:
    assert classify_publication_error(None) == "unknown"
    assert (
        classify_publication_error("error: Your index contains uncommitted changes.")
        == "unstaged_changes"
    )
    assert (
        classify_publication_error("could not stage: .git/index.lock exists")
        == "index_lock"
    )


def test_repository_scope_does_not_charge_attempted_keys() -> None:
    decision = decide_publication_failure_accounting(
        scope=PUBLICATION_FAILURE_SCOPE_REPOSITORY,
        error="agents sync lock is busy",
        attempted_keys=(("alice.athena.foo", "a" * 40),),
        rows=(
            {
                "global_agent": "alice.athena.foo",
                "primary_revision": "a" * 40,
                "attempts": 2,
                "last_error": "prior",
            },
        ),
        quarantine_threshold=3,
    )
    assert decision.scope == PUBLICATION_FAILURE_SCOPE_REPOSITORY
    assert not decision.charge
    assert decision.charges == ()
    assert decision.error_class == PUBLICATION_ERROR_LOCK_BUSY


def test_hood_scope_charges_only_supplied_keys() -> None:
    error = "hood 'foo' has no publishable runs"
    decision = decide_publication_failure_accounting(
        scope=PUBLICATION_FAILURE_SCOPE_HOOD,
        error=error,
        format_error=True,
        attempted_keys=(("alice.athena.foo", "a" * 40),),
        rows=(
            {
                "global_agent": "alice.athena.foo",
                "primary_revision": "a" * 40,
                "attempts": 1,
                "last_error": error,
            },
            {
                "global_agent": "alice.athena.other",
                "primary_revision": "b" * 40,
                "attempts": 2,
                "last_error": error,
            },
        ),
        quarantine_threshold=3,
    )
    assert decision.charge
    assert len(decision.charges) == 1
    assert decision.charges[0].retire
    assert not decision.charges[0].quarantine
    assert decision.charges[0].attempts == 2


def test_select_publication_drain_prefers_new_then_active_then_stopped() -> None:
    selected = select_publication_drain(
        (
            {
                "global_agent": "alice.athena.old",
                "primary_revision": "a" * 40,
                "terminal": False,
                "quarantined": False,
                "last_error": None,
                "created_at": 1.0,
            },
            {
                "global_agent": "alice.athena.new",
                "primary_revision": "b" * 40,
                "terminal": False,
                "quarantined": False,
                "last_error": None,
                "created_at": 5.0,
            },
            {
                "global_agent": "alice.athena.retired",
                "primary_revision": "c" * 40,
                "terminal": True,
                "quarantined": False,
                "last_error": "legacy mismatch",
                "terminal_reason": "legacy mismatch",
                "created_at": 0.5,
            },
        ),
        limit=2,
        preferred_key=("alice.athena.new", "b" * 40),
        retry_retired=True,
        retry_quarantined=True,
    )
    assert [item.global_agent for item in selected.active] == [
        "alice.athena.new",
        "alice.athena.old",
    ]
    assert selected.revive == ()
    assert selected.active[0].prior_class == PUBLICATION_LIFECYCLE_ACTIVE


def test_select_publication_drain_no_match_is_empty() -> None:
    selected = select_publication_drain(
        (
            {
                "global_agent": "alice.athena.bar",
                "primary_revision": "b" * 40,
                "terminal": False,
                "quarantined": True,
                "last_error": "push rejected",
            },
        ),
        limit=25,
        retry_retired=True,
        error_classes=(PUBLICATION_ERROR_TIMEOUT,),
    )
    assert selected.active == ()
    assert selected.revive == ()


def test_completion_requires_session_page_and_revision() -> None:
    revision = "a" * 40
    decision = decide_publication_request_completion(
        global_agent="alice.athena.foo.bar",
        local_agent="foo.bar",
        primary_revision=revision,
        pages=(
            {"path": "agents/alice.athena.foo.bar/README.md", "exists": True},
            {"path": "sessions/alice.athena.foo.bar.md", "exists": True},
        ),
        runs=(
            {
                "global_name": "alice.athena.foo.bar--code",
                "local_name": "foo.bar--code",
                "commit_shas": [revision],
                "has_prompt_file": True,
            },
        ),
        containers=(
            {
                "kind": "family",
                "global_name": "alice.athena.foo.bar",
                "member_global_names": ["alice.athena.foo.bar--code"],
                "commit_shas": [],
            },
        ),
    )
    assert decision.schema_version == PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION
    assert decision.kind == PUBLICATION_KIND_SESSION
    assert decision.required_page == "sessions/alice.athena.foo.bar.md"
    assert decision.fulfilled


def test_completion_rejects_preexisting_run_page_without_revision() -> None:
    decision = decide_publication_request_completion(
        global_agent="alice.athena.foo",
        local_agent="foo",
        primary_revision="a" * 40,
        pages=({"path": "agents/alice.athena.foo/README.md", "exists": True},),
        runs=(
            {
                "global_name": "alice.athena.foo",
                "local_name": "foo",
                "commit_shas": ["b" * 40],
                "has_prompt_file": False,
            },
        ),
    )
    assert decision.kind == PUBLICATION_KIND_RUN
    assert not decision.fulfilled
    assert "primary revision" in decision.reason


def test_deferred_prompt_missing_source_is_unavailable_without_evidence() -> None:
    unavailable = classify_deferred_prompt_obligation(
        restore_wrote=False,
        restore_error=None,
        local_source_present=False,
        archive_present=False,
        prompt_file_in_snapshot=None,
    )
    assert unavailable.status == PROMPT_STATUS_UNAVAILABLE
    assert unavailable.blocks_acknowledgment

    archived = classify_deferred_prompt_obligation(
        restore_wrote=False,
        restore_error=None,
        local_source_present=False,
        archive_present=True,
        prompt_file_in_snapshot=True,
    )
    assert archived.status == PROMPT_STATUS_ALREADY_ARCHIVED
    assert not archived.blocks_acknowledgment

    not_applicable = classify_deferred_prompt_obligation(
        restore_wrote=False,
        restore_error=None,
        local_source_present=False,
        archive_present=False,
        prompt_file_in_snapshot=False,
    )
    assert not_applicable.status == PROMPT_STATUS_NOT_APPLICABLE
    assert not not_applicable.blocks_acknowledgment


def test_python_completion_helper_reads_snapshot_and_pages(tmp_path: Path) -> None:
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    plant_fulfilled_publication(sidecar)
    target = ProjectTarget(
        "proj",
        "Project",
        tmp_path / "primary",
        (tmp_path / "primary",),
        sidecar,
        "unused",
    )
    item = AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent="foo",
        global_agent="alice.athena.foo",
        primary_revision="a" * 40,
        local_hood="foo",
    )
    owner = AgentOwnerIdentity("alice", "athena")

    decision = _publication_request_completion(target, item, owner)
    assert decision.fulfilled
    assert decision.kind == PUBLICATION_KIND_RUN
    assert snapshot_prompt_file_present(target, item, owner) is False

    plant_fulfilled_publication(sidecar, has_prompt_file=True)
    assert snapshot_prompt_file_present(target, item, owner) is True

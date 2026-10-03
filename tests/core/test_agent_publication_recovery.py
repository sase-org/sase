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
    PUBLICATION_KIND_RUN,
    PUBLICATION_KIND_SESSION,
    PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
    classify_deferred_prompt_obligation,
    decide_publication_request_completion,
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

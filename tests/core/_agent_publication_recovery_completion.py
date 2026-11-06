"""Completion and deferred-prompt tests for publication recovery."""

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
    PUBLICATION_SCOPE_LINKED,
    classify_deferred_prompt_obligation,
    decide_publication_request_completion,
)
from tests.agents_sync.git_sync_fixtures import plant_fulfilled_publication


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


def test_linked_scope_fulfills_when_the_required_page_exists_without_revision() -> None:
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
        scope=PUBLICATION_SCOPE_LINKED,
    )
    assert decision.kind == PUBLICATION_KIND_RUN
    assert decision.fulfilled
    assert "linked-scope" in decision.reason


def test_linked_scope_session_fulfills_without_run_commits() -> None:
    decision = decide_publication_request_completion(
        global_agent="alice.athena.foo.bar",
        local_agent="foo.bar",
        primary_revision="a" * 40,
        pages=(
            {"path": "agents/alice.athena.foo.bar/README.md", "exists": False},
            {"path": "sessions/alice.athena.foo.bar.md", "exists": True},
        ),
        runs=(
            {
                "global_name": "alice.athena.foo.bar--plan",
                "local_name": "foo.bar--plan",
                "commit_shas": [],
                "has_prompt_file": True,
            },
        ),
        containers=(
            {
                "kind": "session",
                "global_name": "alice.athena.foo.bar",
                "member_global_names": ["alice.athena.foo.bar--plan"],
                "commit_shas": [],
            },
        ),
        scope=PUBLICATION_SCOPE_LINKED,
    )
    assert decision.kind == PUBLICATION_KIND_SESSION
    assert decision.fulfilled
    assert "linked-scope" in decision.reason


def test_linked_scope_session_fulfills_when_descendant_sha_is_present() -> None:
    planner_head = "a" * 40
    coder_sha = "b" * 40
    decision = decide_publication_request_completion(
        global_agent="alice.athena.foo.bar",
        local_agent="foo.bar",
        primary_revision=planner_head,
        pages=(
            {"path": "agents/alice.athena.foo.bar/README.md", "exists": False},
            {"path": "sessions/alice.athena.foo.bar.md", "exists": True},
        ),
        runs=(
            {
                "global_name": "alice.athena.foo.bar--code",
                "local_name": "foo.bar--code",
                "commit_shas": [coder_sha],
                "has_prompt_file": True,
            },
        ),
        containers=(
            {
                "kind": "session",
                "global_name": "alice.athena.foo.bar",
                "member_global_names": ["alice.athena.foo.bar--code"],
                "commit_shas": [coder_sha],
            },
        ),
        scope=PUBLICATION_SCOPE_LINKED,
    )
    assert decision.fulfilled
    refused = decide_publication_request_completion(
        global_agent="alice.athena.foo.bar",
        local_agent="foo.bar",
        primary_revision=planner_head,
        pages=(
            {"path": "agents/alice.athena.foo.bar/README.md", "exists": False},
            {"path": "sessions/alice.athena.foo.bar.md", "exists": True},
        ),
        runs=(
            {
                "global_name": "alice.athena.foo.bar--code",
                "local_name": "foo.bar--code",
                "commit_shas": [coder_sha],
                "has_prompt_file": True,
            },
        ),
        containers=(
            {
                "kind": "session",
                "global_name": "alice.athena.foo.bar",
                "member_global_names": ["alice.athena.foo.bar--code"],
                "commit_shas": [coder_sha],
            },
        ),
    )
    assert not refused.fulfilled
    assert "primary revision" in refused.reason


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

    linked_item = AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent="foo",
        global_agent="alice.athena.foo",
        primary_revision="c" * 40,
        local_hood="foo",
        scope=PUBLICATION_SCOPE_LINKED,
    )
    linked = _publication_request_completion(target, linked_item, owner)
    assert linked.fulfilled
    assert "linked-scope" in linked.reason
    assert snapshot_prompt_file_present(target, item, owner) is False

    plant_fulfilled_publication(sidecar, has_prompt_file=True)
    assert snapshot_prompt_file_present(target, item, owner) is True

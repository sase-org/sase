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
    PUBLICATION_SCOPE_LINKED,
    REPLAY_APPLY_ACTION_APPLY,
    REPLAY_APPLY_ACTION_REFUSE,
    REPLAY_APPLY_ACTION_REPORT,
    REPLAY_BYTES_KEEP_CURRENT,
    REPLAY_BYTES_KEEP_PREVIOUS,
    REPLAY_BYTES_REFUSE,
    REPLAY_HOOD_ACTION_MERGE,
    REPLAY_PATH_ARCHIVE_OBJECT,
    REPLAY_PATH_BROWSING,
    REPLAY_PATH_OWNER_CONTENT,
    classify_deferred_prompt_obligation,
    classify_publication_error,
    classify_replay_paths,
    classify_stale_publication_request,
    decide_publication_failure_accounting,
    decide_publication_request_completion,
    decide_replay_apply,
    decide_replay_byte_divergence,
    decide_replay_hood_merge,
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


def test_select_publication_drain_exact_key_ignores_unrelated_active_rows() -> None:
    target_revision = "c" * 40
    selected = select_publication_drain(
        (
            {
                "global_agent": "alice.athena.active",
                "primary_revision": "a" * 40,
                "terminal": False,
                "quarantined": False,
                "last_error": "agents sync lock is busy",
                "created_at": 2.0,
            },
            {
                "global_agent": "alice.athena.target",
                "primary_revision": target_revision,
                "terminal": False,
                "quarantined": True,
                "last_error": "agent-hood publication did not complete within 120s",
                "created_at": 1.0,
            },
        ),
        limit=2,
        exact_key=("alice.athena.target", target_revision),
        retry_quarantined=True,
        error_classes=(PUBLICATION_ERROR_TIMEOUT,),
    )
    assert [item.global_agent for item in selected.revive] == ["alice.athena.target"]
    assert selected.active == ()


def test_select_publication_drain_missing_exact_key_is_empty() -> None:
    selected = select_publication_drain(
        (
            {
                "global_agent": "alice.athena.active",
                "primary_revision": "a" * 40,
                "terminal": False,
                "quarantined": False,
                "last_error": None,
                "created_at": 1.0,
            },
        ),
        limit=1,
        exact_key=("alice.athena.gone", "b" * 40),
        retry_quarantined=True,
        retry_retired=True,
    )
    assert selected.active == ()
    assert selected.revive == ()


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


def test_stale_repair_classifies_parent_rebased_linked_and_unknown() -> None:
    repaired = classify_stale_publication_request(
        requested_revision="a" * 40,
        scope="revision",
        run_commit_shas=["b" * 40, "c" * 40],
        ancestor_commit_shas=["c" * 40],
    )
    assert repaired.action == "repaired"
    assert repaired.fulfilling_revision == "c" * 40
    assert repaired.evidence_commit == "c" * 40

    assert (
        classify_stale_publication_request(
            requested_revision="b" * 40,
            scope="revision",
            run_commit_shas=["b" * 40],
        ).action
        == "unchanged"
    )
    assert (
        classify_stale_publication_request(
            requested_revision="c" * 40,
            scope="linked",
        ).action
        == "unchanged"
    )
    assert (
        classify_stale_publication_request(
            requested_revision="c" * 40,
            scope="revision",
            run_commit_shas=["b" * 40],
            linked_revision=True,
        ).action
        == "linked"
    )
    unknown = classify_stale_publication_request(
        requested_revision="d" * 40,
        scope="revision",
        run_commit_shas=["b" * 40],
    )
    assert unknown.action == "unresolved"
    assert unknown.fulfilling_revision is None


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


def test_classify_replay_paths_separates_browsing_owner_and_objects() -> None:
    classified = classify_replay_paths(
        (
            "README.md",
            "agents/alice.athena.foo/chat.md",
            "files/objects/sha256/ab/abc",
            "mystery.bin",
        )
    )

    assert classified.schema_version == PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION
    assert classified.browsing == ("README.md",)
    assert classified.owner_content == ("agents/alice.athena.foo/chat.md",)
    assert classified.archive_object == ("files/objects/sha256/ab/abc",)
    assert classified.unknown == ("mystery.bin",)
    assert dict(classified.entries)["README.md"] == REPLAY_PATH_BROWSING
    assert dict(classified.entries)["agents/alice.athena.foo/chat.md"] == (
        REPLAY_PATH_OWNER_CONTENT
    )
    assert dict(classified.entries)["files/objects/sha256/ab/abc"] == (
        REPLAY_PATH_ARCHIVE_OBJECT
    )


def test_replay_byte_divergence_uses_merge_base_before_prefix_rules() -> None:
    keep = decide_replay_byte_divergence(b"hello world", b"hello")
    assert keep.action == REPLAY_BYTES_KEEP_CURRENT
    assert keep.retained

    refuse = decide_replay_byte_divergence(b"aaaaaaaaaa", b"bbbb")
    assert refuse.action == REPLAY_BYTES_REFUSE
    assert not refuse.retained

    local_change = decide_replay_byte_divergence(
        b"local\r\nchange", b"base\r\n", b"base\r\n"
    )
    assert local_change.action == REPLAY_BYTES_KEEP_CURRENT

    upstream_change = decide_replay_byte_divergence(
        b"base\r\n", b"upstream\r\nchange", b"base\r\n"
    )
    assert upstream_change.action == REPLAY_BYTES_KEEP_PREVIOUS


def test_replay_apply_admits_verified_backup_and_refuses_head_drift() -> None:
    head = "d7e06b77b42d89ecf4bb1538c6f89c6fe700124e"
    merge = decide_replay_hood_merge(
        local_owner_username="alice",
        local_owner_machine="athena",
        local_hood="foo",
        upstream_owner_username="alice",
        upstream_owner_machine="athena",
        upstream_hood="foo",
    )
    assert merge.action == REPLAY_HOOD_ACTION_MERGE

    report = decide_replay_apply(
        apply=False,
        observed_head=head,
        expected_head=head,
        backup_complete=False,
        backup_verified=False,
        unreconcilable=False,
        already_complete=False,
        mutation_started=False,
    )
    assert report.action == REPLAY_APPLY_ACTION_REPORT

    admitted = decide_replay_apply(
        apply=True,
        observed_head=head,
        expected_head=head,
        backup_complete=True,
        backup_verified=True,
        unreconcilable=False,
        already_complete=False,
        mutation_started=False,
    )
    assert admitted.action == REPLAY_APPLY_ACTION_APPLY

    drifted = decide_replay_apply(
        apply=True,
        observed_head="a" * 40,
        expected_head=head,
        backup_complete=True,
        backup_verified=True,
        unreconcilable=False,
        already_complete=False,
        mutation_started=False,
    )
    assert drifted.action == REPLAY_APPLY_ACTION_REFUSE

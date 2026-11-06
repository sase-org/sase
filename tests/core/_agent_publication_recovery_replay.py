"""Replay classification and apply policy tests for publication recovery."""

from __future__ import annotations

from sase.core.agent_publication_recovery import (
    PUBLICATION_REBASE_ACTION_ESCALATE,
    PUBLICATION_REBASE_ACTION_RESOLVE_UPSTREAM,
    PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
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
    classify_replay_paths,
    decide_publication_rebase_conflict,
    decide_replay_apply,
    decide_replay_byte_divergence,
    decide_replay_hood_merge,
)


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


def test_publication_rebase_conflict_resolves_apollo_index_pages() -> None:
    decision = decide_publication_rebase_conflict(
        ["README.md", "users/bbugyi200/README.md"]
    )

    assert decision.schema_version == PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION
    assert decision.action == PUBLICATION_REBASE_ACTION_RESOLVE_UPSTREAM
    assert decision.paths == ("README.md", "users/bbugyi200/README.md")
    assert decision.reasons == ()


def test_publication_rebase_conflict_escalates_mixed_owner_content() -> None:
    decision = decide_publication_rebase_conflict(
        ["README.md", "agents/alice.athena.foo/chat.md"]
    )

    assert decision.action == PUBLICATION_REBASE_ACTION_ESCALATE
    assert decision.paths == ("README.md", "agents/alice.athena.foo/chat.md")
    assert len(decision.reasons) == 1
    assert "agents/alice.athena.foo/chat.md" in decision.reasons[0]


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

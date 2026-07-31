"""Tests for folded memory commit-message composition."""

from __future__ import annotations

from sase.main.init_memory.commit_message import (
    _compose_fold_subject,
    _is_conventional_header,
    build_fold_commit_message,
)


def test_is_conventional_header_accepts_allowed_tags() -> None:
    assert _is_conventional_header("docs(memory): document workflow")
    assert _is_conventional_header("deps(memory): bump lockfile")
    assert _is_conventional_header("feat!: breaking memory change")
    assert _is_conventional_header("fix(scope)!: patch memory")


def test_is_conventional_header_rejects_unknown_or_malformed_tags() -> None:
    assert not _is_conventional_header("wip(memory): document workflow")
    assert not _is_conventional_header("docs(memory):document workflow")
    assert not _is_conventional_header("document workflow")


def test_compose_fold_subject_prepends_default_prefix() -> None:
    assert (
        _compose_fold_subject("document obsidian vault workflow")
        == "docs(memory): document obsidian vault workflow"
    )


def test_compose_fold_subject_preserves_conventional_header() -> None:
    assert (
        _compose_fold_subject("feat(memory): add obsidian note")
        == "feat(memory): add obsidian note"
    )


def test_build_fold_commit_message_preserves_memory_footer() -> None:
    assert (
        build_fold_commit_message("document obsidian vault workflow")
        == "docs(memory): document obsidian vault workflow\n\nSASE_TYPE=memory"
    )

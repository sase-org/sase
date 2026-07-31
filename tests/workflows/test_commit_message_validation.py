"""Tests for commit-message policy loading and rejection text."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.core.commit_subject_facade import default_commit_subject_types
from sase.workflows.commit.message_validation import (
    CommitMessagePolicy,
    check_commit_message,
    load_commit_message_policy,
)


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"commit": {}},
        {"commit": {"message": "invalid"}},
        {"commit": {"message": {"allowed_types": "fix"}}},
        {"commit": {"message": {"allowed_types": []}}},
    ],
)
def test_load_commit_message_policy_defaults_for_missing_or_malformed_config(
    config: dict[str, object],
) -> None:
    with patch(
        "sase.workflows.commit.message_validation.load_merged_config",
        return_value=config,
    ):
        policy = load_commit_message_policy()

    assert policy.require_conventional_subject is True
    assert policy.allowed_types == default_commit_subject_types()


def test_load_commit_message_policy_defaults_when_config_loader_fails() -> None:
    with patch(
        "sase.workflows.commit.message_validation.load_merged_config",
        side_effect=RuntimeError("broken config"),
    ):
        policy = load_commit_message_policy()

    assert policy == CommitMessagePolicy()


def test_load_commit_message_policy_honors_explicit_false_and_custom_types() -> None:
    config = {
        "commit": {
            "message": {
                "require_conventional_subject": False,
                "allowed_types": ["Docs", "fix", "docs", " "],
            }
        }
    }
    with patch(
        "sase.workflows.commit.message_validation.load_merged_config",
        return_value=config,
    ):
        policy = load_commit_message_policy()

    assert policy.require_conventional_subject is False
    assert policy.allowed_types == ("docs", "fix")


def test_check_commit_message_returns_none_when_policy_disabled() -> None:
    policy = CommitMessagePolicy(
        require_conventional_subject=False,
        allowed_types=("fix",),
    )

    assert check_commit_message("not conventional", policy) is None


@pytest.mark.parametrize(
    "message",
    [
        "Merge branch 'main'",
        'Revert "fix: regressions"',
        "fixup! fix: adjust tests",
    ],
)
def test_check_commit_message_returns_none_for_exempt_subjects(message: str) -> None:
    assert check_commit_message(message, CommitMessagePolicy()) is None


@pytest.mark.parametrize(
    ("message", "first_line", "subject"),
    [
        ("", "Commit message rejected: the message is empty.", None),
        (
            "Update built-in model aliases for Claude and Codex catalog",
            "Commit message rejected: the subject line is not a Conventional Commit.",
            "subject: Update built-in model aliases for Claude and Codex catalog",
        ),
        (
            "Fix: x",
            'Commit message rejected: the commit type must be lowercase — use "fix:" not "Fix:".',
            "subject: Fix: x",
        ),
        (
            "feet: x",
            'Commit message rejected: "feet" is not an allowed commit type.',
            "subject: feet: x",
        ),
        (
            "fix:",
            "Commit message rejected: the subject has no description after the type.",
            "subject: fix:",
        ),
    ],
)
def test_check_commit_message_renders_actionable_rejections(
    message: str,
    first_line: str,
    subject: str | None,
) -> None:
    rejection = check_commit_message(message, CommitMessagePolicy())

    assert rejection is not None
    assert rejection.splitlines()[0] == first_line
    if subject is None:
        assert "subject:" not in rejection
    else:
        assert subject in rejection
    assert (
        "Allowed types: build, chore, ci, deps, docs, feat, fix, perf, "
        "refactor, revert, style, test"
    ) in rejection
    assert "Expected: <type>[(<scope>)][!]: <description>" in rejection
    assert "Rewrite the subject line and re-run the same command." in rejection
    assert "commit.message.require_conventional_subject" in rejection


def test_check_commit_message_renders_effective_custom_allowed_types() -> None:
    rejection = check_commit_message(
        "feat: x",
        CommitMessagePolicy(allowed_types=("fix", "docs")),
    )

    assert rejection is not None
    assert 'Commit message rejected: "feat" is not an allowed commit type.' in rejection
    assert "Allowed types: docs, fix" in rejection

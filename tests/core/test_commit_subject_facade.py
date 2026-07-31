"""Tests for the typed commit-subject Rust facade."""

from __future__ import annotations

import pytest

from sase.core.commit_subject_facade import (
    default_commit_subject_types,
    parse_commit_subject,
)


def test_default_commit_subject_types_round_trip() -> None:
    assert default_commit_subject_types() == (
        "build",
        "chore",
        "ci",
        "deps",
        "docs",
        "feat",
        "fix",
        "perf",
        "refactor",
        "revert",
        "style",
        "test",
    )


def test_parse_commit_subject_valid_scoped_breaking_message() -> None:
    parsed = parse_commit_subject("feat(cli)!: add subject gate\n\nBody text")

    assert parsed.subject == "feat(cli)!: add subject gate"
    assert parsed.valid is True
    assert parsed.exempt is False
    assert parsed.commit_type == "feat"
    assert parsed.scope == "cli"
    assert parsed.breaking is True
    assert parsed.description == "add subject gate"
    assert parsed.violation is None
    assert parsed.found_type is None


@pytest.mark.parametrize(
    ("message", "violation", "found_type"),
    [
        ("", "empty_subject", None),
        (
            "Update built-in model aliases for Claude and Codex catalog",
            "missing_type_separator",
            None,
        ),
        ("Fix: x", "uppercase_type", "Fix"),
        ("feet: x", "unknown_type", "feet"),
        ("fix:", "empty_description", None),
    ],
)
def test_parse_commit_subject_violation_codes(
    message: str,
    violation: str,
    found_type: str | None,
) -> None:
    parsed = parse_commit_subject(message)

    assert parsed.valid is False
    assert parsed.violation == violation
    assert parsed.found_type == found_type


@pytest.mark.parametrize(
    "message",
    [
        "Merge branch 'main'",
        'Revert "fix: regressions"',
        "fixup! fix: adjust tests",
        "squash! feat: add command",
        "amend! docs: update guide",
    ],
)
def test_parse_commit_subject_exempt_prefixes(message: str) -> None:
    parsed = parse_commit_subject(message)

    assert parsed.valid is True
    assert parsed.exempt is True
    assert parsed.violation is None


def test_parse_commit_subject_custom_allowed_types_replace_defaults() -> None:
    rejected = parse_commit_subject("fix: x", allowed_types=("docs",))
    accepted = parse_commit_subject("docs: x", allowed_types=("docs",))

    assert rejected.valid is False
    assert rejected.violation == "unknown_type"
    assert rejected.found_type == "fix"
    assert accepted.valid is True

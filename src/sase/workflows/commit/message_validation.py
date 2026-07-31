"""Commit-message policy loading and Conventional Commit rejection text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.config.core import load_merged_config
from sase.core.commit_subject_facade import (
    default_commit_subject_types,
    parse_commit_subject,
)

_DEFAULT_REQUIRE_CONVENTIONAL_SUBJECT = True
_GENERIC_REJECTION = (
    "Commit message rejected: the subject line is not a Conventional Commit."
)


@dataclass(frozen=True)
class _CommitMessagePolicy:
    require_conventional_subject: bool = _DEFAULT_REQUIRE_CONVENTIONAL_SUBJECT
    allowed_types: tuple[str, ...] = field(default_factory=default_commit_subject_types)


def load_commit_message_policy() -> _CommitMessagePolicy:
    """Load the commit-message policy from merged config, falling back safely."""
    defaults = _CommitMessagePolicy()
    try:
        config = load_merged_config()
    except Exception:
        return defaults
    if not isinstance(config, dict):
        return defaults

    commit_config = config.get("commit", {})
    if not isinstance(commit_config, dict):
        return defaults
    message_config = commit_config.get("message", {})
    if not isinstance(message_config, dict):
        return defaults

    raw_require = message_config.get(
        "require_conventional_subject",
        defaults.require_conventional_subject,
    )
    return _CommitMessagePolicy(
        require_conventional_subject=(
            raw_require
            if isinstance(raw_require, bool)
            else defaults.require_conventional_subject
        ),
        allowed_types=_normalize_allowed_types(
            message_config.get("allowed_types"),
            defaults.allowed_types,
        ),
    )


def check_commit_message(
    message: str,
    policy: _CommitMessagePolicy,
) -> str | None:
    """Return a rendered rejection message, or ``None`` when acceptable."""
    if not policy.require_conventional_subject:
        return None
    parsed = parse_commit_subject(message, policy.allowed_types)
    if parsed.valid:
        return None
    return _render_rejection(
        parsed.subject, parsed.violation, parsed.found_type, policy
    )


def _normalize_allowed_types(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        return default
    seen: set[str] = set()
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        commit_type = item.strip().lower()
        if not commit_type or commit_type in seen:
            continue
        normalized.append(commit_type)
        seen.add(commit_type)
    return tuple(normalized) or default


def _render_rejection(
    subject: str,
    violation: str | None,
    found_type: str | None,
    policy: _CommitMessagePolicy,
) -> str:
    first_line = _rejection_first_line(violation, found_type)
    lines = [first_line]
    if violation != "empty_subject":
        lines.extend(["", f"  subject: {subject}"])
    lines.extend(
        [
            "",
            "Expected: <type>[(<scope>)][!]: <description>",
            f"Allowed types: {', '.join(sorted(policy.allowed_types))}",
            "Examples:",
            "  fix(commit): reject non-conventional subjects",
            "  feat!: drop the legacy config format",
            "",
            "Rewrite the subject line and re-run the same command. Do not disable",
            "commit.message.require_conventional_subject to get past this check.",
        ]
    )
    return "\n".join(lines)


def _rejection_first_line(violation: str | None, found_type: str | None) -> str:
    if violation == "empty_subject":
        return "Commit message rejected: the message is empty."
    if violation == "uppercase_type":
        found = found_type or ""
        return (
            "Commit message rejected: the commit type must be lowercase — use "
            f'"{found.lower()}:" not "{found}:".'
        )
    if violation == "unknown_type":
        found = found_type or ""
        return f'Commit message rejected: "{found}" is not an allowed commit type.'
    if violation == "empty_description":
        return "Commit message rejected: the subject has no description after the type."
    return _GENERIC_REJECTION


__all__ = [
    "check_commit_message",
    "load_commit_message_policy",
]

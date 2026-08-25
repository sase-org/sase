"""Shared commit messages for Rust and Python bead CLI mutation paths."""

from __future__ import annotations

from collections.abc import Sequence


def mutation_commit_message(operation: str, issue_ids: list[str]) -> str | None:
    """Return the canonical auto-commit message for one CLI mutation."""
    if operation == "+1" and issue_ids:
        return f"chore(beads): +1 {issue_ids[0]}"
    if operation == "create" and issue_ids:
        return f"chore(beads): create {issue_ids[0]}"
    if operation == "update" and issue_ids:
        return f"chore(beads): update {' '.join(issue_ids)}"
    if operation == "note" and issue_ids:
        return f"chore(beads): note {issue_ids[0]}"
    if operation == "note_edit" and issue_ids:
        return f"chore(beads): edit note {issue_ids[0]}"
    if operation == "note_remove" and issue_ids:
        return f"chore(beads): remove note {issue_ids[0]}"
    if operation == "open" and issue_ids:
        return f"chore(beads): reopen {issue_ids[0]}"
    if operation == "close" and issue_ids:
        return f"chore(beads): close {' '.join(issue_ids)}"
    if operation == "snooze" and issue_ids:
        return f"chore(beads): snooze {' '.join(issue_ids)}"
    if operation == "snooze_cancel" and issue_ids:
        return f"chore(beads): wake {' '.join(issue_ids)}"
    if operation == "rm" and issue_ids:
        return f"chore(beads): remove {' '.join(issue_ids)}"
    if operation == "dep_add" and len(issue_ids) >= 2:
        return f"chore(beads): link {issue_ids[0]} -> {issue_ids[1]}"
    if operation == "dep_rm" and len(issue_ids) >= 2:
        return f"chore(beads): unlink {issue_ids[0]} -> {' '.join(issue_ids[1:])}"
    return None


def close_mutation_commit_message(
    *,
    closed_ids: Sequence[str],
    cascade_closed_ids: Sequence[str],
    noted_ids: Sequence[str],
) -> str | None:
    """Describe what a close mutation changed, excluding implicit closes."""
    cascade_ids = set(cascade_closed_ids)
    requested_closed_ids = [
        issue_id for issue_id in closed_ids if issue_id not in cascade_ids
    ]
    if requested_closed_ids:
        return f"chore(beads): close {' '.join(requested_closed_ids)}"
    if noted_ids:
        return f"chore(beads): note {' '.join(noted_ids)}"
    return None


def require_mutation_commit_message(operation: str, issue_ids: list[str]) -> str:
    """Return a canonical message, rejecting incomplete mutation metadata."""
    message = mutation_commit_message(operation, issue_ids)
    if message is None:
        raise ValueError(
            f"no bead mutation commit message for {operation!r} and {issue_ids!r}"
        )
    return message


__all__ = [
    "close_mutation_commit_message",
    "mutation_commit_message",
    "require_mutation_commit_message",
]

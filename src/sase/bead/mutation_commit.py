"""Shared commit messages for Rust and Python bead CLI mutation paths."""

from __future__ import annotations


def mutation_commit_message(operation: str, issue_ids: list[str]) -> str | None:
    """Return the canonical auto-commit message for one CLI mutation."""
    if operation == "create" and issue_ids:
        return f"chore(beads): create {issue_ids[0]}"
    if operation == "update" and issue_ids:
        return f"chore(beads): update {issue_ids[0]}"
    if operation == "note" and issue_ids:
        return f"chore(beads): note {issue_ids[0]}"
    if operation == "open" and issue_ids:
        return f"chore(beads): reopen {issue_ids[0]}"
    if operation == "close" and issue_ids:
        return f"chore(beads): close {' '.join(issue_ids)}"
    if operation == "rm" and issue_ids:
        return f"chore(beads): remove {' '.join(issue_ids)}"
    if operation == "dep_add" and len(issue_ids) >= 2:
        return f"chore(beads): link {issue_ids[0]} -> {issue_ids[1]}"
    if operation == "dep_rm" and len(issue_ids) >= 2:
        return f"chore(beads): unlink {issue_ids[0]} -> {' '.join(issue_ids[1:])}"
    return None


def require_mutation_commit_message(operation: str, issue_ids: list[str]) -> str:
    """Return a canonical message, rejecting incomplete mutation metadata."""
    message = mutation_commit_message(operation, issue_ids)
    if message is None:
        raise ValueError(
            f"no bead mutation commit message for {operation!r} and {issue_ids!r}"
        )
    return message


__all__ = ["mutation_commit_message", "require_mutation_commit_message"]

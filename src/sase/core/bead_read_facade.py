"""Python facade for Rust-backed read-only bead operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead.model import BeadSearchMatch, BeadTier, Issue, IssueType, Status
from sase.core.bead_wire import (
    issue_from_dict,
    issue_type_values,
    issues_from_list,
    search_matches_from_list,
    status_values,
    tier_values,
)
from sase.core.rust import require_rust_binding


def show(beads_dir: Path | str, issue_id: str) -> Issue:
    binding = require_rust_binding("bead_show")
    try:
        payload: dict[str, Any] = binding(str(beads_dir), issue_id)
    except ValueError as exc:
        _raise_key_error_for_missing_issue(issue_id, exc)
        raise
    return issue_from_dict(payload)


def history(beads_dir: Path | str, issue_id: str) -> dict[str, Any]:
    binding = require_rust_binding("bead_history")
    try:
        payload: dict[str, Any] = binding(str(beads_dir), issue_id)
    except ValueError as exc:
        _raise_key_error_for_missing_issue(issue_id, exc)
        raise
    return payload


def lost_notes(
    beads_dir: Path | str,
    issue_id: str | None = None,
) -> list[dict[str, Any]]:
    binding = require_rust_binding("bead_lost_notes")
    try:
        payload: list[dict[str, Any]] = binding(str(beads_dir), issue_id)
    except ValueError as exc:
        if issue_id is not None:
            _raise_key_error_for_missing_issue(issue_id, exc)
        raise
    return payload


def list_issues(
    beads_dir: Path | str,
    statuses: list[Status] | tuple[Status, ...] | None = None,
    issue_types: list[IssueType] | tuple[IssueType, ...] | None = None,
    tiers: list[BeadTier] | tuple[BeadTier, ...] | None = None,
) -> list[Issue]:
    binding = require_rust_binding("bead_list")
    payload: list[dict[str, Any]] = binding(
        str(beads_dir),
        status_values(statuses),
        issue_type_values(issue_types),
        tier_values(tiers),
    )
    return issues_from_list(payload)


def search(
    beads_dir: Path | str,
    query: str,
    statuses: list[Status] | tuple[Status, ...] | None = None,
    issue_types: list[IssueType] | tuple[IssueType, ...] | None = None,
    tiers: list[BeadTier] | tuple[BeadTier, ...] | None = None,
    limit: int | None = None,
) -> list[BeadSearchMatch]:
    binding = require_rust_binding("bead_search")
    payload: list[dict[str, Any]] = binding(
        str(beads_dir),
        query,
        status_values(statuses),
        issue_type_values(issue_types),
        tier_values(tiers),
        limit,
    )
    return search_matches_from_list(payload)


def ready(beads_dir: Path | str) -> list[Issue]:
    binding = require_rust_binding("bead_ready")
    payload: list[dict[str, Any]] = binding(str(beads_dir))
    return issues_from_list(payload)


def blocked(beads_dir: Path | str) -> list[Issue]:
    binding = require_rust_binding("bead_blocked")
    payload: list[dict[str, Any]] = binding(str(beads_dir))
    return issues_from_list(payload)


def stats(beads_dir: Path | str) -> dict[str, int]:
    binding = require_rust_binding("bead_stats")
    payload: dict[str, int] = binding(str(beads_dir))
    return {str(key): int(value) for key, value in payload.items()}


def doctor(
    beads_dir: Path | str,
    plan_roots: tuple[Path, ...] | None = None,
) -> list[str]:
    binding = require_rust_binding("bead_doctor")
    if plan_roots is None:
        raw_messages = binding(str(beads_dir))
    else:
        raw_messages = binding(
            str(beads_dir),
            [str(root) for root in plan_roots],
        )
    return [str(message) for message in raw_messages]


def get_epic_children(beads_dir: Path | str, epic_id: str) -> list[Issue]:
    binding = require_rust_binding("bead_get_epic_children")
    payload: list[dict[str, Any]] = binding(str(beads_dir), epic_id)
    return issues_from_list(payload)


def _raise_key_error_for_missing_issue(issue_id: str, exc: ValueError) -> None:
    if "Issue not found:" in str(exc):
        raise KeyError(f"Issue not found: {issue_id}") from exc


__all__ = [
    "blocked",
    "doctor",
    "get_epic_children",
    "history",
    "list_issues",
    "ready",
    "search",
    "show",
    "stats",
]

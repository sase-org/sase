"""Python facade for Rust-backed read-only bead operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead.model import Issue, IssueType, Status
from sase.core.bead_wire import (
    issue_from_dict,
    issue_type_values,
    issues_from_list,
    status_values,
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


def list_issues(
    beads_dir: Path | str,
    statuses: list[Status] | tuple[Status, ...] | None = None,
    issue_types: list[IssueType] | tuple[IssueType, ...] | None = None,
) -> list[Issue]:
    binding = require_rust_binding("bead_list")
    payload: list[dict[str, Any]] = binding(
        str(beads_dir),
        status_values(statuses),
        issue_type_values(issue_types),
    )
    return issues_from_list(payload)


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


def doctor(beads_dir: Path | str) -> list[str]:
    binding = require_rust_binding("bead_doctor")
    return [str(message) for message in binding(str(beads_dir))]


def get_epic_children(beads_dir: Path | str, epic_id: str) -> list[Issue]:
    binding = require_rust_binding("bead_get_epic_children")
    payload: list[dict[str, Any]] = binding(str(beads_dir), epic_id)
    return issues_from_list(payload)


def merged_show(beads_dirs: list[Path] | list[str], issue_id: str) -> Issue:
    binding = require_rust_binding("bead_merged_show")
    try:
        payload: dict[str, Any] = binding(_path_strings(beads_dirs), issue_id)
    except ValueError as exc:
        _raise_key_error_for_missing_issue(issue_id, exc)
        raise
    return issue_from_dict(payload)


def merged_list_issues(
    beads_dirs: list[Path] | list[str],
    statuses: list[Status] | tuple[Status, ...] | None = None,
    issue_types: list[IssueType] | tuple[IssueType, ...] | None = None,
) -> list[Issue]:
    binding = require_rust_binding("bead_merged_list")
    payload: list[dict[str, Any]] = binding(
        _path_strings(beads_dirs),
        status_values(statuses),
        issue_type_values(issue_types),
    )
    return issues_from_list(payload)


def merged_ready(beads_dirs: list[Path] | list[str]) -> list[Issue]:
    binding = require_rust_binding("bead_merged_ready")
    payload: list[dict[str, Any]] = binding(_path_strings(beads_dirs))
    return issues_from_list(payload)


def merged_blocked(beads_dirs: list[Path] | list[str]) -> list[Issue]:
    binding = require_rust_binding("bead_merged_blocked")
    payload: list[dict[str, Any]] = binding(_path_strings(beads_dirs))
    return issues_from_list(payload)


def merged_stats(beads_dirs: list[Path] | list[str]) -> dict[str, int]:
    binding = require_rust_binding("bead_merged_stats")
    payload: dict[str, int] = binding(_path_strings(beads_dirs))
    return {str(key): int(value) for key, value in payload.items()}


def merged_get_epic_children(
    beads_dirs: list[Path] | list[str],
    epic_id: str,
) -> list[Issue]:
    binding = require_rust_binding("bead_merged_get_epic_children")
    payload: list[dict[str, Any]] = binding(_path_strings(beads_dirs), epic_id)
    return issues_from_list(payload)


def _path_strings(paths: list[Path] | list[str]) -> list[str]:
    return [str(path) for path in paths]


def _raise_key_error_for_missing_issue(issue_id: str, exc: ValueError) -> None:
    if "Issue not found:" in str(exc):
        raise KeyError(f"Issue not found: {issue_id}") from exc


__all__ = [
    "blocked",
    "doctor",
    "get_epic_children",
    "list_issues",
    "merged_blocked",
    "merged_get_epic_children",
    "merged_list_issues",
    "merged_ready",
    "merged_show",
    "merged_stats",
    "ready",
    "show",
    "stats",
]

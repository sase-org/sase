"""Python facade for Rust-backed read-only bead operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.artifact_ref_models import ArtifactRefContext
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


@dataclass(frozen=True)
class BeadArtifactLinkRow:
    """One provenance-bearing bead-owned artifact-link neighborhood row."""

    source_ref: str
    relation: str
    target_ref: str
    description: str
    origin: str
    created_by: str
    created_at: str
    uses: int = 1

    def as_row_dict(self) -> dict[str, Any]:
        """Return the v2 aggregate-row shape used by :class:`ArtifactLinkStore`."""

        return {
            "schema_version": 2,
            "source_ref": self.source_ref,
            "relation": self.relation,
            "target_ref": self.target_ref,
            "description": self.description,
            "origin": self.origin,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "uses": self.uses,
        }


@dataclass(frozen=True)
class BeadIssueDetailSnapshot:
    """Relationships resolved from one Rust bead-store snapshot."""

    issue: Issue
    ancestors: tuple[Issue | None, ...]
    children: tuple[Issue, ...]
    depends_on: tuple[Issue | None, ...]
    blocks: tuple[Issue, ...]
    artifact_links: tuple[BeadArtifactLinkRow, ...] = ()


def show(beads_dir: Path | str, issue_id: str) -> Issue:
    binding = require_rust_binding("bead_show")
    try:
        payload: dict[str, Any] = binding(str(beads_dir), issue_id)
    except ValueError as exc:
        _raise_key_error_for_missing_issue(issue_id, exc)
        raise
    return issue_from_dict(payload)


def show_issue_detail(
    beads_dir: Path | str,
    issue_id: str,
    *,
    include_links: bool = True,
) -> BeadIssueDetailSnapshot:
    binding = require_rust_binding("bead_show_issue_detail")
    try:
        payload: dict[str, Any] = binding(
            str(beads_dir), issue_id, include_links=include_links
        )
    except ValueError as exc:
        _raise_key_error_for_missing_issue(issue_id, exc)
        raise
    return BeadIssueDetailSnapshot(
        issue=issue_from_dict(payload["issue"]),
        ancestors=tuple(
            None if issue is None else issue_from_dict(issue)
            for issue in payload["ancestors"]
        ),
        children=tuple(issues_from_list(payload["children"])),
        depends_on=tuple(
            None if issue is None else issue_from_dict(issue)
            for issue in payload["depends_on"]
        ),
        blocks=tuple(issues_from_list(payload["blocks"])),
        artifact_links=tuple(
            _artifact_link_row_from_dict(row)
            for row in payload.get("artifact_links") or ()
        ),
    )


def _artifact_link_row_from_dict(payload: object) -> BeadArtifactLinkRow:
    row = payload if isinstance(payload, dict) else {}
    uses_raw = row.get("uses", 1)
    try:
        uses = int(uses_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        uses = 1
    return BeadArtifactLinkRow(
        source_ref=str(row.get("source_ref") or ""),
        relation=str(row.get("relation") or ""),
        target_ref=str(row.get("target_ref") or ""),
        description=str(row.get("description") or ""),
        origin=str(row.get("origin") or ""),
        created_by=str(row.get("created_by") or ""),
        created_at=str(row.get("created_at") or ""),
        uses=uses if uses > 0 else 1,
    )


def resolve_id(beads_dir: Path | str, issue_id: str) -> str:
    binding = require_rust_binding("bead_resolve_id")
    try:
        return str(binding(str(beads_dir), issue_id))
    except ValueError as exc:
        _raise_key_error_for_missing_issue(issue_id, exc)
        raise


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
    regex: bool = False,
) -> list[BeadSearchMatch]:
    binding = require_rust_binding("bead_search")
    payload: list[dict[str, Any]] = binding(
        str(beads_dir),
        query,
        status_values(statuses),
        issue_type_values(issue_types),
        tier_values(tiers),
        limit,
        regex=regex,
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
    reference_context: ArtifactRefContext | None = None,
) -> list[str]:
    binding = require_rust_binding("bead_doctor")
    if plan_roots is None and reference_context is None:
        raw_messages = binding(str(beads_dir))
    else:
        raw_messages = binding(
            str(beads_dir),
            (None if plan_roots is None else [str(root) for root in plan_roots]),
            (None if reference_context is None else reference_context.to_wire()),
        )
    return [str(message) for message in raw_messages]


def doctor_report(
    beads_dir: Path | str,
    plan_roots: tuple[Path, ...] | None = None,
    reference_context: ArtifactRefContext | None = None,
) -> dict[str, Any]:
    binding = require_rust_binding("bead_doctor_report")
    if plan_roots is None and reference_context is None:
        payload: dict[str, Any] = binding(str(beads_dir))
    else:
        payload = binding(
            str(beads_dir),
            (None if plan_roots is None else [str(root) for root in plan_roots]),
            (None if reference_context is None else reference_context.to_wire()),
        )
    return dict(payload)


def get_epic_children(beads_dir: Path | str, epic_id: str) -> list[Issue]:
    binding = require_rust_binding("bead_get_epic_children")
    payload: list[dict[str, Any]] = binding(str(beads_dir), epic_id)
    return issues_from_list(payload)


def _raise_key_error_for_missing_issue(issue_id: str, exc: ValueError) -> None:
    if "Issue not found:" in str(exc):
        raise KeyError(f"Issue not found: {issue_id}") from exc


__all__ = [
    "BeadArtifactLinkRow",
    "BeadIssueDetailSnapshot",
    "blocked",
    "doctor",
    "doctor_report",
    "get_epic_children",
    "history",
    "list_issues",
    "ready",
    "resolve_id",
    "search",
    "show",
    "show_issue_detail",
    "stats",
]

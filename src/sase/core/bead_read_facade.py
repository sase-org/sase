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
from sase.core.rust import optional_rust_binding, require_rust_binding
from sase.task_types.fields import issue_matches_task_types


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


def list_issue_page(
    beads_dir: Path | str,
    statuses: list[Status] | tuple[Status, ...] | None = None,
    issue_types: list[IssueType] | tuple[IssueType, ...] | None = None,
    tiers: list[BeadTier] | tuple[BeadTier, ...] | None = None,
    task_types: list[str] | tuple[str, ...] | None = None,
    limit: int | None = None,
) -> tuple[int, list[Issue]]:
    """Return ``(total, issues)`` for one filtered list query.

    ``total`` counts every match before ``limit`` keeps the newest rows.
    Cores that predate the ``bead_list_query`` binding filter and slice in
    Python until the pin bump removes this fallback.
    """
    binding = optional_rust_binding("bead_list_query")
    if binding is not None:
        try:
            payload: dict[str, Any] = binding(
                str(beads_dir),
                status_values(statuses),
                issue_type_values(issue_types),
                tier_values(tiers),
                list(task_types) if task_types is not None else None,
                limit,
            )
            return int(payload["total"]), issues_from_list(payload["issues"])
        except Exception:
            pass
    issues = list_issues(
        beads_dir,
        statuses=statuses,
        issue_types=issue_types,
        tiers=tiers,
    )
    if task_types:
        issues = [
            issue
            for issue in issues
            if issue_matches_task_types(issue.task_type, task_types)
        ]
    total = len(issues)
    if limit:
        issues = issues[-limit:]
    return total, issues


def closed_ids(beads_dir: Path | str) -> list[str]:
    """Return closed bead IDs in replay order.

    Cores that predate the ``bead_closed_ids`` binding filter one
    ``list_issues`` read in Python until the pin bump removes this
    fallback.
    """
    binding = optional_rust_binding("bead_closed_ids")
    if binding is not None:
        try:
            payload: list[str] = binding(str(beads_dir))
            return [str(item) for item in payload]
        except Exception:
            pass
    return [
        issue.id for issue in list_issues(beads_dir) if issue.status is Status.CLOSED
    ]


def statuses_for_ids(
    beads_dir: Path | str,
    issue_ids: list[str] | tuple[str, ...],
) -> dict[str, str]:
    """Return requested bead IDs mapped to status values.

    IDs that do not exist (or match ambiguously) are omitted, never errors.
    Cores that predate the ``bead_statuses_for_ids`` binding answer from
    one ``list_issues`` read until the pin bump removes this fallback.
    """
    wanted = list(issue_ids)
    binding = optional_rust_binding("bead_statuses_for_ids")
    if binding is not None:
        try:
            payload: dict[str, str] = binding(str(beads_dir), wanted)
            return {str(key): str(value) for key, value in payload.items()}
        except Exception:
            pass
    by_id: dict[str, Issue] = {}
    by_suffix: dict[str, Issue | None] = {}
    for issue in list_issues(beads_dir):
        by_id[issue.id] = issue
        suffix = issue.id.rsplit("-", 1)[-1]
        if suffix == issue.id:
            continue
        by_suffix[suffix] = None if suffix in by_suffix else issue
    statuses: dict[str, str] = {}
    for bead_id in wanted:
        matched = by_id.get(bead_id)
        if matched is None:
            matched = by_suffix.get(bead_id)
        if matched is None:
            continue
        statuses[bead_id] = matched.status.value
    return statuses


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


@dataclass(frozen=True)
class BeadBoardSnapshot:
    """The TUI board views served from a single store read.

    ``issues`` matches :func:`list_issues` with no filters; ``ready_ids``
    and ``blocked_ids`` match the IDs of :func:`ready` and :func:`blocked`.
    """

    issues: list[Issue]
    ready_ids: frozenset[str]
    blocked_ids: frozenset[str]


def board_snapshot(beads_dir: Path | str) -> BeadBoardSnapshot | None:
    """Return the board views from one core read.

    Returns ``None`` when the installed core predates the
    ``bead_board_snapshot`` binding (sase-1h8.6), so callers fail open to
    the legacy three-read lane until the pin bump removes this fallback.
    """
    binding = optional_rust_binding("bead_board_snapshot")
    if binding is None:
        return None
    try:
        payload: dict[str, Any] = binding(str(beads_dir))
    except Exception:
        return None
    try:
        issues = issues_from_list(payload["issues"])
        ready_ids = frozenset(str(item) for item in payload["ready_ids"])
        blocked_ids = frozenset(str(item) for item in payload["blocked_ids"])
    except (KeyError, TypeError, ValueError):
        return None
    return BeadBoardSnapshot(
        issues=issues,
        ready_ids=ready_ids,
        blocked_ids=blocked_ids,
    )


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


def read_model_status(beads_dir: Path | str) -> dict[str, Any] | None:
    """Return the bead read-model cache health report for *beads_dir*.

    Returns ``None`` when the installed core predates the
    ``bead_read_model_status`` binding (sase-1h8.8) or the report cannot be
    built, so doctor fails open to plain replay diagnostics.
    """
    binding = optional_rust_binding("bead_read_model_status")
    if binding is None:
        return None
    try:
        payload = binding(str(beads_dir))
    except Exception:
        return None
    return dict(payload)


def read_model_verify_cache(beads_dir: Path | str) -> dict[str, Any] | None:
    """Compare the read-model cache against a forced full replay.

    Returns ``None`` when the installed core predates the
    ``bead_read_model_verify_cache`` binding (sase-1h8.8) or the comparison
    cannot run. Drift is a report, never an error.
    """
    binding = optional_rust_binding("bead_read_model_verify_cache")
    if binding is None:
        return None
    try:
        payload = binding(str(beads_dir))
    except Exception:
        return None
    return dict(payload)


def seal_watch_triggers(beads_dir: Path | str) -> dict[str, Any] | None:
    """Report the measurable sealed-archive triggers for *beads_dir*.

    Returns ``None`` when the installed core predates the
    ``bead_seal_watch_triggers`` binding (sase-1h8.10). An unusable store is
    a report (``available: False``), never an error, so doctor fails open.
    """
    binding = optional_rust_binding("bead_seal_watch_triggers")
    if binding is None:
        return None
    try:
        payload = binding(str(beads_dir))
    except Exception:
        return None
    return dict(payload)


def get_epic_children(beads_dir: Path | str, epic_id: str) -> list[Issue]:
    binding = require_rust_binding("bead_get_epic_children")
    payload: list[dict[str, Any]] = binding(str(beads_dir), epic_id)
    return issues_from_list(payload)


@dataclass(frozen=True)
class BeadStoreFingerprint:
    """Exact stat-only change token for one bead store.

    Event stores hash ``config.json``, ``events/manifest.json`` and every
    stream file's ``(size, mtime_ns, inode)``; legacy stores hash
    ``config.json`` and ``issues.jsonl``. Regenerating ``issues.jsonl``
    alone never moves an event store's token.
    """

    token: str
    layout: str
    files: int
    streams: int


def store_fingerprint(beads_dir: Path | str) -> BeadStoreFingerprint | None:
    """Return the exact stat-only fingerprint for *beads_dir*.

    Returns ``None`` when the installed core predates the
    ``bead_store_fingerprint`` binding (sase-1h8.5) or the store cannot be
    fingerprinted, so TUI caches fail open to their legacy mtime keys.
    """
    binding = optional_rust_binding("bead_store_fingerprint")
    if binding is None:
        return None
    try:
        payload: dict[str, Any] = binding(str(beads_dir))
    except Exception:
        return None
    try:
        return BeadStoreFingerprint(
            token=str(payload["token"]),
            layout=str(payload.get("layout") or ""),
            files=int(payload.get("files") or 0),
            streams=int(payload.get("streams") or 0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def referenced_artifact_ids(beads_dir: Path | str) -> frozenset[str] | None:
    """Return the artifact IDs referenced by the current bead state.

    Returns ``None`` when the installed core predates the
    ``bead_referenced_artifact_ids`` binding (sase-1h8.11) or the store
    cannot be read, so callers fall back to scanning the
    ``issues.jsonl`` projection text when it exists.
    """
    binding = optional_rust_binding("bead_referenced_artifact_ids")
    if binding is None:
        return None
    try:
        payload = binding(str(beads_dir))
    except Exception:
        return None
    try:
        return frozenset(str(value) for value in payload)
    except TypeError:
        return None


def _raise_key_error_for_missing_issue(issue_id: str, exc: ValueError) -> None:
    if "Issue not found:" in str(exc):
        raise KeyError(f"Issue not found: {issue_id}") from exc


__all__ = [
    "BeadArtifactLinkRow",
    "BeadBoardSnapshot",
    "BeadIssueDetailSnapshot",
    "BeadStoreFingerprint",
    "blocked",
    "board_snapshot",
    "doctor",
    "doctor_report",
    "get_epic_children",
    "history",
    "list_issues",
    "ready",
    "read_model_status",
    "read_model_verify_cache",
    "referenced_artifact_ids",
    "resolve_id",
    "seal_watch_triggers",
    "search",
    "show",
    "show_issue_detail",
    "stats",
    "store_fingerprint",
]

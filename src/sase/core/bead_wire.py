"""Wire helpers for the Rust bead read facade."""

from __future__ import annotations

from typing import Any

from sase.bead.close_history_codec import close_history_from_dicts
from sase.bead.snooze_codec import snooze_from_dict
from sase.bead.model import (
    BeadSearchMatch,
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    Resolution,
    Status,
    TaskPlusOneEvidence,
)


def status_values(
    statuses: list[Status] | tuple[Status, ...] | None,
) -> list[str] | None:
    if statuses is None:
        return None
    return [
        status.value if isinstance(status, Status) else str(status)
        for status in statuses
    ]


def issue_type_values(
    issue_types: list[IssueType] | tuple[IssueType, ...] | None,
) -> list[str] | None:
    if issue_types is None:
        return None
    return [issue_type_value(issue_type) for issue_type in issue_types]


def tier_values(
    tiers: list[BeadTier] | tuple[BeadTier, ...] | None,
) -> list[str] | None:
    if tiers is None:
        return None
    return [tier_value(tier) for tier in tiers]


def issue_type_value(issue_type: IssueType | str) -> str:
    return issue_type.value if isinstance(issue_type, IssueType) else str(issue_type)


def tier_value(tier: BeadTier | str) -> str:
    return tier.value if isinstance(tier, BeadTier) else str(tier)


def phase_size_value(size: PhaseSize | str) -> str:
    return size.value if isinstance(size, PhaseSize) else str(size)


def issue_from_dict(data: dict[str, Any]) -> Issue:
    return Issue(
        id=str(data["id"]),
        title=str(data["title"]),
        status=Status(str(data.get("status", "open"))),
        issue_type=IssueType(str(data.get("issue_type", "phase"))),
        tier=BeadTier(str(data["tier"])) if data.get("tier") else None,
        parent_id=None if data.get("parent_id") is None else str(data["parent_id"]),
        owner="" if data.get("owner") is None else str(data.get("owner", "")),
        assignee="" if data.get("assignee") is None else str(data.get("assignee", "")),
        created_at=""
        if data.get("created_at") is None
        else str(data.get("created_at", "")),
        created_by=""
        if data.get("created_by") is None
        else str(data.get("created_by", "")),
        updated_at=""
        if data.get("updated_at") is None
        else str(data.get("updated_at", "")),
        closed_at=None if data.get("closed_at") is None else str(data["closed_at"]),
        close_reason=(
            None if data.get("close_reason") is None else str(data["close_reason"])
        ),
        resolution=(
            Resolution(str(data["resolution"])) if data.get("resolution") else None
        ),
        description=(
            "" if data.get("description") is None else str(data.get("description", ""))
        ),
        notes="" if data.get("notes") is None else str(data.get("notes", "")),
        design="" if data.get("design") is None else str(data.get("design", "")),
        refs=[
            str(reference)
            for reference in data.get("refs") or []
            if reference is not None
        ],
        plus_one_evidence=[
            TaskPlusOneEvidence(
                timestamp=str(evidence.get("timestamp", "")),
                reporter=str(evidence.get("reporter", "")),
                note=str(evidence.get("note", "")),
                refs=tuple(
                    str(reference)
                    for reference in evidence.get("refs") or []
                    if reference is not None
                ),
            )
            for evidence in data.get("plus_one_evidence") or []
        ],
        close_history=close_history_from_dicts(data.get("close_history")),
        snooze=snooze_from_dict(data.get("snooze")),
        model="" if data.get("model") is None else str(data.get("model", "")),
        size=PhaseSize(str(data["size"])) if data.get("size") else None,
        is_ready_to_work=bool(data.get("is_ready_to_work", False)),
        changespec_name=(
            ""
            if data.get("changespec_name") is None
            else str(data.get("changespec_name", ""))
        ),
        changespec_bug_id=(
            ""
            if data.get("changespec_bug_id") is None
            else str(data.get("changespec_bug_id", ""))
        ),
        dependencies=[
            Dependency(
                issue_id=str(dep["issue_id"]),
                depends_on_id=str(dep["depends_on_id"]),
                created_at=""
                if dep.get("created_at") is None
                else str(dep.get("created_at", "")),
                created_by=""
                if dep.get("created_by") is None
                else str(dep.get("created_by", "")),
            )
            for dep in data.get("dependencies", [])
        ],
    )


def issues_from_list(items: list[dict[str, Any]]) -> list[Issue]:
    return [issue_from_dict(item) for item in items]


def _search_match_from_dict(data: dict[str, Any]) -> BeadSearchMatch:
    return BeadSearchMatch(
        issue=issue_from_dict(dict(data["issue"])),
        matched_fields=[str(field) for field in data.get("matched_fields", [])],
    )


def search_matches_from_list(items: list[dict[str, Any]]) -> list[BeadSearchMatch]:
    return [_search_match_from_dict(item) for item in items]


__all__ = [
    "issue_from_dict",
    "issue_type_value",
    "issue_type_values",
    "issues_from_list",
    "search_matches_from_list",
    "status_values",
    "tier_value",
    "tier_values",
]

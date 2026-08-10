"""Shared language and palette for task ``+1`` presentation surfaces."""

from __future__ import annotations

from collections.abc import Iterable

from sase.ansi_style import ansi_sgr
from sase.bead.model import Issue, Status, TaskPlusOneEvidence
from sase.core.time import parse_local

PLUS_ONE_ACCENT = "#FF87D7"
PLUS_ONE_RICH_STYLE = f"bold {PLUS_ONE_ACCENT}"
PLUS_ONE_CLI_STYLE = ansi_sgr(color=PLUS_ONE_ACCENT, bold=True)
PLUS_ONE_SECTION_LABEL = "+1 EVIDENCE"
POST_CLOSE_ACCENT = "#87D7FF"
POST_CLOSE_RICH_STYLE = f"bold {POST_CLOSE_ACCENT}"
POST_CLOSE_CLI_STYLE = ansi_sgr(color=POST_CLOSE_ACCENT, bold=True)
POST_CLOSE_EVIDENCE_MARKER = "post-close evidence"


def plus_one_badge(count: int) -> str:
    """Return the compact corroboration badge, or an empty string for zero."""

    return f"+{count}" if count > 0 else ""


def plus_one_reports_label(count: int) -> str:
    """Return the shared human label for a derived evidence count."""

    noun = "report" if count == 1 else "reports"
    return f"{count} +1 {noun}"


def plus_one_evidence_search_text(
    evidence: Iterable[TaskPlusOneEvidence],
) -> str:
    """Flatten structured evidence for already-cached in-memory search indexes."""

    return "\n".join(
        value
        for item in evidence
        for value in (
            item.reporter,
            item.timestamp,
            item.observed_since,
            item.note,
            *item.refs,
        )
        if value
    )


def plus_one_evidence_label(evidence: TaskPlusOneEvidence) -> str:
    """Return the stable reporter/time label shared by detail surfaces."""

    return (
        f"+1 {evidence.reporter} · {evidence.timestamp}"
        if evidence.timestamp
        else f"+1 {evidence.reporter}"
    )


def post_close_plus_one_count(issue: Issue) -> int:
    """Return evidence count recorded after the bead's current close."""

    return sum(
        1
        for evidence in issue.plus_one_evidence
        if evidence_recorded_after_current_close(issue, evidence)
    )


def post_close_plus_one_badge(count: int) -> str:
    """Return the compact post-close corroboration badge, or empty for zero."""

    return f"+{count} after close" if count > 0 else ""


def evidence_recorded_after_current_close(
    issue: Issue, evidence: TaskPlusOneEvidence
) -> bool:
    """Return whether evidence was written after the bead's live close."""

    if issue.status is not Status.CLOSED or not issue.closed_at:
        return False
    evidence_time = parse_local(evidence.timestamp)
    close_time = parse_local(issue.closed_at)
    if evidence_time is None or close_time is None:
        return evidence.timestamp >= issue.closed_at
    return evidence_time >= close_time


__all__ = [
    "PLUS_ONE_ACCENT",
    "PLUS_ONE_CLI_STYLE",
    "PLUS_ONE_RICH_STYLE",
    "PLUS_ONE_SECTION_LABEL",
    "POST_CLOSE_ACCENT",
    "POST_CLOSE_CLI_STYLE",
    "POST_CLOSE_EVIDENCE_MARKER",
    "POST_CLOSE_RICH_STYLE",
    "evidence_recorded_after_current_close",
    "post_close_plus_one_badge",
    "post_close_plus_one_count",
    "plus_one_badge",
    "plus_one_evidence_label",
    "plus_one_evidence_search_text",
    "plus_one_reports_label",
]

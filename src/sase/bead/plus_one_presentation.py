"""Shared language and palette for task ``+1`` presentation surfaces."""

from __future__ import annotations

from collections.abc import Iterable

from sase.ansi_style import ansi_sgr
from sase.bead.model import TaskPlusOneEvidence

PLUS_ONE_ACCENT = "#FF87D7"
PLUS_ONE_RICH_STYLE = f"bold {PLUS_ONE_ACCENT}"
PLUS_ONE_CLI_STYLE = ansi_sgr(color=PLUS_ONE_ACCENT, bold=True)
PLUS_ONE_SECTION_LABEL = "+1 EVIDENCE"


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
        for value in (item.reporter, item.timestamp, item.note, *item.refs)
        if value
    )


def plus_one_evidence_label(evidence: TaskPlusOneEvidence) -> str:
    """Return the stable reporter/time label shared by detail surfaces."""

    return (
        f"+1 {evidence.reporter} · {evidence.timestamp}"
        if evidence.timestamp
        else f"+1 {evidence.reporter}"
    )


__all__ = [
    "PLUS_ONE_ACCENT",
    "PLUS_ONE_CLI_STYLE",
    "PLUS_ONE_RICH_STYLE",
    "PLUS_ONE_SECTION_LABEL",
    "plus_one_badge",
    "plus_one_evidence_label",
    "plus_one_evidence_search_text",
    "plus_one_reports_label",
]

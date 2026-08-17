"""Markdown body sections for the shared bead presentation."""

from __future__ import annotations

from sase.bead.model import Issue
from sase.bead.plus_one_presentation import (
    PLUS_ONE_SECTION_LABEL,
    POST_CLOSE_EVIDENCE_MARKER,
    evidence_recorded_after_current_close,
    plus_one_evidence_label,
)
from sase.bead.reopen_presentation import (
    close_history_display_order,
    close_record_label,
    close_record_reopened_label,
)


def close_history_markdown(issue: Issue) -> list[str]:
    if not issue.close_history:
        return []
    lines = ["## Previously Closed", ""]
    for index, record in enumerate(close_history_display_order(issue.close_history)):
        if index:
            lines.append("")
        reason = (record.close_reason or "(none)").replace("`", "\\`")
        lines.append(f"> [!WARNING] **{close_record_label(record)}**")
        lines.extend(f"> {line}" if line else ">" for line in reason.splitlines())
        lines.append(">")
        lines.append(f"> {close_record_reopened_label(record)}")
    lines.append("")
    return lines


def plus_one_evidence_markdown(issue: Issue) -> list[str]:
    if not issue.plus_one_evidence:
        return []
    lines = ["", f"## {PLUS_ONE_SECTION_LABEL.title()}", ""]
    for index, evidence in enumerate(issue.plus_one_evidence):
        if index:
            lines.append("")
        label = plus_one_evidence_label(evidence).replace("`", "\\`")
        if evidence_recorded_after_current_close(issue, evidence):
            label = f"{label} {POST_CLOSE_EVIDENCE_MARKER}"
        lines.append(f"> [!TIP] **{label}**")
        if evidence.observed_since:
            lines.append(f"> **Observed since:** {evidence.observed_since}")
        lines.extend(
            f"> {line}" if line else ">" for line in evidence.note.splitlines()
        )
        if evidence.refs:
            lines.append(">")
            lines.append(f"> **Refs:** {', '.join(evidence.refs)}")
    return lines


def flag_markdown(issue: Issue) -> list[str]:
    record = issue.flag
    if record is None:
        return []
    return [
        "## Flag",
        "",
        f"- Key: `{_inline_code(record.key)}`",
        f"- Remove by date: `{_inline_code(record.remove_by_date)}`",
        f"- Remove by release: `v{_inline_code(record.remove_by_release)}`",
        "",
    ]


def _inline_code(value: str) -> str:
    return value.replace("`", "\\`")


__all__ = [
    "close_history_markdown",
    "flag_markdown",
    "plus_one_evidence_markdown",
]

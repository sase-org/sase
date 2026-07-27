"""Shared Markdown helpers for browsable agent publication pages."""

from __future__ import annotations

from collections import defaultdict
import posixpath
from urllib.parse import quote

from sase.agents_sync.v2_models import V2RunRecord


def md_escape(value: str) -> str:
    """Escape Markdown punctuation in free-form text."""

    return (
        value.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("|", "\\|")
        .replace("<", "\\<")
        .replace(">", "\\>")
    )


def md_cell(value: str) -> str:
    """Escape text for a Markdown table cell."""

    return md_escape(value).replace("\r", " ").replace("\n", "<br>")


def md_code(value: str) -> str:
    """Escape text embedded in a Markdown code span."""

    return value.replace("`", "\\`").replace("\r", " ").replace("\n", " ")


def md_mermaid(value: str) -> str:
    """Escape text embedded in a Mermaid quoted label."""

    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def md_html_id(value: str) -> str:
    """Encode a stable HTML anchor identifier."""

    return quote(value, safe="-._")


def page_url(value: str) -> str:
    """Encode a repository-relative page URL."""

    return quote(value, safe="/.-_")


def relative_page_url(source: str, target: str) -> str:
    """Return an encoded URL from one rendered page to another."""

    path, marker, anchor = target.partition("#")
    relative = posixpath.relpath(path, posixpath.dirname(source))
    suffix = f"#{quote(anchor, safe='-._')}" if marker else ""
    return page_url(relative) + suffix


def page_bytes(text: str) -> bytes:
    """Encode rendered Markdown for the publication payload."""

    return text.encode("utf-8")


def state_counts(runs: tuple[V2RunRecord, ...]) -> str:
    """Summarize run states in deterministic order."""

    counts: dict[str, int] = defaultdict(int)
    for run in runs:
        counts[run.state] += 1
    return ", ".join(f"{state} {count}" for state, count in sorted(counts.items()))


def run_timing(run: V2RunRecord) -> str:
    """Render a run's available timing fields."""

    if run.started_at and run.finished_at:
        return f"{run.started_at} → {run.finished_at}"
    return run.started_at or run.finished_at or run.dismissed_at or "—"


__all__ = [
    "md_cell",
    "md_code",
    "md_escape",
    "md_html_id",
    "md_mermaid",
    "page_bytes",
    "page_url",
    "relative_page_url",
    "run_timing",
    "state_counts",
]

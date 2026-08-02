"""Shared rendering helpers for the ``sase prompt`` command group."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rich.text import Text

from sase.history.prompt import PromptHistoryRecord

if TYPE_CHECKING:
    from sase.prompt.search.model import PromptSource

# Preview width for list rows and JSON ``text_preview``. ``list`` never prints
# full prompt text; ``show``/``export``/``copy`` are the full-text escape hatches.
_PREVIEW_CHARS = 72

_TIMESTAMP_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$")

# Default Rich style for the matched substring in search output.
_MATCH_STYLE = "bold yellow"


def prompt_preview(text: str, limit: int = _PREVIEW_CHARS) -> str:
    """Return a single-line, token-stripped, truncated preview of *text*."""
    try:
        from sase.history.prompt_metadata import clean_prompt_preview

        cleaned = clean_prompt_preview(text)
    except Exception:
        cleaned = ""
    if not cleaned:
        cleaned = " ".join(text.split())
    if len(cleaned) > limit:
        return cleaned[: max(limit - 1, 1)] + "…"
    return cleaned


def format_timestamp(ts: str) -> str:
    """Format a SASE ``YYmmdd_HHMMSS`` timestamp as ``YYYY-MM-DD HH:MM``.

    Returns the input unchanged when it is not a recognized SASE timestamp.
    """
    match = _TIMESTAMP_RE.match(ts)
    if not match:
        return ts
    yy, mm, dd, hh, mi = match.group(1, 2, 3, 4, 5)
    return f"20{yy}-{mm}-{dd} {hh}:{mi}"


def format_search_date(ts: str) -> str:
    """Format a hit's comparable date for display, or ``—`` when unresolved.

    The search corpus floors an undatable hit to an all-zero ``YYmmdd_HHMMSS``
    anchor; rendering that literally as ``2000-00-00`` would be misleading, so
    an empty or all-zero anchor renders as an em dash instead.
    """
    if not ts or set(ts) <= {"0", "_"}:
        return "—"
    return format_timestamp(ts)


def format_search_date_iso(ts: str) -> str | None:
    """Return a hit's date as an ISO ``YYYY-MM-DD`` string, or ``None``.

    Used by the never-colored ``json`` search envelope, where an undatable hit
    (the all-zero ``YYmmdd_HHMMSS`` floor or an empty anchor) is reported as
    ``null`` rather than a misleading ``2000-00-00``.
    """
    if not ts or set(ts) <= {"0", "_"}:
        return None
    match = _TIMESTAMP_RE.match(ts)
    if not match:
        return None
    yy, mm, dd = match.group(1, 2, 3)
    return f"20{yy}-{mm}-{dd}"


def highlight_match(
    value: str,
    query: str,
    *,
    base_style: str = "",
    match_style: str = _MATCH_STYLE,
) -> Text:
    """Return *value* as Rich ``Text`` with every *query* occurrence highlighted.

    Matching is case-insensitive (via :meth:`str.lower`, which is length-stable
    for the ASCII-dominant prompt corpus so highlight spans stay aligned with
    the original text). *base_style* styles the whole string; *match_style*
    styles each matched span on top of it.
    """
    text = Text(value, style=base_style)
    needle = query.strip()
    if not needle:
        return text
    lowered_value = value.lower()
    lowered_needle = needle.lower()
    start = 0
    while True:
        index = lowered_value.find(lowered_needle, start)
        if index < 0:
            break
        text.stylize(match_style, index, index + len(needle))
        start = index + len(needle)
    return text


def source_badge(source: PromptSource) -> Text:
    """Return the colored one-word badge for a search hit's source store."""
    from sase.prompt.search.model import PromptSource

    badges = {
        PromptSource.ARCHIVE: ("archive", "bold cyan"),
        PromptSource.LOCAL: ("local", "bold blue"),
    }
    label, style = badges.get(source, (str(source), ""))
    return Text(label, style=style)


def format_size(num_bytes: int) -> str:
    """Format a byte count as a compact human-readable size."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def record_to_json(
    record: PromptHistoryRecord,
    *,
    preview_chars: int = _PREVIEW_CHARS,
) -> dict[str, object]:
    """Return a stable-key-ordered JSON dict for a prompt-history record.

    Legacy context fields (``workspace``, ``branch_or_workspace``) are emitted
    only when present so the core schema stays compact and diff-friendly.
    """
    payload: dict[str, object] = {
        "id": record.id,
        "timestamp": record.timestamp,
        "last_used": record.last_used,
        "cancelled": record.cancelled,
        "text_preview": prompt_preview(record.text, preview_chars),
        "text_chars": record.text_chars,
        "text_sha256": record.text_sha256,
    }
    if record.workspace:
        payload["workspace"] = record.workspace
    if record.branch_or_workspace:
        payload["branch_or_workspace"] = record.branch_or_workspace
    return payload

"""Shared rendering helpers for the ``sase prompt`` command group."""

from __future__ import annotations

import re

from sase.history.prompt import PromptHistoryRecord

# Preview width for list rows and JSON ``text_preview``. ``list`` never prints
# full prompt text; ``show``/``export``/``copy`` are the full-text escape hatches.
_PREVIEW_CHARS = 72

_TIMESTAMP_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$")


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

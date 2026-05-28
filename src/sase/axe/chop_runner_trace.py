"""Traceback and log-preview helpers for chop runs."""

from __future__ import annotations

import traceback


NO_PYTHON_TRACEBACK = "<no python traceback: subprocess error>"
TRACEBACK_UNAVAILABLE = "<traceback unavailable>"
PROMPT_PREVIEW_CHARS = 160


def capture_traceback() -> str:
    """Capture the active exception traceback, with a placeholder for empty."""
    formatted = traceback.format_exc().rstrip("\n")
    if formatted == "NoneType: None" or not formatted:
        return TRACEBACK_UNAVAILABLE
    return formatted


def compact_preview(value: str, *, limit: int = PROMPT_PREVIEW_CHARS) -> str:
    """Return a bounded single-line preview for chop run logs."""
    preview = " ".join(value.split())
    if len(preview) <= limit:
        return preview
    return preview[: limit - 3].rstrip() + "..."


_capture_traceback = capture_traceback
_compact_preview = compact_preview

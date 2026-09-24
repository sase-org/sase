"""Transcript block output rendering for the Command Line panel.

Output flows through ``sanitize → Text.from_ansi → cache`` keyed by
``(proc_id, byte offset)``. Collapsed blocks show the last 12 lines plus a
``⋯ N more lines`` marker; expanded blocks cap at 2,000 lines (``v`` opens
the pager for anything longer in a later phase).
"""

from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime

from rich.text import Text

#: Lines shown in a collapsed block body.
COLLAPSED_BLOCK_LINES = 12
#: Lines rendered at most in an expanded block body.
EXPANDED_BLOCK_LINE_CAP = 2000
#: Spinner frames advanced on each tail tick for running blocks.
BLOCK_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-ln-zA-LN-Z]")
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
_CR_LINE_RE = re.compile(r"[^\n]*\r(?!\n)")

_render_cache: OrderedDict[tuple[str, int], Text] = OrderedDict()
_RENDER_CACHE_MAX = 256


def sanitize_block_output(text: str) -> str:
    """Collapse ``\\r`` overwrites and drop non-SGR CSI and OSC sequences."""
    cleaned = _OSC_RE.sub("", text)
    cleaned = _CR_LINE_RE.sub("", cleaned)
    cleaned = _CSI_RE.sub(
        lambda match: match.group(0) if _SGR_RE.fullmatch(match.group(0)) else "",
        cleaned,
    )
    return cleaned


def render_block_output(proc_id: str, byte_offset: int, text: str) -> Text:
    """Render sanitized output, caching per ``(proc_id, byte offset)``."""
    key = (proc_id, byte_offset)
    cached = _render_cache.get(key)
    if cached is not None:
        _render_cache.move_to_end(key)
        return cached
    rendered = Text.from_ansi(sanitize_block_output(text))
    _render_cache[key] = rendered
    _render_cache.move_to_end(key)
    while len(_render_cache) > _RENDER_CACHE_MAX:
        _render_cache.popitem(last=False)
    return rendered


def collapsed_body_lines(text: str) -> tuple[list[str], int]:
    """Split tail text into collapsed body lines plus the hidden-line count."""
    lines = text.splitlines()
    if len(lines) <= COLLAPSED_BLOCK_LINES:
        return lines, 0
    hidden = len(lines) - COLLAPSED_BLOCK_LINES
    return lines[-COLLAPSED_BLOCK_LINES:], hidden


def expanded_body_lines(text: str) -> tuple[list[str], bool]:
    """Split tail text into expanded body lines plus whether output was capped."""
    lines = text.splitlines()
    if len(lines) <= EXPANDED_BLOCK_LINE_CAP:
        return lines, False
    return lines[-EXPANDED_BLOCK_LINE_CAP:], True


def gutter_glyph(
    status: str, *, exit_code: int | None = None, declined: bool = False
) -> str:
    """Return the block gutter glyph for a block status."""
    if status in ("submitting", "running"):
        return "⠹"
    if status == "success":
        return "✓"
    if status == "error":
        return "✗" if not declined else "⊘"
    if status == "foreground":
        return "↗"
    if status == "builtin":
        return "›"
    return "⊘"


def block_header_right(
    status: str,
    *,
    exit_code: int | None = None,
    elapsed: float | None = None,
    finished_at: float | None = None,
    proc_id: str | None = None,
    declined: bool = False,
) -> str:
    """Render the dim right-aligned block header metadata."""
    if status in ("submitting", "running"):
        running_for = f"{elapsed:.0f}s" if elapsed else "0s"
        proc = f" · proc {proc_id[:6]}" if proc_id else ""
        return f"running {running_for}{proc}"
    if status == "submit_failed":
        return "submit failed"
    if status == "denied":
        return "not run"
    if status == "foreground":
        exit_part = f"exit {exit_code}" if exit_code is not None else "exit ?"
        return f"ran in terminal · {exit_part}"
    if status == "builtin":
        return "built-in"
    if declined and status == "error":
        parts = ["declined"]
        if exit_code is not None:
            parts.append(f"exit {exit_code}")
        parts.append("R rerun with -y")
        return " · ".join(parts)
    stamp = ""
    if finished_at is not None:
        try:
            stamp = datetime.fromtimestamp(finished_at).strftime("%H:%M")
        except (OSError, OverflowError, ValueError):
            stamp = ""
    parts = []
    if exit_code is not None:
        parts.append(f"exit {exit_code}")
    if elapsed is not None:
        parts.append(f"{elapsed:.1f}s")
    if stamp:
        parts.append(stamp)
    if proc_id:
        parts.append(f"proc {proc_id[:6]}")
    return " · ".join(parts)


__all__ = [
    "BLOCK_SPINNER_FRAMES",
    "COLLAPSED_BLOCK_LINES",
    "EXPANDED_BLOCK_LINE_CAP",
    "block_header_right",
    "collapsed_body_lines",
    "expanded_body_lines",
    "gutter_glyph",
    "render_block_output",
    "sanitize_block_output",
]

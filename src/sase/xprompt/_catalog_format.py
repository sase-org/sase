"""Formatting helpers shared by xprompt catalog renderers."""

from __future__ import annotations

import hashlib

from sase.xprompt.models import UNSET, InputArg


MAX_CONTENT_LINES = 40
MAX_MOBILE_CONTENT_PREVIEW_CHARS = 800


def tag_color_class(tag: str) -> str:
    """Deterministic pill colour class for a tag (4-way cycle)."""
    digest = hashlib.md5(tag.encode("utf-8")).hexdigest()
    bucket = int(digest[:2], 16) % 4
    return f"pill-color-{bucket}"


def truncate_content(content: str, source_path: str | None = None) -> dict:
    """Return dict with 'text' and optional 'elided' note for a card body."""
    lines = content.splitlines()
    if len(lines) <= MAX_CONTENT_LINES:
        return {"text": content, "elided": None}
    head = "\n".join(lines[:MAX_CONTENT_LINES])
    remaining = len(lines) - MAX_CONTENT_LINES
    note = f"... ({remaining} more lines"
    if source_path:
        note += f" - see {source_path}"
    note += ")"
    return {"text": head, "elided": note}


def format_inputs(inputs: list[InputArg]) -> str:
    """Render an input signature like ``(plan_file: path, notes?)``."""
    if not inputs:
        return ""
    parts: list[str] = []
    for inp in inputs:
        if inp.is_step_input:
            continue
        required = inp.default is UNSET
        suffix = "" if required else "?"
        parts.append(f"{inp.name}{suffix}: {inp.type.value}")
    if not parts:
        return ""
    return "(" + ", ".join(parts) + ")"


def bar_width(count: int, maximum: int) -> int:
    """Return the % width of a bar chart segment."""
    if maximum <= 0:
        return 0
    return max(2, int(round(count * 100 / maximum)))


_tag_color_class = tag_color_class
_truncate_content = truncate_content
_format_inputs = format_inputs
_bar_width = bar_width

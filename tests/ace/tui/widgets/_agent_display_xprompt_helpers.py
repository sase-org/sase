"""Shared helpers for terminal agent xprompt display tests."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text

from sase.ace.tui.util.lazy_syntax import CachedRenderable


def _header_text(renderable: object) -> Text:
    if isinstance(renderable, CachedRenderable):
        renderable = renderable.renderable
    if isinstance(renderable, Text):
        return renderable
    assert isinstance(renderable, Group)
    header = renderable.renderables[0]
    assert isinstance(header, Text)
    return header


def _styles_at(text: Text, needle: str, *, offset: int = 0) -> set[str]:
    position = text.plain.index(needle) + offset
    return {
        str(span.style)
        for span in text.spans
        if span.start <= position < span.end and span.style is not None
    }


def _last_style_at(text: Text, needle: str, *, offset: int = 0) -> str | None:
    position = text.plain.index(needle) + offset
    styles = [
        str(span.style)
        for span in text.spans
        if span.start <= position < span.end and span.style is not None
    ]
    return styles[-1] if styles else None

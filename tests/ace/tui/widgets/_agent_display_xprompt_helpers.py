"""Shared helpers for terminal agent xprompt display tests."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text

from sase.ace.tui.util.lazy_syntax import CachedRenderable


def _header_text(renderable: object) -> Text:
    from sase.ace.tui.widgets.decks.card_part import flatten_card_document

    def _unwrap(candidate: object) -> object:
        while isinstance(candidate, CachedRenderable):
            candidate = candidate.renderable
        return candidate

    renderable = _unwrap(renderable)
    renderable = flatten_card_document(renderable)
    if isinstance(renderable, Text):
        return renderable
    assert isinstance(renderable, Group)
    header = _unwrap(renderable.renderables[0])
    if isinstance(header, Text):
        return header
    # Unwrap AgentHeaderRenderable carriers to their logical text.
    text = getattr(header, "_text", None)
    if isinstance(text, Text):
        return text
    plain = getattr(header, "plain", None)
    assert isinstance(plain, str), f"unexpected header type {type(header)}"
    raise AssertionError(f"unexpected header type {type(header)}")


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

"""Stable equality keys for Rich text used by compact ACE indicators."""

from __future__ import annotations

from rich.text import Text


def text_signature(
    text: Text,
) -> tuple[str, str, tuple[tuple[int, int, str], ...]]:
    """Return a stable equality key for Rich text content, base style, and spans."""
    return (
        text.plain,
        str(text.style),
        tuple((span.start, span.end, str(span.style)) for span in text.spans),
    )


__all__ = ["text_signature"]

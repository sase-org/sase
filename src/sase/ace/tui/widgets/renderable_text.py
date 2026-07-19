"""Helpers for flattening Rich renderables into searchable plain text."""

from __future__ import annotations

from io import StringIO

from rich.console import Console


def renderable_to_text(renderable: object) -> str | None:
    """Render ``renderable`` to plain text, returning ``None`` when empty."""
    if renderable is None:
        return None
    console = Console(record=True, width=120, color_system=None, file=StringIO())
    console.print(renderable)
    text = console.export_text(clear=True).rstrip()
    return text or None


__all__ = ["renderable_to_text"]

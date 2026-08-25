"""Shared breadcrumb-strip renderer used by the Memory and Snippets panels.

Pure and free of any glossary-specific data or imports, so panes that need a
``TRAIL  A › B › C`` strip do not have to depend on the glossary panel.
"""

from __future__ import annotations

from rich.text import Text


def build_trail_strip(
    path: tuple[str, ...], *, accent: str, max_width: int = 70
) -> Text:
    """Build the ``TRAIL  A › B › C`` breadcrumb strip.

    Once the plain joined path would exceed *max_width*, the middle is
    elided with ``…`` while the first entry and the two most recent stay
    visible, per the plan's bounded-breadcrumb rule.
    """
    text = Text()
    text.append("TRAIL  ", style=f"bold {accent}")
    full = " › ".join(path)
    if len(full) <= max_width or len(path) <= 3:
        text.append(full)
    else:
        text.append(f"{path[0]} › … › {' › '.join(path[-2:])}")
    return text


__all__ = ["build_trail_strip"]

"""Shared helpers for time-band row rendering.

Public helpers needed by more than one row module live here with public
names; each row module keeps its single-use helpers private in its own
file so no ``_``-prefixed name is imported across modules.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.pager._time_band_vocab import DIM_STYLE


def style_role(styles: Any | None, attr: str, fallback: str) -> str:
    """Return one history colour role, falling back to legacy constants."""
    if styles is not None:
        try:
            value = getattr(styles, attr, None)
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return value
    return fallback


def honest_prefix(kind: str, detail: str | None) -> Text | None:
    """Return the leading honest segment for history-backed rows, if any."""
    if kind == "shallow":
        text = Text(no_wrap=True, overflow="crop")
        text.append("SHALLOW", style=DIM_STYLE)
        if detail:
            text.append(f" · history truncated at {detail}", style=DIM_STYLE)
        else:
            text.append(" · history truncated", style=DIM_STYLE)
        return text
    if kind == "template":
        text = Text(no_wrap=True, overflow="crop")
        text.append("TEMPLATE", style=DIM_STYLE)
        text.append(" · per-host rendering", style=DIM_STYLE)
        return text
    return None


__all__ = [
    "honest_prefix",
    "style_role",
]

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


def metadata_style(styles: Any | None) -> str:
    """Return the explicit secondary metadata foreground when available."""

    return style_role(styles, "secondary", DIM_STYLE)


def honest_prefix(
    kind: str, detail: str | None, styles: Any | None = None
) -> Text | None:
    """Return the leading honest segment for history-backed rows, if any."""
    meta = metadata_style(styles)
    if kind == "shallow":
        text = Text(no_wrap=True, overflow="crop")
        text.append("SHALLOW", style=meta)
        if detail:
            text.append(f" · history truncated at {detail}", style=meta)
        else:
            text.append(" · history truncated", style=meta)
        return text
    if kind == "template":
        text = Text(no_wrap=True, overflow="crop")
        text.append("TEMPLATE", style=meta)
        text.append(" · per-host rendering", style=meta)
        return text
    return None


__all__ = [
    "honest_prefix",
    "metadata_style",
    "style_role",
]

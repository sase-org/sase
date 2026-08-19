"""Shared status colors for ``sase agent list`` and ``sase agent restart``."""

from __future__ import annotations

from rich.text import Text

from sase.monitor_status import (
    MonitorStatusPair,
    monitor_status_glyph,
    monitor_status_style,
)

STATUS_COLORS: dict[str, str] = {
    "STARTING": "cyan",
    "RUNNING": "green",
    "QUEUED": "#5F87FF",
    "WAITING": "yellow",
    "DONE": "bright_black",
    "FAILED": "red",
}


def agent_status_text(
    status: str,
    *,
    monitor: MonitorStatusPair | None = None,
    monitor_state: str | None = None,
) -> Text:
    """Return *status* styled with the shared CLI status colors.

    When *monitor* is given and *status* matches one of its halves, style
    with the pair accent (or failure red) and append the outcome glyph.
    Otherwise fall through to :data:`STATUS_COLORS`.
    """
    if monitor is not None and status.casefold() in {
        monitor.start.casefold(),
        monitor.stop.casefold(),
    }:
        style = monitor_status_style(monitor, monitor_state=monitor_state)
        glyph = monitor_status_glyph(monitor_state)
        if glyph:
            return Text(f"{status} {glyph}", style=style)
        return Text(status, style=style)
    color = STATUS_COLORS.get(status, "")
    return Text(status, style=color) if color else Text(status)

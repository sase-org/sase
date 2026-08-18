"""Shared status colors for ``sase agent list`` and ``sase agent restart``."""

from __future__ import annotations

from rich.text import Text

STATUS_COLORS: dict[str, str] = {
    "STARTING": "cyan",
    "RUNNING": "green",
    "QUEUED": "#5F87FF",
    "WAITING": "yellow",
    "DONE": "bright_black",
    "FAILED": "red",
}


def agent_status_text(status: str) -> Text:
    """Return *status* styled with the shared CLI status colors."""
    color = STATUS_COLORS.get(status, "")
    return Text(status, style=color) if color else Text(status)

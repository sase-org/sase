"""Handler for the 'sase monitor' CLI subcommand."""

from __future__ import annotations

from .monitor.dispatcher import handle_monitor_command

__all__ = [
    "handle_monitor_command",
]

"""Shared user-facing failure messages that point to the Log panel."""

from __future__ import annotations

LOG_PANEL_HINT = "press ,L for the log"


def with_log_panel_hint(prefix: str) -> str:
    """Return *prefix* with the shared Log panel hint appended."""
    return f"{prefix} - {LOG_PANEL_HINT}"


__all__ = ["LOG_PANEL_HINT", "with_log_panel_hint"]

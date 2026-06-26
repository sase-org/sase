"""Shared user-facing failure messages that point to the Logs tab."""

from __future__ import annotations

LOG_PANEL_HINT = "see Logs in SASE Admin Center (#)"


def with_log_panel_hint(prefix: str) -> str:
    """Return *prefix* with the shared Logs-tab hint appended."""
    return f"{prefix} - {LOG_PANEL_HINT}"


__all__ = ["LOG_PANEL_HINT", "with_log_panel_hint"]

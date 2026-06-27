"""Shared user-facing failure messages that point to Operations / Logs."""

from __future__ import annotations

LOG_PANEL_HINT = "see Operations / Logs in SASE Admin Center (#)"


def with_log_panel_hint(prefix: str) -> str:
    """Return *prefix* with the shared Operations / Logs hint appended."""
    return f"{prefix} - {LOG_PANEL_HINT}"


__all__ = ["LOG_PANEL_HINT", "with_log_panel_hint"]

"""Shared Rich style palette for notification detail panes.

Every pane the notification modal can render — question, gate, summary —
draws from this one palette so they read as one visual family instead of
independently invented colors.
"""

from __future__ import annotations

PANE_ACCENT = "#00D7FF"
PANE_AWAITING = "#FFD700"
PANE_ANSWERED = "#5FD787"
PANE_WARN = "#FFAF5F"
PANE_ERROR = "#FF5F5F"
PANE_RULE = "#3A526B"
PANE_KEY = "#87D7FF"
PANE_MUTED = "dim"

__all__ = [
    "PANE_ACCENT",
    "PANE_ANSWERED",
    "PANE_AWAITING",
    "PANE_ERROR",
    "PANE_KEY",
    "PANE_MUTED",
    "PANE_RULE",
    "PANE_WARN",
]

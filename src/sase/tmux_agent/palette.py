"""Shared palette for the tmux Agent menu and the ACE panel.

Both surfaces read these constants so accent, chrome, and dim vendor colors
cannot drift independently. Provider accent colors themselves come from the
catalog entries (the registry's CLI status color map).
"""

from __future__ import annotations

TITLE_FG = "#1d202f"
TITLE_BG = "#7aa2f7"
MENU_FG = "#a9b1d6"
MENU_BG = "#1f2335"
VENDOR_FG = "#565f89"
DISABLED_FG = "#565f89"
HIGHLIGHT_FG = "#1d202f"
HIGHLIGHT_BG = "#7aa2f7"
SELECTED_FG = "#7aa2f7"
SELECTED_BG = "#1f2335"
BORDER = "rounded"

__all__ = [
    "BORDER",
    "DISABLED_FG",
    "HIGHLIGHT_BG",
    "HIGHLIGHT_FG",
    "MENU_BG",
    "MENU_FG",
    "SELECTED_BG",
    "SELECTED_FG",
    "TITLE_BG",
    "TITLE_FG",
    "VENDOR_FG",
]

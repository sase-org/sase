"""Exit action requested by the ACE TUI."""

from __future__ import annotations

from enum import StrEnum


class AceExitAction(StrEnum):
    """Action for the ``sase ace`` handler after the TUI exits."""

    QUIT = "quit"
    RESTART_TUI = "restart_tui"
    RESTART_TUI_AND_AXE = "restart_tui_and_axe"


__all__ = ["AceExitAction"]

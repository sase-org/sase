"""Shared display strings for the Command Line screen."""

from __future__ import annotations

COMMAND_LINE_IDLE_HINT = "type to search · ⇥ complete · ; Command Palette"
COMMAND_LINE_INPUT_HINTS = "⏎ run · ⇥ complete · ↑↓ history · ^R search · esc hide"
COMMAND_LINE_MENU_HINTS = "⏎ accept · ↑↓ move · esc normal"
COMMAND_LINE_INDEXING_HINT = "indexing commands…"
COMMAND_LINE_SEARCH_HINT = "history search · ⏎ load · esc exit"
COMMAND_LINE_BLOCK_HINTS = (
    "j/k move · o expand · v pager · K kill · r rerun · e edit · "
    "y copy · p Procs · x remove · i input · esc hide"
)

__all__ = [
    "COMMAND_LINE_BLOCK_HINTS",
    "COMMAND_LINE_IDLE_HINT",
    "COMMAND_LINE_INDEXING_HINT",
    "COMMAND_LINE_INPUT_HINTS",
    "COMMAND_LINE_MENU_HINTS",
    "COMMAND_LINE_SEARCH_HINT",
]

"""Command catalog and palette subsystem for the ace TUI.

Phase 1 deliverables (see ``plans/202604/tui_command_palette.md``):
build a single source-of-truth command catalog for every configurable
keymap (app actions, saved-query digits, built-in mode subcommands, and
custom mode commands) along with pure applicability predicates over a
small ``CommandContext``.

Later phases add the palette modal (Phase 2), live context extraction
and execution wiring (Phase 3), and help/footer unification (Phase 4).
"""

from sase.ace.tui.commands.availability import is_command_available
from sase.ace.tui.commands.catalog import (
    build_command_catalog,
    iter_app_commands,
    iter_digit_commands,
    iter_mode_commands,
)
from sase.ace.tui.commands.types import (
    CommandAvailability,
    CommandCategory,
    CommandContext,
    CommandExecutor,
    CommandPaletteResult,
    CommandSpec,
    CommandTab,
)

__all__ = [
    "CommandAvailability",
    "CommandCategory",
    "CommandContext",
    "CommandExecutor",
    "CommandPaletteResult",
    "CommandSpec",
    "CommandTab",
    "build_command_catalog",
    "is_command_available",
    "iter_app_commands",
    "iter_digit_commands",
    "iter_mode_commands",
]

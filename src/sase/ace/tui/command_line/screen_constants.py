"""Shared display strings for the Command Line screen."""

from __future__ import annotations

from sase.ace.tui.keymaps.app_keymaps import CommandLineKeymaps
from sase.ace.tui.keymaps.defaults import load_builtin_command_line_defaults
from sase.ace.tui.keymaps.display import key_display_name
from sase.ace.tui.keymaps.key_validation import (
    is_unbound_key,
    split_key_alternatives,
)

COMMAND_LINE_MENU_HINTS = "⏎ accept · ↑↓ move · esc normal"
COMMAND_LINE_INDEXING_HINT = "indexing commands…"
COMMAND_LINE_SEARCH_HINT = "history search · ⏎ load · esc exit"

#: Compact arrow glyphs for single-key hints. ``key_display_name`` renders
#: ``up`` verbatim, which is too wide for the one-line key rows.
_ARROW_GLYPHS = {
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
}


def _compact_key_display(binding: str) -> str:
    """Render the first alternative of *binding* for the one-line key rows.

    Returns ``""`` for an ``unbound`` action so callers can omit it.
    """
    if not binding or is_unbound_key(binding):
        return ""
    alternatives = [part for part in split_key_alternatives(binding) if part]
    if not alternatives:
        return ""
    first = alternatives[0]
    glyph = _ARROW_GLYPHS.get(first)
    if glyph is not None:
        return glyph
    return key_display_name(first)


def command_line_input_hints(keymaps: CommandLineKeymaps) -> str:
    """Render the input key row from live key names, skipping unbound."""
    parts = ["⏎ run", "⇥ complete"]
    prev = _compact_key_display(keymaps.history_prev)
    next_key = _compact_key_display(keymaps.history_next)
    if prev and next_key:
        parts.append(f"{prev}{next_key} history")
    elif prev or next_key:
        parts.append(f"{prev or next_key} history")
    search = _compact_key_display(keymaps.history_search)
    if search:
        parts.append(f"{search} search")
    hide = _compact_key_display(keymaps.hide_panel)
    if hide:
        parts.append(f"{hide} hide")
    return " · ".join(parts)


def command_line_block_hints(keymaps: CommandLineKeymaps) -> str:
    """Render the block key row from live key names, skipping unbound."""
    parts = []
    next_key = _compact_key_display(keymaps.block_next)
    prev = _compact_key_display(keymaps.block_prev)
    if next_key and prev:
        parts.append(f"{next_key}/{prev} move")
    elif next_key or prev:
        parts.append(f"{next_key or prev} move")
    for field, label in (
        ("block_toggle_expand", "expand"),
        ("block_pager", "pager"),
        ("block_kill", "kill"),
        ("block_rerun", "rerun"),
        ("block_edit", "edit"),
        ("block_copy_output", "copy"),
        ("block_procs", "Procs"),
        ("block_remove", "remove"),
        ("block_focus_input", "input"),
    ):
        display = _compact_key_display(getattr(keymaps, field))
        if display:
            parts.append(f"{display} {label}")
    hide = _compact_key_display(keymaps.hide_panel)
    if hide:
        parts.append(f"{hide} hide")
    return " · ".join(parts)


def command_line_idle_hint(keymaps: CommandLineKeymaps) -> str:
    """Render the idle signature hint from the live palette-hop key."""
    base = "type to search · ⇥ complete"
    hop = _compact_key_display(keymaps.hop_to_palette)
    if hop:
        return f"{base} · {hop} Command Palette"
    return base


def _bundled_command_line_keymaps() -> CommandLineKeymaps:
    """Return the bundled-default scope used for the static snapshots."""
    return CommandLineKeymaps(**load_builtin_command_line_defaults())


#: Default renderings, kept for initial compose paint and tests. Screens
#: render the builders above with the live registry instead.
COMMAND_LINE_IDLE_HINT = command_line_idle_hint(_bundled_command_line_keymaps())
COMMAND_LINE_INPUT_HINTS = command_line_input_hints(_bundled_command_line_keymaps())
COMMAND_LINE_BLOCK_HINTS = command_line_block_hints(_bundled_command_line_keymaps())

__all__ = [
    "COMMAND_LINE_BLOCK_HINTS",
    "COMMAND_LINE_IDLE_HINT",
    "COMMAND_LINE_INDEXING_HINT",
    "COMMAND_LINE_INPUT_HINTS",
    "COMMAND_LINE_MENU_HINTS",
    "COMMAND_LINE_SEARCH_HINT",
    "command_line_block_hints",
    "command_line_idle_hint",
    "command_line_input_hints",
]

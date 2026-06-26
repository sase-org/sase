"""Formatting helpers for TUI command catalog entries."""

from __future__ import annotations

from sase.ace.tui.keymaps.loader import key_display_name


def format_key_sequence(keys: tuple[str, ...]) -> str:
    """Format a Textual key sequence for palette display.

    Single keys go through ``key_display_name`` directly. Multi-key
    sequences (mode prefix + subkey) are concatenated without a
    separator when both are single chars (``%n``, ``,A``, ``zc``) and
    space-joined otherwise to preserve readability (``Ctrl+D x``).
    """
    if not keys:
        return ""
    parts = [key_display_name(k) for k in keys]
    if all(len(p) == 1 for p in parts):
        return "".join(parts)
    return " ".join(parts)

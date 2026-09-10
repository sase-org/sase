"""Keybinding helpers for the Admin Center Machines pane."""

from __future__ import annotations

from sase.ace.tui.keymaps import (
    MachinesPaneKeymaps,
    key_display_name,
    split_key_alternatives,
)


def primary_key_display(key: str) -> str:
    return key_display_name(split_key_alternatives(key)[0])


def machines_help_bindings(
    keymaps: MachinesPaneKeymaps,
) -> list[tuple[str, str]]:
    """Return effective Machines pane bindings for help surfaces."""

    d = primary_key_display
    return [
        (
            f"{d(keymaps.next_option)} / {d(keymaps.prev_option)}",
            "Move through machines",
        ),
        (d(keymaps.focus_filter), "Filter machines"),
        (d(keymaps.connect_machine), "Open Connect flow"),
        (d(keymaps.check_status), "Check selected machine status"),
        (d(keymaps.repair_machine), "Show repair flow"),
        (d(keymaps.rename_machine), "Show rename command"),
        (d(keymaps.remove_machine), "Show removal command"),
        (d(keymaps.show_agents), "Show Agents for selected machine"),
        (d(keymaps.copy_command), "Copy current action command"),
        (d(keymaps.reload), "Reload machine inventory"),
    ]


__all__ = ["machines_help_bindings", "primary_key_display"]

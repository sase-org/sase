"""Shared fixtures for command-palette modal tests.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_command_palette_modal_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.commands import (
    CommandExecutor,
    CommandPaletteResult,
    CommandSpec,
    build_command_catalog,
    is_command_available,
)
from sase.ace.tui.commands.types import CommandContext
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal


class CommandPaletteTestApp(App[CommandPaletteResult | None]):
    """Minimal app harness for async modal tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def make_spec(
    spec_id: str,
    label: str,
    *,
    key_display: str = "x",
    key_sequence: tuple[str, ...] = ("x",),
    category: str = "Misc",
    aliases: tuple[str, ...] = (),
) -> CommandSpec:
    return CommandSpec(
        id=spec_id,
        label=label,
        key_sequence=key_sequence,
        key_display=key_display,
        category=category,  # type: ignore[arg-type]
        tabs=("changespecs", "agents", "axe"),  # legacy tab id
        executor=CommandExecutor(kind="app_action", action="quit"),
        aliases=aliases,
    )


def live_specs() -> list[CommandSpec]:
    """Build an applicable list from the real catalog for the Patches tab.

    The Phase 3 wiring will pass exactly this kind of pre-filtered list
    in. Using the real catalog keeps the modal honest about real ids.
    """
    reg = load_keymap_registry({})
    catalog = build_command_catalog(reg)
    ctx = CommandContext(tab="changespecs")  # legacy tab id
    return [s for s in catalog if is_command_available(s, ctx)]


def modal_static_text(modal: CommandPaletteModal, selector: str) -> str:
    return str(modal.query_one(selector, Static).render())

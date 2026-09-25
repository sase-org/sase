"""Configurable ``ace.keymaps.command_line`` scope tests.

Covers the keymap-config phase contract: the screen builds its bindings
from the registry scope, the input routes history/palette/Block-nav keys
through the same scope, ``unbound`` actions stay inactive and leave the
hints, and the schema stays in sync with the scope fields.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from sase.ace.tui.keymaps import (
    build_command_line_bindings,
    load_keymap_registry,
)
from sase.ace.tui.keymaps.metadata import _COMMAND_LINE_BINDING_META
from sase.ace.tui.keymaps.scopes import load_command_line_keymaps


def test_command_line_scope_loads_overrides_and_unbound() -> None:
    """User overrides replace defaults; ``unbound`` is a legal value."""
    keymaps = load_command_line_keymaps(
        {"command_line": {"block_next": "ctrl+j", "block_remove": "unbound"}}
    )

    assert keymaps.block_next == "ctrl+j"
    assert keymaps.block_remove == "unbound"
    assert keymaps.block_prev == "k,up"
    assert keymaps.history_prev == "up"


def test_build_command_line_bindings_skips_unbound() -> None:
    """Every screen-bound action is bound by default; unbound drops out."""
    keymaps = load_keymap_registry({}).command_line

    assert {action for action, _ in _COMMAND_LINE_BINDING_META} == {
        binding.action for binding in build_command_line_bindings(keymaps)
    }
    by_action = {
        binding.action: binding.key for binding in build_command_line_bindings(keymaps)
    }
    assert by_action["block_last"] == "G,shift+g"
    assert by_action["block_focus_input"] == "i,a,colon"

    rebound = dataclasses.replace(keymaps, block_remove="unbound")
    rebound_actions = {
        binding.action for binding in build_command_line_bindings(rebound)
    }
    assert "block_remove" not in rebound_actions


def test_command_line_schema_matches_scope_fields() -> None:
    """The config schema accepts exactly the scope's fields."""
    from dataclasses import fields

    from sase.ace.tui.keymaps.app_keymaps import CommandLineKeymaps
    from tests._config_schema_helpers import schema

    properties: dict[str, Any] = schema()["properties"]["ace"]["properties"]["keymaps"][
        "properties"
    ]["command_line"]["properties"]
    assert set(properties) == {field.name for field in fields(CommandLineKeymaps)}


def test_hint_builders_render_live_names_and_omit_unbound() -> None:
    """Hints follow overrides; unbound actions disappear from the rows."""
    from sase.ace.tui.command_line.screen_constants import (
        command_line_block_hints,
        command_line_idle_hint,
        command_line_input_hints,
    )

    keymaps = load_keymap_registry({}).command_line
    assert "↑↓ history" in command_line_input_hints(keymaps)
    assert "^R search" in command_line_input_hints(keymaps)
    assert "esc hide" in command_line_input_hints(keymaps)
    assert "j/k move" in command_line_block_hints(keymaps)
    assert "; Command Palette" in command_line_idle_hint(keymaps)

    rebound = dataclasses.replace(
        keymaps,
        history_search="unbound",
        hop_to_palette="f9",
        block_next="ctrl+j",
        block_remove="unbound",
    )
    input_hints = command_line_input_hints(rebound)
    assert "search" not in input_hints
    assert "↑↓ history" in input_hints
    block_hints = command_line_block_hints(rebound)
    assert "^J/k move" in block_hints
    assert "remove" not in block_hints
    assert "f9 Command Palette" in command_line_idle_hint(rebound)
    assert (
        command_line_idle_hint(dataclasses.replace(keymaps, hop_to_palette="unbound"))
        == "type to search · ⇥ complete"
    )


async def _open_panel(
    page: Any, monkeypatch: pytest.MonkeyPatch, **overrides: str
) -> Any:
    """Open the panel with the store stubbed and scope overrides applied."""
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.screen import CommandLineScreen

    monkeypatch.setattr(screen_module, "read_command_line_store_rows", lambda: [])

    def _mark_loaded(block: Any) -> bool:
        block.tail_loaded = True
        return True

    monkeypatch.setattr(screen_module, "load_block_tail_text", _mark_loaded)
    if overrides:
        scope = page.app._keymap_registry.command_line
        page.app._keymap_registry.command_line = dataclasses.replace(scope, **overrides)
    page.app.action_open_command_line()
    await page.expect_modal("CommandLineScreen")
    screen = page.app.screen
    assert isinstance(screen, CommandLineScreen)
    await page.pause()
    return screen


def _to_normal(screen: Any) -> Any:
    from sase.ace.tui.command_line.input import CommandLineInput

    widget = screen.query_one(CommandLineInput)
    widget._enter_normal_mode()
    return widget


async def test_panel_action_override_takes_effect_in_mounted_pilot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rebound history key walks on the new key and ignores the old one."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen
    from sase.history import command_line as history_store

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_panel(page, monkeypatch, history_prev="ctrl+b")
            widget = screen.query_one(CommandLineInput)
            screen._history.entries = [
                history_store.CommandLineHistoryEntry(
                    line="bead list --status open", last_used="260101_000001"
                )
            ]
            widget.set_line("bead")
            await page.pause()

            await page.press("ctrl+b")
            assert widget.text == "bead list --status open"

            widget.set_line("bead")
            await page.pause()
            await page.press("up")
            assert widget.text == "bead"
            assert isinstance(page.app.screen, CommandLineScreen)


async def test_block_nav_override_takes_effect_in_mounted_pilot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rebound Block-nav key moves; the old key falls through to vim."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_panel(page, monkeypatch, block_next="ctrl+j")
            session = command_line_session_for(page.app)
            for line in ("bead list", "bead show sase-1"):
                session.add_block(line)
            screen.refresh_transcript()
            await page.pause()

            rebound = screen._bindings.key_to_bindings.get("ctrl+j", ())
            assert any(binding.action == "block_next" for binding in rebound)

            _to_normal(screen)
            assert screen.handle_block_nav_key("g") is True
            assert session.selected_block() is session.blocks[0]

            await page.press("j")
            await page.pause()
            assert session.selected_block() is session.blocks[0]

            await page.press("ctrl+j")
            await page.pause()
            assert session.selected_block() is session.blocks[1]


async def test_unbound_actions_are_inactive_and_missing_from_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``unbound`` keys keep vim meanings and vanish from the key rows."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.chrome import CommandLineFrame
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_panel(
                page,
                monkeypatch,
                block_remove="unbound",
                history_search="unbound",
            )
            session = command_line_session_for(page.app)
            for line in ("bead list", "bead show sase-1"):
                session.add_block(line)
            screen.refresh_transcript()
            await page.pause()

            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead lisst")
            widget.move_cursor((0, len("bead lis")))
            _to_normal(screen)
            await page.pause()
            assert screen.handle_block_nav_key("j") is True

            frame = screen.query_one(CommandLineFrame)
            assert "remove" not in frame.bottom_label.plain

            await page.press("x")
            assert widget.text == "bead list"
            assert [block.line for block in session.blocks] == [
                "bead list",
                "bead show sase-1",
            ]

            screen.focus_input()
            await page.pause()
            assert "search" not in frame.bottom_label.plain
            await page.press("ctrl+r")
            await page.pause()
            assert screen._history_search_active is False
            assert isinstance(page.app.screen, CommandLineScreen)


def test_compact_key_display_renders_esc_and_caret() -> None:
    """The one-line rows use ``esc`` and ``^R`` instead of long names."""
    from sase.ace.tui.command_line.screen_constants import _compact_key_display

    assert _compact_key_display("escape") == "esc"
    assert _compact_key_display("ctrl+r") == "^R"
    assert _compact_key_display("ctrl+j") == "^J"
    assert _compact_key_display("up") == "↑"
    assert _compact_key_display("down") == "↓"
    assert _compact_key_display("unbound") == ""
    assert _compact_key_display("semicolon") == ";"


def test_menu_hints_leave_the_menu() -> None:
    """The menu row no longer claims Esc enters NORMAL mode."""
    from sase.ace.tui.command_line.screen_constants import COMMAND_LINE_MENU_HINTS

    assert COMMAND_LINE_MENU_HINTS == "⏎ accept · ↑↓ move · esc leave"


async def test_menu_moves_with_fixed_arrows_when_history_rebound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rebound history keys never steer the menu; ``↑``/``↓`` still do."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen
    from sase.history import command_line as history_store

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_panel(page, monkeypatch, history_prev="ctrl+b")
            widget = screen.query_one(CommandLineInput)
            assert isinstance(screen, CommandLineScreen)
            widget.set_line("bead ")
            await page.pause()
            screen._popup_state.reset(
                [
                    {"insert_text": "list ", "display": "list", "match_runs": []},
                    {"insert_text": "show ", "display": "show", "match_runs": []},
                ],
                typed_text="bead ",
                replace_start=len("bead "),
                replace_end=len("bead "),
            )
            screen._popup_state.on_tab()
            assert screen._popup_state.menu_active is True

            await page.press("down")
            assert screen._popup_state.index == 1
            await page.press("up")
            assert screen._popup_state.index == 0

            await page.press("ctrl+b")
            assert screen._popup_state.index == 0
            assert screen._popup_state.menu_active is True

            await page.press("escape")
            assert screen._popup_state.menu_active is False
            screen._history.entries = [
                history_store.CommandLineHistoryEntry(
                    line="bead list --status open", last_used="260101_000001"
                )
            ]
            widget.set_line("bead")
            await page.pause()
            await page.press("ctrl+b")
            assert widget.text == "bead list --status open"
            widget.set_line("bead")
            await page.pause()
            await page.press("up")
            assert widget.text == "bead"

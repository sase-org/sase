"""Block navigation and edit tests for transcript blocks.

NORMAL-mode ``j``/``k``/``g``/``G`` movement, expand/remove, edit, and
rerun keys for the ``:`` Command Line transcript.
"""

from __future__ import annotations

import pytest

from tests.ace.tui.command_line._transcript_blocks_shared import (
    open_seeded_panel,
    to_normal,
)

__all__ = [
    "test_block_keys_select_move_and_switch_hints",
    "test_e_loads_line_into_input",
    "test_forwarded_k_key_enters_transcript_selection",
    "test_o_toggles_expand_and_x_removes",
    "test_r_reruns_and_R_is_limited_to_declined_blocks",
    "test_unselected_normal_input_keeps_vim_editing_and_redo",
]


async def test_block_keys_select_move_and_switch_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``j``/``k``/``g``/``G`` move the bar and swap the footer hints."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.chrome import CommandLineFrame
    from sase.ace.tui.command_line.screen import (
        COMMAND_LINE_BLOCK_HINTS,
        COMMAND_LINE_INPUT_HINTS,
    )
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature", patches=[make_patch()], size=(200, 40)
        ) as page:
            screen = await open_seeded_panel(
                page, monkeypatch, ["bead list", "bead show sase-1"]
            )
            to_normal(screen)
            assert screen.handle_block_nav_key("j") is True
            session = command_line_session_for(page.app)
            selected = session.selected_block()
            assert selected is session.blocks[-1]
            assert selected is not None and selected.unseen is False
            frame = screen.query_one(CommandLineFrame)
            assert "o expand" in frame.bottom_label.plain
            assert COMMAND_LINE_BLOCK_HINTS in frame.bottom_label.plain
            screen.handle_block_nav_key("k")
            assert session.selected_block() is session.blocks[0]
            screen.handle_block_nav_key("G")
            assert session.selected_block() is session.blocks[-1]
            screen.handle_block_nav_key("g")
            assert session.selected_block() is session.blocks[0]
            screen.focus_input()
            assert session.selected_block() is None
            assert COMMAND_LINE_INPUT_HINTS in frame.bottom_label.plain


async def test_forwarded_k_key_enters_transcript_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A NORMAL-mode ``k`` in an unselected input enters the transcript."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(
                page, monkeypatch, ["bead list", "bead show sase-1"]
            )
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead list --status open")
            await page.pause()
            widget._enter_normal_mode()
            await page.pause()
            await page.press("k")
            await page.pause()
            session = command_line_session_for(page.app)
            assert session.selected_block() is session.blocks[-1]
            assert widget.text == "bead list --status open"


async def test_unselected_normal_input_keeps_vim_editing_and_redo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only k/Up enter blocks; x and Ctrl-R retain their vim meanings."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(page, monkeypatch, ["bead list"])
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead lisst")
            widget.move_cursor((0, len("bead lis")))
            widget._enter_normal_mode()
            await page.pause()

            await page.press("x")
            assert widget.text == "bead list"
            assert command_line_session_for(page.app).selected_block() is None

            await page.press("u", "ctrl+r")
            assert widget.text == "bead list"
            assert screen._history_search_active is False


async def test_o_toggles_expand_and_x_removes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``o`` expands/collapses and ``x`` removes the selected block."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(
                page, monkeypatch, ["bead list", "bead show sase-1"]
            )
            session = command_line_session_for(page.app)
            assert screen.handle_block_nav_key("bogus") is False
            screen.handle_block_nav_key("j")
            assert screen.handle_block_nav_key("o") is True
            expanded = session.selected_block()
            assert expanded is not None and expanded.expanded is True
            screen.handle_block_nav_key("o")
            collapsed = session.selected_block()
            assert collapsed is not None and collapsed.expanded is False
            assert screen.handle_block_nav_key("x") is True
            assert [block.line for block in session.blocks] == ["bead list"]
            assert session.selected_block() is session.blocks[0]


async def test_e_loads_line_into_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``e`` loads the selected command back into the input for editing."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(page, monkeypatch, ["bead show sase-9"])
            screen.handle_block_nav_key("j")
            assert screen.handle_block_nav_key("e") is True
            assert screen.query_one(CommandLineInput).text == "bead show sase-9"
            assert screen.selected_block() is None


async def test_r_reruns_and_R_is_limited_to_declined_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``R`` appends ``-y`` only for blocks whose confirmation was declined."""
    from types import SimpleNamespace as _NS
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.session import command_line_session_for

    counter = {"n": 0}

    def _fake_submit(**kwargs: object) -> object:
        counter["n"] += 1
        return _NS(proc_id=f"proc-rerun-{counter['n']}")

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        mock_patch.object(screen_module, "submit_in_worker", side_effect=_fake_submit),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            screen.handle_block_nav_key("j")
            assert screen.handle_block_nav_key("r") is True
            assert [block.line for block in session.blocks] == [
                "bead list",
                "bead list",
            ]
            assert session.selected_block() is session.blocks[-1]
            await page.pause_until_cpu_idle()
            assert session.blocks[-1].proc_id == "proc-rerun-1"
            screen.handle_block_nav_key("R")
            assert len(session.blocks) == 2

            session.blocks[-1].declined = True
            screen.handle_block_nav_key("R")
            assert len(session.blocks) == 3
            assert session.blocks[-1].line == "bead list -y"

"""Block action tests for transcript blocks.

Pager, Procs focus, copy, kill, jump-focus, and real-key rerun/insert
keys for the ``:`` Command Line transcript.
"""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.command_line.session import CommandLineBlock
from tests.ace.tui.command_line._transcript_blocks_shared import open_seeded_panel

__all__ = [
    "test_K_warns_when_finished_and_confirms_when_running",
    "test_p_opens_procs_with_focus_target",
    "test_procs_jump_focus_selects_block_on_open",
    "test_real_R_press_reruns_declined_and_notices_otherwise",
    "test_real_i_a_colon_presses_return_to_insert",
    "test_v_loads_an_unloaded_tail_then_opens_pager",
    "test_v_opens_pager_for_selected_block",
    "test_y_and_Y_copy_output_and_command",
]


async def test_v_opens_pager_for_selected_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``v`` pushes the pager with the block's full output."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.pager.screen import PagerScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            session.blocks[0].tail_text = "line one\nline two\n"
            session.blocks[0].tail_loaded = True
            screen.handle_block_nav_key("j")
            assert screen.handle_block_nav_key("v") is True
            await page.expect_modal("PagerScreen")
            assert isinstance(page.app.screen, PagerScreen)


async def test_v_loads_an_unloaded_tail_then_opens_pager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``v`` resumes on the app loop and opens the pager after a tail load."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.pager.screen import PagerScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            block = session.blocks[0]
            block.proc_id = "proc-unloaded-tail"
            block.tail_loaded = False

            def _load_tail(loaded: CommandLineBlock) -> bool:
                loaded.tail_text = "loaded after v"
                loaded.tail_loaded = True
                return True

            monkeypatch.setattr(screen_module, "load_block_tail_text", _load_tail)
            screen.handle_block_nav_key("j")
            assert screen.handle_block_nav_key("v") is True
            await page.expect_modal("PagerScreen")
            assert isinstance(page.app.screen, PagerScreen)
            assert page.app.screen.document.sections[0].body.plain == "loaded after v"


async def test_p_opens_procs_with_focus_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``p`` opens Admin Center → Procs with the proc selected."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            session.blocks[0].proc_id = "proc-focus-1"
            screen.handle_block_nav_key("j")
            calls: list[tuple[Any, Any]] = []
            monkeypatch.setattr(
                page.app,
                "_open_config_center",
                lambda tab, **kwargs: calls.append((tab, kwargs)),
            )
            assert screen.handle_block_nav_key("p") is True
            assert calls == [("procs", {"proc_focus_target": "proc-focus-1"})]


async def test_y_and_Y_copy_output_and_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``y`` copies the output and ``Y`` copies the command line."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            session.blocks[0].tail_text = "some output\n"
            screen.handle_block_nav_key("j")
            copied: list[tuple[Any, Any]] = []

            def _stub_copy(owner: Any, value: Any, **kwargs: Any) -> None:
                copied.append((value, kwargs))

            monkeypatch.setattr(
                "sase.ace.tui.actions.clipboard.schedule_copy_delivery",
                _stub_copy,
            )
            assert screen.handle_block_nav_key("y") is True
            assert screen.handle_block_nav_key("Y") is True
            assert copied[0][0] == "some output\n"
            assert copied[1][0] == "bead list"


async def test_K_warns_when_finished_and_confirms_when_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``K`` warns on finished blocks and confirms (stubbed kill) on running."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            session.blocks[0].status = "success"
            screen.handle_block_nav_key("j")
            notices: list[str] = []
            monkeypatch.setattr(
                page.app, "notify", lambda message, **kwargs: notices.append(message)
            )
            assert screen.handle_block_nav_key("K") is True
            assert notices == ["Proc already finished"]

            session.blocks[0].status = "running"
            session.blocks[0].proc_id = "proc-kill-1"
            killed: list[tuple[str, int]] = []

            def _stub_kill(proc_id: str) -> str | None:
                import threading

                killed.append((proc_id, threading.get_ident()))
                return None

            monkeypatch.setattr(
                "sase.ace.tui.modals.procs_store_rows.kill_store_task",
                _stub_kill,
            )
            pushed: dict[str, Any] = {}
            orig_push = page.app.push_screen

            def _capture(pushed_screen: Any, callback: Any = None) -> Any:
                pushed["callback"] = callback
                return orig_push(pushed_screen, callback)

            monkeypatch.setattr(page.app, "push_screen", _capture)
            assert screen.handle_block_nav_key("K") is True
            await page.expect_modal("ConfirmActionModal")
            pushed["callback"](True)
            assert killed == []
            await page.pause_until_cpu_idle()
            assert [proc_id for proc_id, _ in killed] == ["proc-kill-1"]
            import threading

            assert killed[0][1] != threading.get_ident()


async def test_procs_jump_focus_selects_block_on_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Procs ``⏎`` jump opens the panel with that block selected."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            from sase.ace.tui.command_line import screen as screen_module

            monkeypatch.setattr(
                screen_module, "read_command_line_store_rows", lambda: []
            )
            session = command_line_session_for(page.app)
            block = session.add_block("bead show p1")
            block.proc_id = "proc-jump-1"
            block.status = "success"
            session.focus_block_proc_id = "proc-jump-1"
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            await page.pause()
            assert session.selected_block() is block


async def test_real_R_press_reruns_declined_and_notices_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real ``R`` reruns declined blocks and warns on other blocks."""
    from types import SimpleNamespace as _NS
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.session import command_line_session_for

    counter = {"n": 0}

    def _fake_submit(**kwargs: object) -> object:
        counter["n"] += 1
        return _NS(proc_id=f"proc-real-r-{counter['n']}")

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        mock_patch.object(screen_module, "submit_in_worker", side_effect=_fake_submit),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            widget = screen.query_one(CommandLineInput)
            widget._enter_normal_mode()
            await page.pause()
            await page.press("k")
            await page.pause()
            assert session.selected_block() is session.blocks[0]

            notices: list[str] = []
            monkeypatch.setattr(
                page.app, "notify", lambda message, **kwargs: notices.append(message)
            )
            await page.press("R")
            await page.pause()
            assert notices == ["Rerun with -y is available for declined confirmations"]
            assert len(session.blocks) == 1

            session.blocks[-1].declined = True
            await page.press("R")
            await page.pause_until_cpu_idle()
            assert len(session.blocks) == 2
            assert session.blocks[-1].line == "bead list -y"


async def test_real_i_a_colon_presses_return_to_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real ``i``/``a``/``:`` presses leave the selection for INSERT mode."""
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
            screen = await open_seeded_panel(page, monkeypatch, ["bead show sase-9"])
            session = command_line_session_for(page.app)
            widget = screen.query_one(CommandLineInput)

            for key in ("i", "a", "colon"):
                widget._enter_normal_mode()
                await page.pause()
                await page.press("k")
                await page.pause()
                assert session.selected_block() is not None
                await page.press(key)
                await page.pause()
                assert session.selected_block() is None
                assert getattr(widget, "_vim_mode", "insert") == "insert"

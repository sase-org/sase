"""Mounted-panel pilot tests for the ``:`` Command Line.

Escape semantics, draft persistence across hide/reopen, the submit paths
through the real screen, and grammar-loader refresh behavior.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from sase.history import command_line as history_store

__all__ = [
    "test_empty_panel_escape_follows_the_hide_panel_binding",
    "test_empty_panel_semicolon_hops_to_palette_and_back",
    "test_grammar_loader_notifies_every_pending_screen_callback",
    "test_grammar_readiness_through_real_loader_with_in_process_grammar",
    "test_grammar_ready_refreshes_open_empty_panel_without_a_keystroke",
    "test_panel_escape_keeps_draft_across_reopen",
    "test_real_input_history_filters_prefix_and_resets_new_walk",
    "test_real_input_right_accepts_ghost_at_line_end",
    "test_submit_failure_turns_block_red_and_restores_line",
    "test_submit_happy_path_settles_on_exit_completion",
]


# -- pilot tests: Escape, draft, submit paths ------------------------------------


async def test_panel_escape_keeps_draft_across_reopen() -> None:
    """Esc hides the panel and reopening restores the unsent draft."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            screen.query_one(CommandLineInput).set_line("bead list")
            await page.pause()
            await page.press("escape")
            await page.expect_modal("CommandLineScreen")
            await asyncio.wait_for(page.press("escape"), timeout=1.0)
            await page.expect_no_modal()
            assert screen.is_attached is False
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            reopened = page.app.screen
            assert isinstance(reopened, CommandLineScreen)
            assert reopened.query_one(CommandLineInput).text == "bead list"


async def test_empty_panel_semicolon_hops_to_palette_and_back() -> None:
    """The empty-line ``;`` hop queues the palette without wedging the panel."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen
    from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            old_screen = page.app.screen
            assert isinstance(old_screen, CommandLineScreen)

            await asyncio.wait_for(page.press("semicolon"), timeout=1.0)
            await page.expect_modal("CommandPaletteModal")
            assert old_screen.is_attached is False

            await page.press("colon")
            await page.expect_modal("CommandLineScreen")
            reopened = page.app.screen
            assert isinstance(reopened, CommandLineScreen)
            assert reopened.query_one(CommandLineInput).text == ""


async def test_empty_panel_escape_follows_the_hide_panel_binding() -> None:
    """A rebound hide key leaves empty-line Escape to vim's INSERT handling."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.keymaps import load_keymap_registry

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app._keymap_registry = load_keymap_registry(
                {"keymaps": {"command_line": {"hide_panel": "f8"}}}
            )
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")

            await asyncio.wait_for(page.press("escape"), timeout=1.0)
            await page.expect_modal("CommandLineScreen")


async def test_grammar_loader_notifies_every_pending_screen_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Panels reopened during one grammar load each receive the settled callback."""
    from collections.abc import Coroutine
    from typing import Any

    from sase.ace.tui.command_line import grammar

    workers: list[Coroutine[Any, Any, None]] = []

    def _run_worker(coro: Coroutine[Any, Any, None], **_kwargs: object) -> None:
        workers.append(coro)

    app = SimpleNamespace(run_worker=_run_worker)
    callbacks: list[str] = []
    monkeypatch.setattr(grammar, "_load_command_line_grammar_sync", lambda: object())

    assert (
        grammar.ensure_command_line_grammar_loaded(
            app, on_ready=lambda: callbacks.append("first-open")
        )
        is False
    )
    assert (
        grammar.ensure_command_line_grammar_loaded(
            app, on_ready=lambda: callbacks.append("reopen")
        )
        is False
    )
    assert len(workers) == 1

    await workers[0]

    assert callbacks == ["first-open", "reopen"]
    assert grammar.ensure_command_line_grammar_loaded(app) is True


async def test_grammar_ready_refreshes_open_empty_panel_without_a_keystroke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reopen during grammar loading refreshes when the shared worker lands."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import grammar
    from sase.ace.tui.command_line.screen import CommandLineScreen
    from sase.ace.tui.command_line.screen_constants import (
        COMMAND_LINE_IDLE_HINT,
        COMMAND_LINE_INDEXING_HINT,
    )
    from textual.widgets import Static

    release_grammar = threading.Event()

    def _wait_for_grammar_release() -> object:
        assert release_grammar.wait(timeout=5.0)
        return object()

    monkeypatch.setattr(
        grammar, "_load_command_line_grammar_sync", _wait_for_grammar_release
    )
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            try:
                page.app.action_open_command_line()
                await page.expect_modal("CommandLineScreen")
                first = page.app.screen
                assert isinstance(first, CommandLineScreen)
                await page.wait_for(
                    lambda _state: page.app._command_line_grammar_loading is True
                )

                # The escape press races a blocked grammar worker; 1s is too
                # tight under parallel-check load (observed TimeoutError on a
                # loaded gate while isolated reruns pass in ~2s).
                await asyncio.wait_for(page.press("escape"), timeout=5.0)
                await page.expect_no_modal()
                assert first.is_attached is False

                page.app.action_open_command_line()
                await page.expect_modal("CommandLineScreen")
                reopened = page.app.screen
                assert isinstance(reopened, CommandLineScreen)
                hint = reopened.query_one("#command-line-hint-row", Static)
                reopened._show_indexing(has_text=True)
                assert str(hint.render()) == COMMAND_LINE_INDEXING_HINT

                release_grammar.set()
                await page.wait_for(
                    lambda _state: page.app._command_line_grammar_loading is False
                )
                await page.pause()

                assert str(hint.render()) == COMMAND_LINE_IDLE_HINT
                assert (
                    reopened.query_one("#command-line-popup-footer", Static).display
                    is False
                )
            finally:
                release_grammar.set()


async def test_submit_failure_turns_block_red_and_restores_line() -> None:
    """A failed submit shows a red block and puts the line back in the input."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen
    from sase.ace.tui.command_line.session import command_line_session_for

    def _boom(**kwargs: object) -> object:
        raise RuntimeError("no supervisor in test")

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        mock_patch.object(screen_module, "submit_in_worker", side_effect=_boom),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            screen.query_one(CommandLineInput).set_line("bead list")
            await page.pause()
            screen.submit_current_line()
            await page.pause_until_cpu_idle()
            session = command_line_session_for(page.app)
            assert len(session.blocks) == 1
            assert session.blocks[0].status == "submit_failed"
            assert screen.query_one(CommandLineInput).text == "bead list"


async def test_submit_happy_path_settles_on_exit_completion() -> None:
    """A submitted proc attaches to its block and settles on exit."""
    from types import SimpleNamespace as _NS
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.exits import deliver_command_line_exit
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen
    from sase.ace.tui.command_line.session import command_line_session_for

    def _fake_submit(**kwargs: object) -> object:
        return _NS(proc_id="proc-test-submit-1")

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        mock_patch.object(screen_module, "submit_in_worker", side_effect=_fake_submit),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            screen.query_one(CommandLineInput).set_line("bead list")
            await page.pause()
            screen.submit_current_line()
            await page.pause_until_cpu_idle()
            session = command_line_session_for(page.app)
            assert len(session.blocks) == 1
            block = session.blocks[0]
            assert block.status == "running"
            assert block.proc_id == "proc-test-submit-1"
            assert screen.query_one(CommandLineInput).text == ""
            completion = _NS(proc_id="proc-test-submit-1", exit_code=0, status="done")
            assert deliver_command_line_exit(page.app, completion) is True
            assert block.status == "success"
            assert (
                deliver_command_line_exit(
                    page.app, _NS(proc_id="proc-unknown", exit_code=0, status="done")
                )
                is False
            )


async def test_real_input_history_filters_prefix_and_resets_new_walk() -> None:
    """``↑``/``↓`` filter by prefix and a new walk starts from the newest."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            widget = screen.query_one(CommandLineInput)
            screen._history.entries = [
                history_store.CommandLineHistoryEntry(
                    line="git status", last_used="260101_000005"
                ),
                history_store.CommandLineHistoryEntry(
                    line="bead show sase-3", last_used="260101_000004"
                ),
                history_store.CommandLineHistoryEntry(
                    line="bead show sase-2", last_used="260101_000003"
                ),
                history_store.CommandLineHistoryEntry(
                    line="agent wait athena.1", last_used="260101_000002"
                ),
                history_store.CommandLineHistoryEntry(
                    line="bead list", last_used="260101_000001"
                ),
            ]
            widget.set_line("bead")
            await page.pause()

            await page.press("up")
            assert widget.text == "bead show sase-3"
            await page.press("up")
            assert widget.text == "bead show sase-2"
            await page.press("up")
            assert widget.text == "bead list"
            await page.press("down")
            assert widget.text == "bead show sase-2"

            # An edit back to the same prefix starts a new walk at the newest.
            widget.set_line("bead")
            await page.pause()
            await page.press("up")
            assert widget.text == "bead show sase-3"

            widget.set_line("git")
            await page.pause()
            await page.press("up")
            assert widget.text == "git status"

            widget.set_line("bead")
            await page.pause()
            await page.press("up")
            assert widget.text == "bead show sase-3"


async def test_real_input_right_accepts_ghost_at_line_end() -> None:
    """``→`` at the end of the line accepts the ghost remainder."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            widget = screen.query_one(CommandLineInput)
            screen._history.entries = [
                history_store.CommandLineHistoryEntry(
                    line="bead list --status open", last_used="260101_000001"
                )
            ]
            widget.set_line("bead")
            await page.pause()
            screen._update_ghost()
            assert widget.suggestion == " list --status open"
            await page.press("right")
            assert widget.text == "bead list --status open"


async def test_grammar_readiness_through_real_loader_with_in_process_grammar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The panel refreshes via the loader worker, not a direct callback."""
    import json
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import grammar as grammar_module
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen

    try:
        from sase.completion.build import build_spec
        from sase.completion.command_line_grammar import CommandLineGrammar

        handle = CommandLineGrammar.from_spec_json(json.dumps(build_spec().to_json()))
    except AttributeError:
        pytest.skip("installed sase_core_rs wheel predates CommandLineGrammar")
    monkeypatch.setattr(
        grammar_module, "_load_command_line_grammar_sync", lambda: handle
    )
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            assert getattr(page.app, "_command_line_grammar", None) is None
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            await page.wait_for(
                lambda _state: (
                    getattr(page.app, "_command_line_grammar", None) is not None
                )
            )
            await page.pause()
            assert grammar_module.command_line_grammar_for(page.app) is not None
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead ")
            await page.pause()
            assert grammar_module.resolve_command_line(page.app, "bead ", 5) is not None

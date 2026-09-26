"""Panel-shell tests for the ``:`` Command Line.

Covers the panel-shell phase contract: both flag states, Escape semantics,
draft persistence across hide/reopen, history locking and LRU, leading
``sase `` stripping, the submit happy path and failure path, and pump-free
tail polling.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.command_line.block_render import (
    block_header_right,
    collapsed_body_lines,
    gutter_glyph,
    render_block_output,
    sanitize_block_output,
)
from sase.ace.tui.command_line.context import (
    CommandLineContext,
    working_context_chip,
)
from sase.ace.tui.command_line.history import CommandLineHistory
from sase.ace.tui.command_line.session import (
    COMMAND_LINE_MAX_BLOCKS,
    CommandLineSession,
    command_line_session_for,
    strip_implicit_prefix,
    tokenize_command_line,
)
from sase.ace.tui.command_line.submit import (
    apply_exit_completion,
    apply_local_block,
    apply_submit_failure,
    apply_submit_success,
    prepare_submit,
)
from sase.ace.tui.commands.availability import is_command_available
from sase.ace.tui.commands.types import CommandContext, CommandExecutor, CommandSpec
from sase.history import command_line as history_store


@pytest.fixture
def history_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the history store to a temp file."""
    path = tmp_path / "command_line_history.json"
    monkeypatch.setattr(history_store, "_history_file_override", path)
    return path


def _command_line_spec() -> CommandSpec:
    return CommandSpec(
        id="app.open_command_line",
        label="Command Line",
        key_sequence=("unbound",),
        key_display="",
        category="Misc",
        tabs=("artifacts", "agents", "services"),
        executor=CommandExecutor(kind="app_action", action="open_command_line"),
    )


# -- tokenize / strip --------------------------------------------------------


def test_tokenize_strips_implicit_sase_prefix() -> None:
    """A typed or pasted leading ``sase `` is stripped at once."""
    assert tokenize_command_line("sase bead list") == ["bead", "list"]
    assert tokenize_command_line("sase") is None
    assert tokenize_command_line("bead show sase-1") == ["bead", "show", "sase-1"]
    assert tokenize_command_line("  ") is None
    assert tokenize_command_line('bead show "unterminated') is None


def test_strip_implicit_prefix_keeps_other_text_verbatim() -> None:
    """Only one leading ``sase `` word is stripped; the rest is untouched."""
    assert strip_implicit_prefix("sase bead list") == "bead list"
    assert strip_implicit_prefix("sase") == ""
    assert strip_implicit_prefix("bead sase list") == "bead sase list"


# -- landed states (flag removed) --------------------------------------------


def test_palette_row_always_visible_after_land() -> None:
    """The catalog row is available unconditionally after the flip."""
    assert is_command_available(_command_line_spec(), CommandContext()) is True


def test_palette_moved_tip_marker_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one-time flip tip marker persists under ``sase_home``."""
    from sase.ace.tui.command_line import palette_moved_tip as tip

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    assert tip.has_shown_palette_moved_tip() is False
    assert "Command Palette moved to" in tip.COMMAND_LINE_PALETTE_MOVED_TIP
    assert "`;`" in tip.COMMAND_LINE_PALETTE_MOVED_TIP
    tip.mark_palette_moved_tip_shown()
    assert tip.has_shown_palette_moved_tip() is True


def test_action_pushes_command_line_screen_unconditionally() -> None:
    """``open_command_line`` pushes the panel with no flag gate."""
    from sase.ace.tui.actions.base import BaseActionsMixin
    from sase.ace.tui.command_line.screen import CommandLineScreen

    pushed: list[object] = []
    stub = SimpleNamespace(
        notify=lambda message, **kwargs: None,
        push_screen=lambda screen, **kwargs: pushed.append(screen),
    )
    BaseActionsMixin.action_open_command_line(stub)  # type: ignore[arg-type]
    assert len(pushed) == 1
    assert isinstance(pushed[0], CommandLineScreen)


# -- session -------------------------------------------------------------------


def test_session_caps_blocks_at_200() -> None:
    """The transcript keeps at most 200 blocks."""
    session = CommandLineSession()
    for index in range(COMMAND_LINE_MAX_BLOCKS + 10):
        session.add_block(f"bead show sase-{index}")
    assert len(session.blocks) == COMMAND_LINE_MAX_BLOCKS
    assert session.blocks[0].line == "bead show sase-10"


def test_clear_transcript_keeps_running_blocks() -> None:
    """``ctrl+l`` drops finished blocks; running procs are untouched."""
    session = CommandLineSession()
    running = session.add_block("agent wait x")
    running.status = "running"
    done = session.add_block("bead list")
    done.status = "success"
    session.clear_transcript()
    assert session.blocks == [running]


def test_session_defaults_for_reopen() -> None:
    """A fresh session holds an empty draft, no pin, and no restore yet."""
    session = CommandLineSession()
    assert session.draft == ""
    assert session.cwd_pin is None
    assert session.restored is False
    assert session.history_cursor is None


def test_session_for_app_is_stable() -> None:
    """The app-held session is created once and reused."""
    app = SimpleNamespace()
    first = command_line_session_for(app)
    first.draft = "bead list"
    assert command_line_session_for(app) is first
    assert command_line_session_for(app).draft == "bead list"


# -- history store --------------------------------------------------------------


def test_record_dedups_repeats_with_count(history_file: Path) -> None:
    """Repeat submissions bump ``count`` instead of duplicating rows."""
    del history_file
    with history_store.locked_command_line_history():
        history_store.record_command_line("bead list", cwd="/a", project="sase")
        history_store.record_command_line("bead list", cwd="/a", project="sase")
    entries = history_store.load_command_line_history()
    assert len(entries) == 1
    assert entries[0].count == 2
    assert entries[0].line == "bead list"


def test_history_enforces_lru_cap(
    history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store keeps the newest entries up to its LRU cap."""
    del history_file
    monkeypatch.setattr(history_store, "COMMAND_LINE_HISTORY_LIMIT", 20)
    entries = [
        history_store.CommandLineHistoryEntry(
            line=f"bead show sase-{index:02d}",
            last_used=f"260101_0000{index:02d}",
        )
        for index in range(25)
    ]
    assert history_store._save_command_line_history(entries) is True
    loaded = history_store.load_command_line_history()
    assert len(loaded) == 20
    assert loaded[0].line == "bead show sase-24"
    assert all(entry.line != "bead show sase-00" for entry in loaded)


def test_history_lock_serializes_concurrent_records(history_file: Path) -> None:
    """Concurrent recorders under the lock lose no submissions."""
    del history_file

    def _record(index: int) -> None:
        with history_store.locked_command_line_history():
            history_store.record_command_line(f"agent show agent-{index}")

    threads = [threading.Thread(target=_record, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(history_store.load_command_line_history()) == 8


def test_prefix_walk_prefers_same_cwd(history_file: Path) -> None:
    """``↑``/``↓`` walk prefix matches with same-cwd entries first."""
    del history_file
    history = CommandLineHistory()
    history.entries = [
        history_store.CommandLineHistoryEntry(
            line="bead list", cwd="/other", last_used="260101_000002"
        ),
        history_store.CommandLineHistoryEntry(
            line="bead list --status open", cwd="/here", last_used="260101_000001"
        ),
    ]
    assert history.walk("bead", direction=1, cwd="/here") == "bead list --status open"
    history.anchor = "bead"
    history.cursor = None
    assert history.walk("bead", direction=1, cwd="/here") == "bead list --status open"


def test_ghost_prefers_same_cwd(history_file: Path) -> None:
    """Ghost text completes from the most recent same-cwd prefix match."""
    del history_file
    history = CommandLineHistory()
    history.entries = [
        history_store.CommandLineHistoryEntry(
            line="bead list", cwd="/here", last_used="260101_000002"
        ),
    ]
    assert history.ghost("bead", cwd="/here") == " list"
    assert history.ghost("bead list", cwd="/here") == ""
    assert history.ghost("zzz", cwd="/here") == ""


async def test_real_input_walks_history_and_never_pastes_mid_line_ghost() -> None:
    """The mounted input owns inactive arrows and clears ghosts off line end."""
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

            await page.press("up")
            assert widget.text == "bead list --status open"
            await page.press("down")
            assert widget.text == "bead"

            screen._update_ghost()
            assert widget.suggestion == " list --status open"
            await page.press("left")
            assert widget.suggestion == ""
            await page.press("right")
            assert widget.text == "bead"


async def test_real_input_ctrl_f_accepts_only_an_active_menu() -> None:
    """Ctrl-F keeps forward-char behavior until the mounted menu is active."""
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

            widget.set_line("bead")
            widget.move_cursor((0, 0))
            await page.press("ctrl+f")
            assert widget.text == "bead"
            assert widget.cursor_location == (0, 1)

            widget.set_line("bead ")
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

            await page.press("ctrl+f")
            assert widget.text == "bead list "
            assert screen._popup_state.menu_active is False


# -- submit ---------------------------------------------------------------------


def test_prepare_submit_rejects_blank_and_guards_double_enter() -> None:
    """Blank lines never submit; the same line within 300 ms is dropped."""
    session = CommandLineSession()
    assert prepare_submit(session, "   ") is None
    first = prepare_submit(session, "bead list")
    assert first is not None and first.tokens == ["bead", "list"]
    assert prepare_submit(session, "bead list") is None
    session.last_submit_at -= 10.0
    assert prepare_submit(session, "bead list") is not None


def test_submit_failure_path_restores_state() -> None:
    """A failed submit turns the block red with the error."""
    session = CommandLineSession()
    block = session.add_block("bead list")
    apply_submit_failure(block, "boom")
    assert block.status == "submit_failed"
    assert block.error == "boom"


def test_submit_success_and_exit_settle() -> None:
    """Attaching a proc marks running; the exit completion settles it."""
    session = CommandLineSession()
    block = session.add_block("bead list")
    apply_submit_success(block, SimpleNamespace(proc_id="proc123"), placeholder_id="p1")
    assert block.status == "running"
    assert block.proc_id == "proc123"
    apply_exit_completion(block, exit_code=0, status="done")
    assert block.status == "success"
    assert block.exit_code == 0
    failed = session.add_block("bead close sase-zz")
    apply_exit_completion(failed, exit_code=2, status="done")
    assert failed.status == "error"


def test_exit_elapsed_uses_one_clock_for_live_blocks() -> None:
    """A live block's elapsed is seconds since submit, not an epoch timestamp.

    ``finished_at`` is wall-clock time (it renders the ``HH:MM`` stamp), so a
    fresh block must start on the same clock.
    """
    session = CommandLineSession()
    block = session.add_block("bead list")
    apply_submit_success(block, SimpleNamespace(proc_id="proc124"), placeholder_id="p2")
    apply_exit_completion(block, exit_code=0, status="done")
    assert block.elapsed is not None
    assert 0.0 <= block.elapsed < 60.0
    local = session.add_block("history")
    apply_local_block(local, status="builtin", text="", exit_code=0)
    assert local.elapsed is not None
    assert 0.0 <= local.elapsed < 60.0


# -- rendering -------------------------------------------------------------------


def test_sanitize_collapses_cr_and_drops_osc_keeps_sgr() -> None:
    """``\\r`` overwrites collapse, OSC sequences drop, SGR colors survive."""
    cleaned = sanitize_block_output("old\rnew\x1b]0;title\x07\x1b[31mred\x1b[0m")
    assert "old" not in cleaned
    assert "title" not in cleaned
    assert "\x1b[31m" in cleaned


def test_collapsed_body_shows_last_12_lines() -> None:
    """Collapsed blocks show the last 12 lines plus the hidden count."""
    text = "\n".join(f"line {index}" for index in range(20))
    lines, hidden = collapsed_body_lines(text)
    assert hidden == 8
    assert lines == [f"line {index}" for index in range(8, 20)]
    assert render_block_output("proc1", len(text), text) is not None


def test_gutter_and_header_metadata() -> None:
    """Gutter glyphs and right-aligned metadata follow the visual language."""
    assert gutter_glyph("running") == "⠹"
    assert gutter_glyph("success") == "✓"
    assert gutter_glyph("error") == "✗"
    header = block_header_right(
        "success",
        exit_code=0,
        elapsed=0.9,
        finished_at=1700000000.0,
        proc_id="470vtqab",
    )
    assert "exit 0" in header
    assert "proc 470vtq" in header
    assert "running 0s" in block_header_right("running", elapsed=0.2)


def test_context_chip_marks_pins_and_truncates() -> None:
    """The chip shows project plus path, marks pins, and middle-truncates."""
    context = CommandLineContext(cwd="/home/u/projects/sase", project="sase")
    assert working_context_chip(context) == "⌂ +sase · /home/u/projects/sase"
    pinned = CommandLineContext(cwd="/tmp", project=None, pinned=True)
    assert working_context_chip(pinned).endswith("(pinned)")
    long_context = CommandLineContext(cwd="/" + "a" * 100, project="sase")
    assert len(working_context_chip(long_context, max_width=48)) <= 48


# -- pump-free tail regression ----------------------------------------------------


def test_tail_polling_never_touches_message_pump() -> None:
    """The tail loop is a plain coroutine driven by ``spawn_pump_free_task``."""
    import asyncio
    import inspect

    from sase.ace.tui.command_line.transcript import CommandLineTranscript

    assert inspect.iscoroutinefunction(CommandLineTranscript._tail_loop)
    source = inspect.getsource(CommandLineTranscript.start_tail_task)
    assert "spawn_pump_free_task" in source
    assert "call_after_refresh" not in source
    assert asyncio.iscoroutinefunction(CommandLineTranscript._tail_loop)


def test_screen_submit_uses_thread_worker_not_await() -> None:
    """Submission fans out to a worker; the keystroke path never awaits I/O."""
    import inspect

    from sase.ace.tui.command_line import screen as screen_module

    worker_source = inspect.getsource(screen_module.CommandLineScreen._submit_worker)
    assert "to_thread" in worker_source
    submit_source = inspect.getsource(
        screen_module.CommandLineScreen.submit_current_line
    )
    assert "await" not in submit_source


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

                await asyncio.wait_for(page.press("escape"), timeout=1.0)
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

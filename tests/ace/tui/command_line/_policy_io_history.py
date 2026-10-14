"""Command-line history persistence and session-memory tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.command_line.history import CommandLineHistory
from sase.ace.tui.command_line.session import command_line_session_for
from sase.history import command_line as history_store

from ._policy_io_helpers import open_panel


def test_remember_upserts_in_memory_without_disk(
    history_file: Any,
) -> None:
    """``remember`` dedups like the store but never touches the file."""
    history = CommandLineHistory()
    history.remember("bead list", cwd="/tmp")
    history.remember("bead show sase-1", cwd="/tmp")
    history.remember("bead list", cwd="/tmp", exit_code=0)
    assert [entry.line for entry in history.entries] == [
        "bead list",
        "bead show sase-1",
    ]
    assert history.entries[0].count == 2
    assert history.entries[0].last_exit == 0
    history.remember("   ")
    assert len(history.entries) == 2
    assert not history_file.exists()


async def test_reopen_reuses_session_history_without_disk_reads(
    monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> None:
    """History loads once off-thread; reopen does no history/marker read."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line import palette_moved_tip as tip_module
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.screen import CommandLineScreen

    with history_store.locked_command_line_history():
        history_store.record_command_line("bead list", cwd="/tmp", exit_code=0)
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            monkeypatch.setattr(
                screen_module, "read_command_line_store_rows", lambda: []
            )
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            screen.transcript.stop_tail_task()
            session = command_line_session_for(page.app)
            await page.wait_for(
                lambda _state: (
                    session.history_loaded and session.palette_tip_show is not None
                )
            )
            assert session.command_history is screen._history
            assert [e.line for e in session.command_history.entries] == ["bead list"]

            reads: list[str] = []
            real_load = history_store.load_command_line_history

            def _counting_load() -> Any:
                reads.append("history")
                return real_load()

            real_tip = tip_module.has_shown_palette_moved_tip

            def _counting_tip() -> bool:
                reads.append("tip")
                return real_tip()

            monkeypatch.setattr(
                history_store, "load_command_line_history", _counting_load
            )
            monkeypatch.setattr(
                tip_module, "has_shown_palette_moved_tip", _counting_tip
            )
            page.app.pop_screen()
            await page.pause()
            assert not isinstance(page.app.screen, CommandLineScreen)
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            reopened = page.app.screen
            assert isinstance(reopened, CommandLineScreen)
            reopened.transcript.stop_tail_task()
            await page.pause()
            await page.pause()
            assert reads == []
            assert session.history_loaded is True
            assert [e.line for e in session.command_history.entries] == ["bead list"]
            widget = reopened.query_one(CommandLineInput)
            widget.set_line("bead")
            await page.pause()
            assert widget.suggestion == " list"


async def test_submit_and_exit_update_memory_without_reopen(
    monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> None:
    """A submitted and finished command shows in ghost/RECENT at once."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.exits import deliver_command_line_exit
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.session import command_line_session_for

    monkeypatch.setattr(
        screen_module,
        "resolve_command_line",
        lambda app, line, cursor: {
            "run_policy": {"policy": "proc", "note": None},
            "confirms": False,
            "confirm_flag_present": False,
        },
    )
    monkeypatch.setattr(
        screen_module,
        "submit_in_worker",
        lambda **kwargs: SimpleNamespace(proc_id="proc-mem-1"),
    )
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_panel(page, monkeypatch, history_file)
            assert screen._submit_line("bead list --status open") is True
            session = command_line_session_for(page.app)
            assert session.command_history.entries[0].line == (
                "bead list --status open"
            )
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead list")
            await page.pause()
            assert widget.suggestion == " --status open"

            await page.pause_until_cpu_idle()
            block = session.block_for_proc("proc-mem-1")
            assert block is not None
            completion = SimpleNamespace(
                proc_id="proc-mem-1", exit_code=0, status="done"
            )
            assert deliver_command_line_exit(page.app, completion) is True
            # The store write runs off-thread: wait for its observable end state.
            await page.wait_for(lambda _state: history_file.exists())
            assert session.command_history.entries[0].line == (
                "bead list --status open"
            )
            assert session.command_history.entries[0].last_exit == 0
            assert session.command_history.recent()[0].line == (
                "bead list --status open"
            )


def test_note_exit_refreshes_without_bumping_count(history_file: Any) -> None:
    """``note_exit`` refreshes ``last_exit``/``last_used``; one run counts once."""
    history = CommandLineHistory()
    history.remember("bead list", cwd="/tmp")
    history.note_exit("bead list", cwd="/tmp", exit_code=0)
    assert [entry.line for entry in history.entries] == ["bead list"]
    assert history.entries[0].count == 1
    assert history.entries[0].last_exit == 0
    # A line with no remembered submission still records at count 1.
    history.note_exit("bead show sase-1", cwd="/tmp", exit_code=1)
    assert history.entries[0].line == "bead show sase-1"
    assert history.entries[0].count == 1
    assert history.entries[0].last_exit == 1
    history.note_exit("   ")
    assert len(history.entries) == 2
    assert not history_file.exists()


async def test_submit_then_exit_counts_one_run_once(
    monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> None:
    """A proc run bumps the in-memory count at submit only, not again at exit."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.exits import deliver_command_line_exit

    monkeypatch.setattr(
        screen_module,
        "resolve_command_line",
        lambda app, line, cursor: {
            "run_policy": {"policy": "proc", "note": None},
            "confirms": False,
            "confirm_flag_present": False,
        },
    )
    monkeypatch.setattr(
        screen_module,
        "submit_in_worker",
        lambda **kwargs: SimpleNamespace(proc_id="proc-once-1"),
    )
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_panel(page, monkeypatch, history_file)
            assert screen._submit_line("bead list --status open") is True
            session = command_line_session_for(page.app)
            assert session.command_history.entries[0].count == 1
            await page.pause_until_cpu_idle()
            assert session.block_for_proc("proc-once-1") is not None
            completion = SimpleNamespace(
                proc_id="proc-once-1", exit_code=0, status="done"
            )
            assert deliver_command_line_exit(page.app, completion) is True
            await page.wait_for(lambda _state: history_file.exists())
            await page.wait_for(
                lambda _state: session.command_history.entries[0].last_exit == 0
            )
            assert len(session.command_history.entries) == 1
            assert session.command_history.entries[0].count == 1
            stored = history_store.load_command_line_history()
            assert len(stored) == 1
            assert stored[0].count == 1
            assert stored[0].last_exit == 0

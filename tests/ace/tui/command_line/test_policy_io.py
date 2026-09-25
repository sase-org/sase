"""Policy-I/O tests for the ``:`` Command Line (phase sase-17x.13.7).

Covers the foreground interpreter argv, session-held history that loads once
off-thread and updates in memory at submit and exit, the cached palette-moved
tip marker, the worker-thread ``K`` kill and Procs-jump store reads, and
tail polling limited to visible running blocks with off-loop log reads.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.command_line.history import CommandLineHistory
from sase.ace.tui.command_line.session import command_line_session_for
from sase.history import command_line as history_store


@pytest.fixture
def history_file(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolate the history store to a temp file."""
    path = tmp_path / "command_line_history.json"
    monkeypatch.setattr(history_store, "_history_file_override", path)
    return path


async def _open_panel(
    page: Any, monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> Any:
    """Open the panel with restore stubbed and history isolated to tmp."""
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.screen import CommandLineScreen

    monkeypatch.setattr(screen_module, "read_command_line_store_rows", lambda: [])
    monkeypatch.setattr(history_store, "_history_file_override", history_file)
    page.app.action_open_command_line()
    await page.expect_modal("CommandLineScreen")
    screen = page.app.screen
    assert isinstance(screen, CommandLineScreen)
    screen.transcript.stop_tail_task()
    await page.pause()
    return screen


async def _wait_for(page: Any, predicate: Any, *, attempts: int = 200) -> None:
    """Pause until *predicate* holds (async workers have landed)."""
    for _ in range(attempts):
        if predicate():
            return
        await page.pause()
    assert predicate(), "timed out waiting for background worker"


# -- remember() ------------------------------------------------------------------


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


# -- session-held history ----------------------------------------------------------


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
            await _wait_for(
                page,
                lambda: session.history_loaded and session.palette_tip_show is not None,
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


# -- submit/exit memory ------------------------------------------------------------


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
            screen = await _open_panel(page, monkeypatch, history_file)
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
            await page.pause_until_cpu_idle()
            assert history_file.exists()
            assert session.command_history.entries[0].line == (
                "bead list --status open"
            )
            assert session.command_history.entries[0].last_exit == 0
            assert session.command_history.recent()[0].line == (
                "bead list --status open"
            )


# -- Procs jump worker -------------------------------------------------------------


async def test_procs_jump_reads_store_off_thread(
    monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> None:
    """The Procs ``⏎`` jump ensures its block in a worker, then opens."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.restore import ensure_block_for_proc
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.ace.tui.modals.procs_pane_agent_jump import (
        _open_command_line_on_block,
    )

    main_ident = threading.get_ident()
    idents: list[int] = []

    def _fake_ensure(session: Any, proc_id: str) -> Any:
        idents.append(threading.get_ident())
        block = session.add_block("bead show p1")
        block.proc_id = proc_id
        block.status = "success"
        block.tail_loaded = True
        return block

    monkeypatch.setattr(
        "sase.ace.tui.command_line.restore.ensure_block_for_proc", _fake_ensure
    )
    assert ensure_block_for_proc is not None
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            monkeypatch.setattr(
                screen_module, "read_command_line_store_rows", lambda: []
            )
            monkeypatch.setattr(history_store, "_history_file_override", history_file)
            assert _open_command_line_on_block(page.app, "proc-jump-9") is False
            await page.expect_modal("CommandLineScreen")
            await page.pause_until_cpu_idle()
            session = command_line_session_for(page.app)
            assert idents and all(ident != main_ident for ident in idents)
            assert session.focus_block_proc_id is None
            selected = session.selected_block()
            assert selected is not None and selected.proc_id == "proc-jump-9"
            page.app.screen.transcript.stop_tail_task()


# -- tail visibility -----------------------------------------------------------------


async def test_hidden_running_blocks_are_not_tailed(
    monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> None:
    """Tail polling skips hidden blocks and reads logs off the loop."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import transcript as transcript_module
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.procs.logs import ProcLogCursor, ProcLogRead

    main_ident = threading.get_ident()
    reads: list[tuple[str, int]] = []

    def _spy_read(self: ProcLogCursor) -> ProcLogRead:
        reads.append((self.proc_id, threading.get_ident()))
        return ProcLogRead(text=f"<{self.proc_id}>\n")

    monkeypatch.setattr(ProcLogCursor, "read_new", _spy_read)
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_panel(page, monkeypatch, history_file)
            session = command_line_session_for(page.app)
            first = session.add_block("bead list")
            first.proc_id = "proc-tail-1"
            first.status = "running"
            second = session.add_block("bead show sase-1")
            second.proc_id = "proc-tail-2"
            second.status = "running"
            screen.refresh_transcript()
            await page.pause()
            widgets = list(
                screen.transcript.query(transcript_module._CommandLineBlockWidget)
            )
            assert len(widgets) == 2
            assert screen.transcript._tail_target_visible(widgets[0]) is True
            widgets[1].display = False
            await page.pause()
            await screen.transcript._poll_once()
            assert "<proc-tail-1>" in first.tail_text
            assert second.tail_text == ""
            assert [proc_id for proc_id, _ in reads] == ["proc-tail-1"]
            assert all(ident != main_ident for _, ident in reads)

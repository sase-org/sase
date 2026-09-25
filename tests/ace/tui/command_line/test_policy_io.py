"""Policy-I/O tests for the ``:`` Command Line (phases sase-17x.13.7, sase-17x.13.10.5).

Covers the foreground interpreter argv, session-held history that loads once
off-thread and updates in memory at submit and exit, the cached palette-moved
tip marker, the worker-thread ``K`` kill and Procs-jump store reads, and
tail polling limited to visible running blocks with off-loop log reads.

Phase sase-17x.13.10.5 adds: the palette-tip marker *write* off the loop,
the Procs-jump block build/append on the UI thread only, one in-memory count
per run, the ``writes``-chip pilot coverage, and the scrolled-out tail test.
"""

from __future__ import annotations

import json
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import Static

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
            # The store write runs off-thread: wait for its observable end state.
            await page.wait_for(lambda _state: history_file.exists())
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
    """The Procs ``⏎`` jump reads the store in a worker, then opens."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.restore import read_proc_for_block
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.ace.tui.modals.procs_pane_agent_jump import (
        _open_command_line_on_block,
    )

    main_ident = threading.get_ident()
    idents: list[int] = []

    def _fake_read(proc_id: str) -> Any:
        idents.append(threading.get_ident())
        assert proc_id == "proc-jump-9"
        return SimpleNamespace(
            proc_id="proc-jump-9",
            command=["sase", "bead", "show", "p1"],
            label=": bead show p1",
            origin="ace",
            tags=["command-line"],
            status="success",
            exit_code=0,
            created_at="2026-09-25T10:00:00Z",
            started_at="2026-09-25T10:00:00Z",
            finished_at="2026-09-25T10:00:01Z",
            log_path="",
        )

    monkeypatch.setattr(
        "sase.ace.tui.command_line.restore.read_proc_for_block", _fake_read
    )
    assert read_proc_for_block is not None
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


# -- phase sase-17x.13.10.5: ui-thread-state -----------------------------------


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


async def test_palette_tip_marker_write_runs_off_loop(
    monkeypatch: pytest.MonkeyPatch, history_file: Any, tmp_path: Any
) -> None:
    """The one-time tip write never runs on the loop; the session caches first."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import palette_moved_tip as tip_module

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_panel(page, monkeypatch, history_file)
            session = command_line_session_for(page.app)
            await page.wait_for(lambda _state: session.palette_tip_show is not None)
            marker = tmp_path / "command_line_palette_moved_tip_shown"
            if marker.exists():
                marker.unlink()
            main_ident = threading.get_ident()
            idents: list[int] = []
            real_mark = tip_module.mark_palette_moved_tip_shown

            def _spy_mark() -> None:
                idents.append(threading.get_ident())
                real_mark()

            monkeypatch.setattr(tip_module, "mark_palette_moved_tip_shown", _spy_mark)
            session.palette_tip_show = True
            screen._maybe_show_palette_moved_tip()
            # Cache-first: a reopen before the write lands does no disk I/O.
            assert session.palette_tip_show is False
            # The spy records its thread before the real write runs, so wait
            # for the marker itself rather than racing the write.
            await page.wait_for(lambda _state: idents != [] and marker.exists())
            assert all(ident != main_ident for ident in idents)


async def test_procs_jump_reads_off_thread_and_appends_on_ui_thread(
    monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> None:
    """The Procs jump reads the store off-thread, then appends on the loop."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import restore as restore_module
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.modals.procs_pane_agent_jump import (
        _open_command_line_on_block,
    )

    main_ident = threading.get_ident()
    read_idents: list[int] = []
    append_idents: list[int] = []
    real_read = restore_module.read_proc_for_block
    real_append = restore_module.append_proc_block
    fake_proc = SimpleNamespace(
        proc_id="proc-split-1",
        command=["sase", "bead", "show", "sase-1"],
        label=": bead show sase-1",
        origin="ace",
        tags=["command-line"],
        status="success",
        exit_code=0,
        created_at="2026-09-25T10:00:00Z",
        started_at="2026-09-25T10:00:00Z",
        finished_at="2026-09-25T10:00:05Z",
        log_path="",
    )

    def _spy_read(proc_id: str) -> Any:
        read_idents.append(threading.get_ident())
        assert proc_id == "proc-split-1"
        return real_read(proc_id) if proc_id != "proc-split-1" else fake_proc

    def _spy_append(session: Any, proc: Any) -> Any:
        append_idents.append(threading.get_ident())
        return real_append(session, proc)

    monkeypatch.setattr(restore_module, "read_proc_for_block", _spy_read)
    monkeypatch.setattr(restore_module, "append_proc_block", _spy_append)
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            monkeypatch.setattr(
                screen_module, "read_command_line_store_rows", lambda: []
            )
            monkeypatch.setattr(history_store, "_history_file_override", history_file)
            assert _open_command_line_on_block(page.app, "proc-split-1") is False
            await page.expect_modal("CommandLineScreen")
            session = command_line_session_for(page.app)
            await page.wait_for(
                lambda _state: session.block_for_proc("proc-split-1") is not None
            )
            block = session.block_for_proc("proc-split-1")
            assert block is not None and block.line == "bead show sase-1"
            assert read_idents and all(ident != main_ident for ident in read_idents)
            assert append_idents and all(ident == main_ident for ident in append_idents)
            page.app.screen.transcript.stop_tail_task()


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
            screen = await _open_panel(page, monkeypatch, history_file)
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


@pytest.fixture(scope="module")
def grammar_handle() -> Any:
    """Return an in-process ``CommandLineGrammar`` (no spec subprocess)."""
    try:
        from sase.completion.build import build_spec
        from sase.completion.command_line_grammar import CommandLineGrammar

        return CommandLineGrammar.from_spec_json(json.dumps(build_spec().to_json()))
    except AttributeError:
        pytest.skip("installed sase_core_rs wheel predates CommandLineGrammar")


@asynccontextmanager
async def _grammar_panel(
    grammar: Any, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[Any, Any]]:
    """Open the panel with the real in-process grammar behind the resolver."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.screen import CommandLineScreen

    monkeypatch.setattr(screen_module, "read_command_line_store_rows", lambda: [])
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app._command_line_grammar = grammar
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            await page.pause()
            await page.pause()
            yield page, screen


async def test_mounted_panel_shows_writes_chip(
    grammar_handle: Any,
    history_file: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mounted panel shows the ``writes`` chip for writers (not just the spec)."""
    from sase.ace.tui.command_line.input import CommandLineInput

    async with _grammar_panel(grammar_handle, monkeypatch) as (page, screen):
        for line in ("tool stop", "plan approve"):
            widget = screen.query_one(CommandLineInput)
            widget.set_line(line)
            await page.pause()
            hint = str(screen.query_one("#command-line-hint-row", Static).render())
            assert "⚠ writes" in hint, line
        screen.transcript.stop_tail_task()


async def test_scrolled_out_running_block_is_not_tailed(
    monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> None:
    """Tail polling skips running blocks scrolled out of view, not just hidden ones."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line import transcript as transcript_module
    from sase.procs.logs import ProcLogCursor, ProcLogRead

    reads: list[str] = []

    def _spy_read(self: ProcLogCursor) -> ProcLogRead:
        reads.append(self.proc_id)
        return ProcLogRead(text=f"<{self.proc_id}>\n")

    monkeypatch.setattr(ProcLogCursor, "read_new", _spy_read)
    monkeypatch.setattr(screen_module, "read_command_line_store_rows", lambda: [])
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            monkeypatch.setattr(history_store, "_history_file_override", history_file)
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            screen.transcript.stop_tail_task()
            await page.pause()
            session = command_line_session_for(page.app)
            for index in range(6):
                block = session.add_block(f"bead show sase-{index}")
                block.proc_id = f"proc-scroll-{index}"
                block.status = "running"
                block.tail_text = "".join(f"line-{index}-{row}\n" for row in range(12))
            screen.refresh_transcript()
            await page.pause()
            screen.transcript.scroll_end(animate=False)
            await page.pause()
            widgets = list(
                screen.transcript.query(transcript_module._CommandLineBlockWidget)
            )
            assert len(widgets) == 6
            assert screen.transcript._tail_target_visible(widgets[0]) is False
            assert screen.transcript._tail_target_visible(widgets[-1]) is True
            await screen.transcript._poll_once()
            assert "proc-scroll-0" not in reads
            assert "proc-scroll-5" in reads

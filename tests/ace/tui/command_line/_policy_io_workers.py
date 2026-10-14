"""Worker-thread and UI-thread policy-I/O tests."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.command_line.session import command_line_session_for
from sase.history import command_line as history_store

from ._policy_io_helpers import open_panel


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
            screen = await open_panel(page, monkeypatch, history_file)
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

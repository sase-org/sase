"""Tail polling visibility and elapsed-time tests."""

from __future__ import annotations

import re
import threading
import time
from typing import Any

import pytest

from sase.ace.tui.command_line.session import command_line_session_for
from sase.history import command_line as history_store

from ._policy_io_helpers import open_panel


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
            screen = await open_panel(page, monkeypatch, history_file)
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


async def test_poll_once_ticks_running_elapsed(
    monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> None:
    """A visible running block counts elapsed on the existing tail tick."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.ace.tui.command_line.transcript import _CommandLineBlockWidget
    from sase.procs.logs import ProcLogCursor, ProcLogRead

    def _spy_read(self: ProcLogCursor) -> ProcLogRead:
        return ProcLogRead(text="")

    monkeypatch.setattr(ProcLogCursor, "read_new", _spy_read)
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_panel(page, monkeypatch, history_file)
            screen.transcript.stop_tail_task()
            session = command_line_session_for(page.app)
            block = session.add_block("agent archive rebuild-index")
            block.proc_id = "proc-tick-1"
            block.status = "running"
            block.started_at = time.time() - 5.0
            screen.refresh_transcript()
            await page.pause()
            assert block.elapsed is None
            assert "running 0s" in str(_CommandLineBlockWidget.render_block(block))
            await screen.transcript._poll_once()
            assert block.elapsed is not None
            assert 5.0 <= block.elapsed < 30.0
            rendered = str(_CommandLineBlockWidget.render_block(block))
            match = re.search(r"running (\d+)s", rendered)
            assert match is not None
            assert int(match.group(1)) >= 5


async def test_poll_once_ticks_submitting_without_log_read(
    monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> None:
    """A submitting block ticks elapsed and spinner without reading a log."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import transcript as transcript_module
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.procs.logs import ProcLogCursor, ProcLogRead

    reads: list[str] = []

    def _spy_read(self: ProcLogCursor) -> ProcLogRead:
        reads.append(self.proc_id)
        return ProcLogRead(text="")

    monkeypatch.setattr(ProcLogCursor, "read_new", _spy_read)
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_panel(page, monkeypatch, history_file)
            screen.transcript.stop_tail_task()
            session = command_line_session_for(page.app)
            block = session.add_block("bead list")
            block.proc_id = None
            block.status = "submitting"
            block.started_at = time.time() - 3.0
            screen.refresh_transcript()
            await page.pause()
            widgets = list(
                screen.transcript.query(transcript_module._CommandLineBlockWidget)
            )
            assert len(widgets) == 1
            assert widgets[0]._spinner_index == 0
            await screen.transcript._poll_once()
            assert block.elapsed is not None
            assert block.elapsed >= 3.0
            assert widgets[0]._spinner_index == 1
            assert reads == []


async def test_poll_once_keeps_settled_elapsed_after_await(
    monkeypatch: pytest.MonkeyPatch, history_file: Any
) -> None:
    """An exit that lands during the log read keeps the settled elapsed."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import (
        CommandLineBlock,
        command_line_session_for,
    )
    from sase.procs.logs import ProcLogCursor, ProcLogRead

    target: list[CommandLineBlock] = []

    def _spy_read(self: ProcLogCursor) -> ProcLogRead:
        if self.proc_id == "proc-settle-1" and target:
            settled = target[0]
            settled.status = "success"
            settled.finished_at = time.time()
            settled.elapsed = 1.25
        return ProcLogRead(text="")

    monkeypatch.setattr(ProcLogCursor, "read_new", _spy_read)
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await open_panel(page, monkeypatch, history_file)
            screen.transcript.stop_tail_task()
            session = command_line_session_for(page.app)
            block = session.add_block("bead list")
            block.proc_id = "proc-settle-1"
            block.status = "running"
            block.started_at = time.time() - 8.0
            target.append(block)
            screen.refresh_transcript()
            await page.pause()
            await screen.transcript._poll_once()
            assert block.elapsed == 1.25
            assert block.status == "success"


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

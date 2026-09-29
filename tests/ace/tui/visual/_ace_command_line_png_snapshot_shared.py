"""Shared Command Line PNG snapshot panel helpers.

Public helpers for the ``test_ace_png_snapshots_command_line*`` split. This
module is private (``_``-prefixed); the helpers are public so each split test
module can import them without importing a ``_``-prefixed name across modules.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.command_line.context import CommandLineContext
from sase.ace.tui.command_line.screen import CommandLineScreen
from sase.ace.tui.command_line.session import command_line_session_for
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    wait_for_startup,
    wait_for_visual_idle,
)

_FROZEN_CONTEXT = CommandLineContext(cwd="/home/test/projects/sase", project="sase")


async def open_command_line_panel(
    page: AcePage,
    monkeypatch: pytest.MonkeyPatch,
    *,
    history_file: object = None,
) -> CommandLineScreen:
    """Open the panel with frozen context/history and a stopped tail task."""
    monkeypatch.setattr(
        "sase.ace.tui.command_line.screen.resolve_working_context",
        lambda app, session: _FROZEN_CONTEXT,
    )
    # These snapshots either supply a frozen resolver response or explicitly
    # model the pre-grammar indexing state. Starting the real grammar builder
    # here would leave its host-dependent ``_load`` worker in flight and make
    # render convergence depend on a subprocess that the snapshot cannot show.
    monkeypatch.setattr(
        "sase.ace.tui.command_line.screen.ensure_command_line_grammar_loaded",
        lambda app, *, on_ready=None: False,
    )
    if history_file is not None:
        from sase.history import command_line as history_store

        monkeypatch.setattr(history_store, "_history_file_override", history_file)
    # Treat the one-time palette tip as already shown. The real marker read
    # lands from an off-thread worker, so whether the tip or a later hint
    # owns the hint row at capture time would otherwise depend on host load.
    command_line_session_for(page.app).palette_tip_show = False
    page.app.action_open_command_line()
    await wait_for_visual_idle(page)
    screen = page.app.screen
    assert isinstance(screen, CommandLineScreen)
    screen.transcript.stop_tail_task()
    await wait_for_visual_idle(page)
    return screen


def seed_command_line_block(
    screen: CommandLineScreen,
    line: str,
    *,
    status: str,  # type: ignore[valid-type]
    tail_text: str = "",
    exit_code: int | None = None,
    elapsed: float | None = None,
    proc_id: str | None = None,
    error: str | None = None,
    expanded: bool = False,
    restored: bool = False,
    unseen: bool = False,
    selected: bool = False,
    declined: bool = False,
) -> None:
    session = command_line_session_for(screen.app)
    block = session.add_block(line)
    block.status = status  # type: ignore[assignment]
    block.tail_text = tail_text
    block.exit_code = exit_code
    block.elapsed = elapsed
    block.proc_id = proc_id
    block.error = error
    block.expanded = expanded
    block.restored = restored
    block.unseen = unseen
    block.declined = declined
    if selected:
        session.select_block(block.block_id)
    screen.refresh_transcript()


async def seeded_command_line_panel(
    page: AcePage, monkeypatch: pytest.MonkeyPatch
) -> CommandLineScreen:
    await wait_for_startup(page)
    return await open_command_line_panel(page, monkeypatch)

"""Shared helpers for transcript-block tests.

Public helpers used by more than one ``test_transcript_blocks_*`` module
live here under public names so no new module imports a ``_``-prefixed
name from another new module.
"""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.command_line.session import CommandLineBlock

__all__ = [
    "open_seeded_panel",
    "to_normal",
]


async def open_seeded_panel(
    page: Any,
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> Any:
    """Open the panel with restore stubbed and *lines* seeded as blocks."""
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.screen import CommandLineScreen
    from sase.ace.tui.command_line.session import command_line_session_for

    monkeypatch.setattr(screen_module, "read_command_line_store_rows", lambda: [])

    def _mark_loaded(block: CommandLineBlock) -> bool:
        block.tail_loaded = True
        return True

    monkeypatch.setattr(screen_module, "load_block_tail_text", _mark_loaded)
    page.app.action_open_command_line()
    await page.expect_modal("CommandLineScreen")
    screen = page.app.screen
    assert isinstance(screen, CommandLineScreen)
    session = command_line_session_for(page.app)
    for line in lines:
        session.add_block(line)
    screen.refresh_transcript()
    await page.pause()
    return screen


def to_normal(screen: Any) -> Any:
    from sase.ace.tui.command_line.input import CommandLineInput

    widget = screen.query_one(CommandLineInput)
    widget._enter_normal_mode()
    return widget

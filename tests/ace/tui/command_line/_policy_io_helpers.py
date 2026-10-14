"""Shared fixtures and setup for policy-I/O tests."""

from __future__ import annotations

from typing import Any

import pytest

from sase.history import command_line as history_store


@pytest.fixture
def history_file(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolate the history store to a temp file."""
    path = tmp_path / "command_line_history.json"
    monkeypatch.setattr(history_store, "_history_file_override", path)
    return path


async def open_panel(
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

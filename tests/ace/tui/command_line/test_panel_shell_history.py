"""History-store tests for the ``:`` Command Line.

History locking and LRU, prefix walking, ghost text, and the mounted
input's history key handling.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from sase.ace.tui.command_line.history import CommandLineHistory
from sase.history import command_line as history_store

__all__ = [
    "history_file",
    "test_ghost_prefers_same_cwd",
    "test_history_enforces_lru_cap",
    "test_history_lock_serializes_concurrent_records",
    "test_prefix_walk_prefers_same_cwd",
    "test_real_input_ctrl_f_accepts_only_an_active_menu",
    "test_real_input_walks_history_and_never_pastes_mid_line_ghost",
    "test_record_dedups_repeats_with_count",
]


@pytest.fixture
def history_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the history store to a temp file."""
    path = tmp_path / "command_line_history.json"
    monkeypatch.setattr(history_store, "_history_file_override", path)
    return path


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

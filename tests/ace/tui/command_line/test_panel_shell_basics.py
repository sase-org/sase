"""Basic panel-shell tests for the ``:`` Command Line.

Tokenize/strip parsing, the landed panel-shell phase contract, and the
session lifecycle.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.command_line.session import (
    COMMAND_LINE_MAX_BLOCKS,
    CommandLineSession,
    command_line_session_for,
    strip_implicit_prefix,
    tokenize_command_line,
)
from sase.ace.tui.commands.availability import is_command_available
from sase.ace.tui.commands.types import CommandContext, CommandExecutor, CommandSpec

__all__ = [
    "test_action_pushes_command_line_screen_unconditionally",
    "test_clear_transcript_keeps_running_blocks",
    "test_palette_moved_tip_marker_round_trip",
    "test_palette_row_always_visible_after_land",
    "test_session_caps_blocks_at_200",
    "test_session_defaults_for_reopen",
    "test_session_for_app_is_stable",
    "test_strip_implicit_prefix_keeps_other_text_verbatim",
    "test_tokenize_strips_implicit_sase_prefix",
]


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

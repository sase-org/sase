"""Tests for the BgCmdList widget."""

from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.widgets import BgCmdList


def test_bgcmd_list_selection_changed_slot() -> None:
    """Test SelectionChanged message with index."""
    msg = BgCmdList.SelectionChanged(3)
    assert msg.index == 3


def test_bgcmd_list_format_lumberjack_option_stopped() -> None:
    """Test formatting a top-level lumberjack option without a status."""
    widget = BgCmdList()
    option = widget._format_lumberjack_option(
        name="hooks", status=None, is_selected=False
    )
    assert option.id == "lumberjack-hooks"


def test_bgcmd_list_format_lumberjack_option_selected() -> None:
    """Test formatting a top-level lumberjack option when selected."""
    widget = BgCmdList()
    option = widget._format_lumberjack_option(
        name="hooks", status=None, is_selected=True
    )
    assert option.id == "lumberjack-hooks"


def test_bgcmd_list_format_bgcmd_option_long_command() -> None:
    """Long bgcmd labels are no longer hard-truncated by the formatter; the
    widget posts a wider :class:`BgCmdList.WidthChanged` instead and Rich's
    no-wrap text plus the panel's clamped width handle overflow."""
    widget = BgCmdList()
    long_command = "make test-all-with-coverage-and-reports"
    info = BackgroundCommandInfo(
        command=long_command,
        project="myproject",
        workspace_num=1,
        workspace_dir="/path",
        started_at="2025-01-01T12:00:00",
    )
    option = widget._format_bgcmd_option(
        slot=1, info=info, is_selected=False, is_running=True
    )
    assert option.id == "1"
    text_str = str(option.prompt)
    assert long_command in text_str
    assert "..." not in text_str


def test_bgcmd_list_format_bgcmd_option_done() -> None:
    """Test formatting background command option when done (not running)."""
    widget = BgCmdList()
    info = BackgroundCommandInfo(
        command="make test",
        project="myproject",
        workspace_num=1,
        workspace_dir="/path",
        started_at="2025-01-01T12:00:00",
    )
    option = widget._format_bgcmd_option(
        slot=2, info=info, is_selected=False, is_running=False
    )
    assert option.id == "2"
    text_str = str(option.prompt)
    # Done commands should show a checkmark
    assert "\u2713" in text_str

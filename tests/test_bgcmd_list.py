"""Tests for the BgCmdList widget."""

from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.widgets import BgCmdList


def test_bgcmd_list_selection_changed_slot() -> None:
    """Test SelectionChanged message with index."""
    msg = BgCmdList.SelectionChanged(3)
    assert msg.index == 3


def test_bgcmd_list_format_axe_parent_option_stopped() -> None:
    """Test formatting axe parent option when stopped."""
    widget = BgCmdList()
    option = widget._format_axe_parent_option(
        is_running=False, is_selected=False, child_count=0, is_expanded=False
    )
    assert option.id == "axe"


def test_bgcmd_list_format_axe_parent_option_selected() -> None:
    """Test formatting axe parent option when selected."""
    widget = BgCmdList()
    option = widget._format_axe_parent_option(
        is_running=True, is_selected=True, child_count=0, is_expanded=False
    )
    assert option.id == "axe"


def test_bgcmd_list_format_bgcmd_option_long_command() -> None:
    """Test formatting background command option with long command."""
    widget = BgCmdList()
    info = BackgroundCommandInfo(
        command="make test-all-with-coverage-and-reports",
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
    # Command should be truncated
    assert "..." in text_str


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

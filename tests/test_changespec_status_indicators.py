"""Tests for ChangeSpec status indicators in TUI widgets."""

from sase.ace.changespec import ChangeSpec, CommitEntry, HookEntry, HookStatusLine
from sase.ace.tui.widgets.ancestors_children_panel import _get_simple_status_indicator
from sase.ace.tui.widgets.changespec_list import _get_status_indicator


def _make_changespec(
    name: str = "test_feature",
    status: str = "Draft",
    commits: list[CommitEntry] | None = None,
    hooks: list[HookEntry] | None = None,
) -> ChangeSpec:
    """Create a mock ChangeSpec for testing."""
    return ChangeSpec(
        name=name,
        description="Test description",
        parent=None,
        cl=None,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
        commits=commits,
        hooks=hooks,
        comments=None,
    )


def _make_running_agent_hook() -> list[HookEntry]:
    """Create a hook list with a running agent."""
    return [
        HookEntry(
            command="test_hook",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="250118_120000",
                    status="RUNNING",
                    suffix_type="running_agent",
                )
            ],
        )
    ]


def _make_running_process_hook() -> list[HookEntry]:
    """Create a hook list with a running process."""
    return [
        HookEntry(
            command="test_hook",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="250118_120000",
                    status="RUNNING",
                    suffix_type="running_process",
                )
            ],
        )
    ]


def _make_error_hook() -> list[HookEntry]:
    """Create a hook list with an error."""
    return [
        HookEntry(
            command="test_hook",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="250118_120000",
                    status="FAILED",
                    suffix_type="error",
                )
            ],
        )
    ]


# --- Draft Status Indicator Tests ---


def test_get_simple_status_indicator_draft_returns_d() -> None:
    """Test that Draft status returns 'D' in simple indicator."""
    indicator, _ = _get_simple_status_indicator("Draft")
    assert indicator == "D"


def test_get_simple_status_indicator_unknown_returns_w() -> None:
    """Test that unknown status returns 'W' indicator (treated as WIP)."""
    indicator, _ = _get_simple_status_indicator("Unknown Status")
    assert indicator == "W"


# --- Draft with Running Agent/Process Prefix Tests ---


def test_get_status_indicator_draft_with_running_agent() -> None:
    """Test Draft with running agent shows @D."""
    changespec = _make_changespec(status="Draft", hooks=_make_running_agent_hook())
    indicator, letter_color = _get_status_indicator(changespec)
    assert indicator == "@D"
    assert letter_color == "#FFD700"  # Gold for Draft


def test_get_status_indicator_draft_with_running_process() -> None:
    """Test Draft with running process shows $D."""
    changespec = _make_changespec(status="Draft", hooks=_make_running_process_hook())
    indicator, letter_color = _get_status_indicator(changespec)
    assert indicator == "$D"
    assert letter_color == "#FFD700"  # Gold for Draft


# --- Other Status Indicators (non-Draft) ---


def test_get_status_indicator_mailed() -> None:
    """Test Mailed status returns 'M' with cyan-green color."""
    changespec = _make_changespec(status="Mailed")
    indicator, letter_color = _get_status_indicator(changespec)
    assert indicator == "M"
    assert letter_color == "#00D787"


def test_get_status_indicator_submitted() -> None:
    """Test Submitted status returns 'S' with dark green color."""
    changespec = _make_changespec(status="Submitted")
    indicator, letter_color = _get_status_indicator(changespec)
    assert indicator == "S"
    assert letter_color == "#00AF00"


def test_get_status_indicator_reverted() -> None:
    """Test Reverted status returns 'X' with gray color."""
    changespec = _make_changespec(status="Reverted")
    indicator, letter_color = _get_status_indicator(changespec)
    assert indicator == "X"
    assert letter_color == "#808080"


def test_get_simple_status_indicator_ready() -> None:
    """Test Ready status in simple indicator."""
    indicator, color = _get_simple_status_indicator("Ready")
    assert indicator == "R"
    assert color == "#87D700"


def test_get_simple_status_indicator_mailed() -> None:
    """Test Mailed status in simple indicator."""
    indicator, color = _get_simple_status_indicator("Mailed")
    assert indicator == "M"
    assert color == "#00D787"


def test_get_simple_status_indicator_submitted() -> None:
    """Test Submitted status in simple indicator."""
    indicator, color = _get_simple_status_indicator("Submitted")
    assert indicator == "S"
    assert color == "#00AF00"


def test_get_simple_status_indicator_reverted() -> None:
    """Test Reverted status in simple indicator."""
    indicator, color = _get_simple_status_indicator("Reverted")
    assert indicator == "X"
    assert color == "#808080"


# --- Prefix with Non-Draft Status Tests ---

"""Tests for status colors, available statuses, and display functions."""

from io import StringIO

from sase.ace.changespec import ChangeSpec
from sase.ace.display import display_changespec
from sase.ace.status import get_available_statuses
from rich.console import Console


def test_get_available_statuses_includes_others() -> None:
    """Test that get_available_statuses includes other valid statuses."""
    current_status = "Ready"
    available = get_available_statuses(current_status)
    # Should include some other statuses but not current
    assert len(available) > 0
    assert all(s != current_status for s in available)


def test_display_changespec_without_hints_returns_empty() -> None:
    """Test that display_changespec without hints returns empty dict."""
    # Create a minimal ChangeSpec
    changespec = ChangeSpec(
        name="test_spec",
        description="Test description",
        parent=None,
        cl=None,
        status="Ready",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
    )

    # Create a console that writes to a string buffer
    console = Console(file=StringIO(), force_terminal=True)

    # Call without hints (default)
    hint_mappings, hook_hint_to_idx = display_changespec(changespec, console)

    # Should be empty when hints not enabled
    assert hint_mappings == {}
    assert hook_hint_to_idx == {}

"""Tests for the axe dashboard widget utility functions."""

from sase.ace.tui.widgets.axe_dashboard import (
    _format_runtime,
    _format_uptime,
)


def test_format_uptime_hours_minutes_seconds() -> None:
    """Test formatting uptime with hours, minutes, and seconds."""
    assert _format_uptime(3723) == "1h 2m 3s"


def test_format_uptime_zero() -> None:
    """Test formatting uptime with zero seconds."""
    assert _format_uptime(0) == "0s"


def test_format_runtime_invalid() -> None:
    """Test formatting runtime with invalid timestamp."""
    assert _format_runtime("invalid") == "unknown"

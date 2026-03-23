"""Tests for HookEntry dataclass, HOOKS field parsing, and utility functions."""

from sase.ace.changespec import (
    HookEntry,
    HookStatusLine,
    parse_commit_entry_id,
)
from sase.ace.changespec.parser import _parse_changespec_from_lines
from sase.ace.hooks import (
    calculate_duration_from_timestamps,
    format_duration,
)


def _make_hook(
    command: str,
    commit_entry_num: str = "1",
    timestamp: str | None = None,
    status: str | None = None,
    duration: str | None = None,
) -> HookEntry:
    """Helper function to create a HookEntry with a status line."""
    if timestamp is None and status is None:
        return HookEntry(command=command)
    status_line = HookStatusLine(
        commit_entry_num=commit_entry_num,
        timestamp=timestamp or "",
        status=status or "",
        duration=duration,
    )
    return HookEntry(command=command, status_lines=[status_line])


# Tests for HookEntry dataclass
# Tests for HOOKS field parsing
def test_parse_changespec_hooks_with_dead_status() -> None:
    """Test parsing HOOKS with DEAD status."""
    lines = [
        "NAME: test_cl\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "STATUS: Ready\n",
        "HOOKS:\n",
        "  pytest src\n",
        "      | (1) [240601_123456] DEAD (24h0m)\n",
        "\n",
    ]
    changespec, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
    assert changespec is not None
    assert changespec.hooks is not None
    assert len(changespec.hooks) == 1
    assert changespec.hooks[0].command == "pytest src"
    sl = changespec.hooks[0].latest_status_line
    assert sl is not None
    assert sl.status == "DEAD"
    assert sl.duration == "24h0m"


def test_parse_changespec_hooks_suffix_with_closing_paren() -> None:
    """Test parsing HOOKS where suffix text contains ')' characters.

    AI-generated summaries can contain parentheses (e.g., "Exit 3)"),
    which previously broke the regex that used [^)]+ for the suffix group.
    """
    lines = [
        "NAME: test_cl\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "STATUS: Ready\n",
        "COMMITS:\n",
        "  (8) Some commit\n",
        "HOOKS:\n",
        "  pytest src\n",
        "      | (8) [260323_173040] FAILED (1m30s)"
        " - (%: deal_check_line_chart_test failed remotely (Exit 3)."
        " | deal_check_line_chart_test failed remotely (Exit 3).)\n",
        "\n",
    ]
    changespec, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
    assert changespec is not None
    assert changespec.hooks is not None
    assert len(changespec.hooks) == 1
    sl = changespec.hooks[0].latest_status_line
    assert sl is not None
    assert sl.status == "FAILED"
    assert sl.duration == "1m30s"
    assert sl.commit_entry_num == "8"
    # The suffix should be parsed despite containing ')' characters
    assert sl.suffix is not None
    assert "Exit 3" in sl.suffix


# Tests for hook utility functions
def test_format_duration_seconds_only() -> None:
    """Test formatting duration with only seconds."""
    assert format_duration(45) == "45s"
    assert format_duration(0) == "0s"
    assert format_duration(59) == "59s"


def test_format_duration_with_hours() -> None:
    """Test formatting duration with hours, minutes, and seconds."""
    assert format_duration(3600) == "1h0m0s"
    assert format_duration(3661) == "1h1m1s"
    assert format_duration(7323) == "2h2m3s"
    assert format_duration(86400) == "24h0m0s"  # 24 hours


# Tests for calculate_duration_from_timestamps
def test_calculate_duration_from_timestamps_invalid() -> None:
    """Test that invalid timestamps return None."""
    assert calculate_duration_from_timestamps("invalid", "240601_120000") is None
    assert calculate_duration_from_timestamps("240601_120000", "invalid") is None
    assert calculate_duration_from_timestamps("", "") is None
    # Legacy format (no underscore) no longer supported
    assert calculate_duration_from_timestamps("240601120000", "240601120100") is None


# Tests for parse_commit_entry_id
def test_parse_commit_entry_id_invalid() -> None:
    """Test parsing invalid commit entry IDs."""
    # Fallback returns (0, original_string)
    assert parse_commit_entry_id("abc") == (0, "abc")
    assert parse_commit_entry_id("") == (0, "")

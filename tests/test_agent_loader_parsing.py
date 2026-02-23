"""Tests for agent loader timestamp parsing functions."""

from sase.ace.tui.models._timestamps import (
    extract_timestamp_from_workflow,
    extract_timestamp_str_from_suffix,
    parse_timestamp_from_suffix,
)

# --- Timestamp Parsing Tests ---


def testparse_timestamp_from_suffix_none() -> None:
    """Test parsing None suffix."""
    result = parse_timestamp_from_suffix(None)
    assert result is None


def testparse_timestamp_from_suffix_invalid_timestamp() -> None:
    """Test parsing suffix with invalid timestamp format."""
    result = parse_timestamp_from_suffix("fix_hook-12345-invalid")
    assert result is None


# --- Timestamp Extraction Helper Tests ---


def testextract_timestamp_str_from_suffix_invalid_format() -> None:
    """Test extracting timestamp from suffix with invalid format."""
    result = extract_timestamp_str_from_suffix("fix_hook-12345-invalid")
    assert result is None


def testextract_timestamp_from_workflow_no_timestamp() -> None:
    """Test extracting timestamp from workflow without timestamp."""
    result = extract_timestamp_from_workflow("axe(crs)-critique")
    assert result is None

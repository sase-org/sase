"""Tests for query selection persistence."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.query_selection import (
    MAX_SELECTIONS,
    load_query_selections,
    save_query_selections,
)


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    """Test loading returns empty dict when no file exists."""
    with patch(
        "sase.ace.query_selection._QUERY_SELECTION_FILE", tmp_path / "nonexistent.json"
    ):
        result = load_query_selections()
        assert result == {}


def test_trimming_keeps_most_recent(tmp_path: Path) -> None:
    """Test that trimming keeps the most recently inserted entries."""
    test_file = tmp_path / "query_selections.json"
    with patch("sase.ace.query_selection._QUERY_SELECTION_FILE", test_file):
        selections: dict[str, str] = {}
        for i in range(MAX_SELECTIONS + 5):
            selections[f"q{i}"] = f"cl{i}"
        save_query_selections(selections)
        result = load_query_selections()
        # Oldest 5 entries (q0..q4) should be trimmed
        for i in range(5):
            assert f"q{i}" not in result
        # Most recent entries should remain
        assert f"q{MAX_SELECTIONS + 4}" in result
        assert result[f"q{MAX_SELECTIONS + 4}"] == f"cl{MAX_SELECTIONS + 4}"


def test_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    test_file = tmp_path / "query_selections.json"
    test_file.write_text("not valid json {")
    with patch("sase.ace.query_selection._QUERY_SELECTION_FILE", test_file):
        result = load_query_selections()
        assert result == {}


def test_handles_non_dict_json(tmp_path: Path) -> None:
    """Test that non-dict JSON is handled gracefully."""
    test_file = tmp_path / "query_selections.json"
    test_file.write_text('["a", "b"]')
    with patch("sase.ace.query_selection._QUERY_SELECTION_FILE", test_file):
        result = load_query_selections()
        assert result == {}

"""Tests for parsing and validation functions in the file_references module."""

import os
import tempfile

import pytest
from sase.gemini_wrapper.file_references import (
    _parse_file_refs,
    validate_file_references,
)

# Tests for _parse_file_refs


def test_parse_file_refs_duplicate_paths() -> None:
    """Test detecting duplicate file references."""
    result = _parse_file_refs("Check @file.txt and again @file.txt")
    assert result.seen_paths.get("file.txt", 0) == 2
    assert "file.txt" in result.duplicate_paths


def test_parse_file_refs_skips_urls() -> None:
    """Test that URL-like patterns are skipped."""
    result = _parse_file_refs("Visit @http://example.com")
    assert result.seen_paths == {}


def test_parse_file_refs_skips_domain_names() -> None:
    """Test that domain-like patterns are skipped."""
    result = _parse_file_refs("Email @google.com @github.io")
    assert result.seen_paths == {}


# Tests for validate_file_references


def test_validate_file_references_no_refs_passes() -> None:
    """Test that prompt without file refs passes validation."""
    # Should not raise
    validate_file_references("No file references here")


def test_validate_file_references_parent_dir_exits() -> None:
    """Test that parent dir path causes exit."""
    with pytest.raises(SystemExit) as exc_info:
        validate_file_references("Check @../some/file.txt")
    assert exc_info.value.code == 1


def test_validate_file_references_duplicate_exits() -> None:
    """Test that duplicate file refs cause exit."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        temp_path = f.name
    try:
        with pytest.raises(SystemExit) as exc_info:
            validate_file_references(f"Check @{temp_path} and @{temp_path}")
        assert exc_info.value.code == 1
    finally:
        os.unlink(temp_path)

"""Tests for suffix classification functions in ace/changespec/models.py."""

from sase.ace.changespec.models import (
    is_plain_suffix,
    is_running_process_suffix,
)


# Tests for is_running_process_suffix
def test_is_running_process_suffix_none() -> None:
    """Test that None suffix is not a running process."""
    assert is_running_process_suffix(None) is False


# Tests for is_plain_suffix
def test_is_plain_suffix_none() -> None:
    """Test that None suffix is not considered a plain suffix.

    Note: The removal condition uses 'suffix is None or is_plain_suffix(suffix)',
    so None is handled separately from plain suffixes.
    """
    assert is_plain_suffix(None) is False


def test_is_plain_suffix_commit_reference_multi_digit() -> None:
    """Test that multi-digit commit references are plain suffixes."""
    assert is_plain_suffix("12") is True
    assert is_plain_suffix("123") is True

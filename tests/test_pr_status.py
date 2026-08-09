"""Tests for ace.pr_status module."""

from unittest.mock import MagicMock, patch

from sase.ace.pr_status import (
    SYNCABLE_STATUSES,
    is_parent_submitted,
)

# === Tests for is_parent_submitted ===


def test_is_parent_submitted_no_parent() -> None:
    """Test that no parent means parent is considered submitted."""
    mock_patch = MagicMock()
    mock_patch.parent = None

    result = is_parent_submitted(mock_patch)

    assert result is True


@patch("sase.ace.pr_status.find_all_changespecs")  # legacy API path
def test_is_parent_submitted_parent_not_submitted(mock_find: MagicMock) -> None:
    """Test that non-submitted parent returns False."""
    mock_parent = MagicMock()
    mock_parent.name = "parent_cs"
    mock_parent.status = "Mailed"

    mock_find.return_value = [mock_parent]

    mock_patch = MagicMock()
    mock_patch.parent = "parent_cs"

    result = is_parent_submitted(mock_patch)

    assert result is False


@patch("sase.ace.pr_status.find_all_changespecs")  # legacy API path
def test_is_parent_submitted_parent_not_found(mock_find: MagicMock) -> None:
    """Test that missing parent returns True (assumed deleted)."""
    mock_find.return_value = []

    mock_patch = MagicMock()
    mock_patch.parent = "nonexistent_parent"

    result = is_parent_submitted(mock_patch)

    assert result is True


# === Tests for SYNCABLE_STATUSES constant ===


def test_syncable_statuses_contains_mailed() -> None:
    """Test that SYNCABLE_STATUSES contains Mailed."""
    assert "Mailed" in SYNCABLE_STATUSES

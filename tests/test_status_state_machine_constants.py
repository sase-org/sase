"""Tests for status_state_machine validation and transition checks."""

from sase.status_state_machine import (
    VALID_STATUSES,
    VALID_TRANSITIONS,
    is_valid_transition,
)


def test_valid_statuses_defined() -> None:
    """Test that all valid statuses are defined."""
    expected_statuses = [
        "WIP",
        "Draft",
        "Ready",
        "Mailed",
        "Submitted",
        "Reverted",
        "Archived",
    ]
    assert VALID_STATUSES == expected_statuses


def test_valid_transitions_defined() -> None:
    """Test that valid transitions are defined for all statuses."""
    # Ensure all valid statuses have an entry in transitions
    for status in VALID_STATUSES:
        assert status in VALID_TRANSITIONS


def test_is_valid_transition_invalid_status() -> None:
    """Test that invalid status names are rejected."""
    assert is_valid_transition("Invalid Status", "Mailed") is False
    assert is_valid_transition("Mailed", "Invalid Status") is False

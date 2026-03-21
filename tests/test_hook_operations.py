"""Tests for hook operations and ID mapping functions in accept_workflow module."""

from typing import Any

from sase.workflows.accept.renumber import (
    _build_entry_id_mapping,
    _update_hooks_with_id_mapping,
)
from sase.ace.changespec import get_entry_id


# Tests for _get_entry_id
def test_get_entry_id_regular() -> None:
    """Test getting entry ID for regular entry."""
    entry = {"number": 2, "letter": None}
    assert get_entry_id(entry) == "2"


def test_get_entry_id_proposal() -> None:
    """Test getting entry ID for proposal entry."""
    entry = {"number": 2, "letter": "a"}
    assert get_entry_id(entry) == "2a"


# Tests for _build_entry_id_mapping
def test_build_entry_id_mapping_multi_accept_first_promoted_others_archived() -> None:
    """Test that first accepted proposal is promoted, others are archived."""
    entries: list[dict[str, Any]] = [
        {"number": 1, "letter": None, "note": "First"},
        {"number": 1, "letter": "a", "note": "Proposal A"},
        {"number": 1, "letter": "b", "note": "Proposal B"},
        {"number": 1, "letter": "c", "note": "Proposal C"},
    ]
    new_entries: list[dict[str, Any]] = []  # Not used for this test
    # Accept c first, then a -> c becomes 2, a becomes 3
    accepted_proposals = [(1, "c"), (1, "a")]
    next_regular = 4  # After accepting 2 proposals: 2, 3
    remaining_proposals: list[dict[str, Any]] = [
        {"number": 1, "letter": "b", "note": "Proposal B"}
    ]

    promote_mapping, archive_mapping = _build_entry_id_mapping(
        entries, new_entries, accepted_proposals, next_regular, remaining_proposals
    )

    # First accepted (1c) promoted to 2, second (1a) also in promote for suffix updates
    assert promote_mapping["1c"] == "2"
    assert promote_mapping["1a"] == "3"
    # Remaining proposal keeps original ID unchanged
    assert promote_mapping["1b"] == "1b"
    # Second accepted (1a) has archive mapping
    assert archive_mapping == {"1a": "1a-3"}


# Tests for _update_hooks_with_id_mapping
def test_update_hooks_with_id_mapping_suffix_updated_for_archived() -> None:
    """Test that suffixes are updated to new ID even for archived proposals."""
    lines = [
        "NAME: test_cl\n",
        "STATUS: Ready\n",
        "HOOKS:\n",
        "  make lint\n",
        "      | (1a) [251224_120100] FAILED (30s) - (1a)\n",
    ]
    promote_mapping = {"1a": "3"}
    archive_mapping = {"1a": "1a-3"}

    result = _update_hooks_with_id_mapping(
        lines, "test_cl", promote_mapping, archive_mapping
    )

    # Prefix archived: (1a) -> (1a-3)
    # Suffix promoted: - (1a) -> - (3)
    assert "      | (1a-3) [251224_120100] FAILED (30s) - (3)\n" in result


def test_update_hooks_single_proposal_no_archive() -> None:
    """Test that single proposal acceptance works as before (no archiving)."""
    lines = [
        "NAME: test_cl\n",
        "STATUS: Ready\n",
        "HOOKS:\n",
        "  make lint\n",
        "      | (1a) [251224_120100] PASSED (30s)\n",
    ]
    promote_mapping = {"1a": "2"}
    archive_mapping: dict[str, str] = {}  # Empty - no archiving for single proposal

    result = _update_hooks_with_id_mapping(
        lines, "test_cl", promote_mapping, archive_mapping
    )

    # Promoted normally: (1a) -> (2)
    assert "      | (2) [251224_120100] PASSED (30s)\n" in result


# Tests for sort_hook_status_lines

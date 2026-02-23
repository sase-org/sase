"""Tests for proposal parsing and lookup functions in accept_workflow module."""

import os
import tempfile

from sase.accept_workflow import (
    expand_shorthand_proposals,
    find_proposal_entry,
    parse_proposal_entries,
    parse_proposal_entries_with_shorthand,
    parse_proposal_id,
)
from sase.ace.changespec import CommitEntry
from sase.workflow_utils import get_changespec_from_file


# Tests for parse_proposal_id
def testparse_proposal_id_invalid_letters_only() -> None:
    """Test parsing proposal ID with letters only."""
    result = parse_proposal_id("abc")
    assert result is None


# Tests for parse_proposal_entries
def test_parse_proposal_entries_legacy_syntax() -> None:
    """Test parsing legacy syntax with separate message argument."""
    result = parse_proposal_entries(["2a", "some message"])
    assert result == [("2a", "some message")]


def test_parse_proposal_entries_invalid_format() -> None:
    """Test that invalid format returns None."""
    result = parse_proposal_entries(["invalid"])
    assert result is None


def test_parse_proposal_entries_empty_list() -> None:
    """Test that empty list returns None."""
    result = parse_proposal_entries([])
    assert result is None


def test_parse_proposal_entries_complex_mix() -> None:
    """Test complex mix of entries."""
    result = parse_proposal_entries(["1a(First)", "1b", "2a(Second change)"])
    assert result == [("1a", "First"), ("1b", None), ("2a", "Second change")]


# Tests for expand_shorthand_proposals
def test_expand_shorthand_proposals_mixed() -> None:
    """Test mixing shorthand and full IDs."""
    result = expand_shorthand_proposals(["a", "2b(msg)", "c(fix)"], "3")
    assert result == ["3a", "2b(msg)", "3c(fix)"]


def test_expand_shorthand_proposals_invalid_format() -> None:
    """Test that invalid format returns None."""
    result = expand_shorthand_proposals(["invalid"], "2")
    assert result is None


# Tests for parse_proposal_entries_with_shorthand
def test_parse_proposal_entries_with_shorthand_bare_letters() -> None:
    """Test parsing bare letter shortcuts."""
    result = parse_proposal_entries_with_shorthand(["a", "b"], "2")
    assert result == [("2a", None), ("2b", None)]


def test_parse_proposal_entries_with_shorthand_no_base() -> None:
    """Test that shorthand without base returns None."""
    result = parse_proposal_entries_with_shorthand(["a", "b"], None)
    assert result is None


# Tests for find_proposal_entry
def testfind_proposal_entry_found() -> None:
    """Test finding proposal entry that exists."""
    history = [
        CommitEntry(number=1, note="First commit"),
        CommitEntry(number=2, note="Second commit"),
        CommitEntry(number=2, note="First proposal", proposal_letter="a"),
        CommitEntry(number=2, note="Second proposal", proposal_letter="b"),
    ]
    result = find_proposal_entry(history, 2, "a")
    assert result is not None
    assert result.note == "First proposal"


def testfind_proposal_entry_not_found_wrong_letter() -> None:
    """Test finding proposal entry with wrong letter."""
    history = [
        CommitEntry(number=2, note="First proposal", proposal_letter="a"),
    ]
    result = find_proposal_entry(history, 2, "b")
    assert result is None


def testfind_proposal_entry_none_history() -> None:
    """Test finding proposal entry with None history."""
    result = find_proposal_entry(None, 2, "a")
    assert result is None


# Tests for get_changespec_from_file
def test_get_changespec_from_file_multiple_specs() -> None:
    """Test getting changespec from file with multiple specs."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: first_cl\n")
        f.write("STATUS: Ready\n")
        f.write("\n")
        f.write("NAME: second_cl\n")
        f.write("STATUS: Mailed\n")
        temp_path = f.name

    try:
        result = get_changespec_from_file(temp_path, "second_cl")
        assert result is not None
        assert result.name == "second_cl"
    finally:
        os.unlink(temp_path)

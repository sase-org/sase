"""Tests for ace/hooks/history.py - history entry utilities."""

from typing import Any

from sase.ace.changespec import CommitEntry
from sase.ace.hooks.history import (
    get_history_entry_by_id,
    get_last_accepted_history_entry_id,
    get_last_history_entry,
)


# Tests for get_last_history_entry_id
# Tests for get_last_history_entry
def test_get_last_history_entry_empty_commits(make_changespec: Any) -> None:
    """Test get_last_history_entry returns None for empty commits."""
    cs = make_changespec.create(commits=[])
    assert get_last_history_entry(cs) is None


def test_get_last_history_entry_single_commit(make_changespec: Any) -> None:
    """Test get_last_history_entry returns single commit."""
    commit = CommitEntry(number=1, note="First commit")
    cs = make_changespec.create(commits=[commit])
    result = get_last_history_entry(cs)
    assert result is commit


# Tests for get_last_accepted_history_entry_id
def test_get_last_accepted_history_entry_id_empty_commits(make_changespec: Any) -> None:
    """Test get_last_accepted_history_entry_id returns None for empty commits."""
    cs = make_changespec.create(commits=[])
    assert get_last_accepted_history_entry_id(cs) is None


def test_get_last_accepted_history_entry_id_skips_proposals(
    make_changespec: Any,
) -> None:
    """Test get_last_accepted_history_entry_id skips proposal entries."""
    commits = [
        CommitEntry(number=1, note="First commit"),
        CommitEntry(number=2, note="Second commit"),
        CommitEntry(number=2, note="Proposal A", proposal_letter="a"),
        CommitEntry(number=2, note="Proposal B", proposal_letter="b"),
    ]
    cs = make_changespec.create(commits=commits)
    # Should return "2" (the last all-numeric), not "2b"
    assert get_last_accepted_history_entry_id(cs) == "2"


def test_get_last_accepted_history_entry_id_all_proposals(make_changespec: Any) -> None:
    """Test get_last_accepted_history_entry_id returns None when all are proposals."""
    commits = [
        CommitEntry(number=1, note="Proposal A", proposal_letter="a"),
        CommitEntry(number=1, note="Proposal B", proposal_letter="b"),
    ]
    cs = make_changespec.create(commits=commits)
    assert get_last_accepted_history_entry_id(cs) is None


# Tests for is_proposal_entry
# Tests for get_history_entry_by_id
def test_get_history_entry_by_id_none_commits(make_changespec: Any) -> None:
    """Test get_history_entry_by_id returns None when commits is None."""
    cs = make_changespec.create(commits=None)
    assert get_history_entry_by_id(cs, "1") is None


def test_get_history_entry_by_id_not_found(make_changespec: Any) -> None:
    """Test get_history_entry_by_id returns None when ID not found."""
    commits = [
        CommitEntry(number=1, note="First commit"),
        CommitEntry(number=2, note="Second commit"),
    ]
    cs = make_changespec.create(commits=commits)
    assert get_history_entry_by_id(cs, "3") is None
    assert get_history_entry_by_id(cs, "99") is None


def test_get_history_entry_by_id_proposal(make_changespec: Any) -> None:
    """Test get_history_entry_by_id finds proposal entries."""
    commits = [
        CommitEntry(number=1, note="First commit"),
        CommitEntry(number=2, note="Second commit"),
        CommitEntry(number=2, note="Proposal A", proposal_letter="a"),
    ]
    cs = make_changespec.create(commits=commits)
    result = get_history_entry_by_id(cs, "2a")
    assert result is commits[2]
    assert result.note == "Proposal A"

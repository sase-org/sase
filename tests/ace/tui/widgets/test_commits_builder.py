"""Tests for the Patch commits section builder."""

from sase.ace.patch import CommitEntry
from sase.ace.testing import make_patch
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.commits_builder import _should_show_commits_drawers


def test_should_show_commits_drawers_expanded() -> None:
    """All entries show drawers when expanded."""
    entry = CommitEntry(number=5, note="test")
    patch = make_patch(
        commits=[
            CommitEntry(number=1, note="first"),
            CommitEntry(number=5, note="test"),
        ]
    )

    assert _should_show_commits_drawers(entry, patch, FoldLevel.EXPANDED)


def test_should_show_commits_drawers_collapsed_intermediate_hidden() -> None:
    """Intermediate entries hide drawers when collapsed."""
    entry = CommitEntry(number=3, note="intermediate")
    patch = make_patch(
        commits=[
            CommitEntry(number=1, note="first"),
            CommitEntry(number=3, note="intermediate"),
            CommitEntry(number=5, note="current"),
        ]
    )

    assert not _should_show_commits_drawers(entry, patch, FoldLevel.COLLAPSED)


def test_should_show_commits_drawers_collapsed_old_proposal_hidden() -> None:
    """Old proposal entries (not for max ID) hide drawers when collapsed."""
    entry = CommitEntry(number=2, note="old proposal", proposal_letter="a")
    patch = make_patch(
        commits=[
            CommitEntry(number=1, note="first"),
            CommitEntry(number=2, note="second"),
            CommitEntry(number=2, note="old proposal", proposal_letter="a"),
            CommitEntry(number=5, note="current"),
        ]
    )

    assert not _should_show_commits_drawers(entry, patch, FoldLevel.COLLAPSED)


def test_should_show_commits_drawers_collapsed_multiple_proposals_shown() -> None:
    """Multiple proposals for max ID all show drawers when collapsed."""
    patch = make_patch(
        commits=[
            CommitEntry(number=1, note="first"),
            CommitEntry(number=3, note="current"),
            CommitEntry(number=3, note="proposal a", proposal_letter="a"),
            CommitEntry(number=3, note="proposal b", proposal_letter="b"),
        ]
    )

    entry_a = CommitEntry(number=3, note="proposal a", proposal_letter="a")
    entry_b = CommitEntry(number=3, note="proposal b", proposal_letter="b")

    assert _should_show_commits_drawers(entry_a, patch, FoldLevel.COLLAPSED)
    assert _should_show_commits_drawers(entry_b, patch, FoldLevel.COLLAPSED)

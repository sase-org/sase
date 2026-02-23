"""Tests for conflict checking in accept workflow."""

from unittest.mock import MagicMock, patch

from sase.accept_workflow.conflict_check import (
    ConflictCheckResult,
    ConflictPair,
    format_conflict_message,
    run_conflict_check,
)
from sase.ace.changespec import CommitEntry


def _make_entry(number: int, letter: str, diff: str) -> CommitEntry:
    """Create a CommitEntry for testing."""
    return CommitEntry(
        number=number,
        note=f"Test proposal {number}{letter}",
        diff=diff,
        proposal_letter=letter,
    )


def test_run_conflict_check_empty_proposals_returns_success() -> None:
    """Test that empty proposals returns success."""
    result = run_conflict_check("/workspace", [], verbose=False)
    assert result.success is True
    assert result.failed_proposal is None
    assert result.conflicting_pairs == []


@patch("sase.accept_workflow.conflict_check.clean_workspace")
@patch("sase.accept_workflow.conflict_check.apply_diffs_to_workspace")
def test_run_conflict_check_two_proposals_no_conflict(
    mock_apply: MagicMock,
    mock_clean: MagicMock,
) -> None:
    """Test two proposals that don't conflict."""
    mock_apply.return_value = (True, "")
    mock_clean.return_value = True

    entry_a = _make_entry(2, "a", "~/.sase/diffs/a.diff")
    entry_b = _make_entry(2, "b", "~/.sase/diffs/b.diff")
    validated = [(2, "a", None, entry_a), (2, "b", "extra msg", entry_b)]

    result = run_conflict_check("/workspace", validated, verbose=False)

    assert result.success is True
    assert result.failed_proposal is None
    assert result.conflicting_pairs == []
    # Should have applied both proposals together in single call
    assert mock_apply.call_count == 1


@patch("sase.accept_workflow.conflict_check.clean_workspace")
@patch("sase.accept_workflow.conflict_check.apply_diffs_to_workspace")
def test_run_conflict_check_two_proposals_with_conflict(
    mock_apply: MagicMock,
    mock_clean: MagicMock,
) -> None:
    """Test two proposals that conflict (no pair detection for 2 proposals)."""
    # Both proposals fail when applied together
    mock_apply.return_value = (False, "patch failed")
    mock_clean.return_value = True

    entry_a = _make_entry(2, "a", "~/.sase/diffs/a.diff")
    entry_b = _make_entry(2, "b", "~/.sase/diffs/b.diff")
    validated: list[tuple[int, str, str | None, CommitEntry]] = [
        (2, "a", None, entry_a),
        (2, "b", None, entry_b),
    ]

    result = run_conflict_check("/workspace", validated, verbose=False)

    assert result.success is False
    # Can't determine which proposal failed when applying together
    assert result.failed_proposal is None
    # No pair detection for 2 proposals
    assert result.conflicting_pairs == []


@patch("sase.accept_workflow.conflict_check.clean_workspace")
@patch("sase.accept_workflow.conflict_check.apply_diffs_to_workspace")
def test_run_conflict_check_three_proposals_triggers_pair_detection(
    mock_apply: MagicMock,
    mock_clean: MagicMock,
) -> None:
    """Test three proposals triggers pair detection when conflict found."""
    # All three together fails, then pair testing shows A+B conflicts
    mock_clean.return_value = True

    call_count = 0

    def apply_side_effect(
        _workspace_dir: str, diff_paths: list[str]
    ) -> tuple[bool, str]:
        nonlocal call_count
        call_count += 1

        # Initial phase: all 3 together (fails)
        if call_count == 1:
            return (False, "patch conflict")

        # Pair testing phase (each pair tested with single hg import):
        # Pair (A,B): conflicts
        if call_count == 2:
            return (False, "patch conflict")

        # Pair (A,C): succeeds
        if call_count == 3:
            return (True, "")

        # Pair (B,C): succeeds
        if call_count == 4:
            return (True, "")

        return (True, "")

    mock_apply.side_effect = apply_side_effect

    entry_a = _make_entry(2, "a", "~/.sase/diffs/a.diff")
    entry_b = _make_entry(2, "b", "~/.sase/diffs/b.diff")
    entry_c = _make_entry(2, "c", "~/.sase/diffs/c.diff")
    validated: list[tuple[int, str, str | None, CommitEntry]] = [
        (2, "a", None, entry_a),
        (2, "b", None, entry_b),
        (2, "c", None, entry_c),
    ]

    result = run_conflict_check("/workspace", validated, verbose=False)

    assert result.success is False
    # Can't determine which proposal failed when applying together
    assert result.failed_proposal is None
    assert len(result.conflicting_pairs) == 1
    assert result.conflicting_pairs[0].proposal_a == (2, "a")
    assert result.conflicting_pairs[0].proposal_b == (2, "b")


def test_conflict_check_result_dataclass() -> None:
    """Test ConflictCheckResult dataclass fields."""
    result = ConflictCheckResult(
        success=False,
        failed_proposal=(2, "b"),
        conflicting_pairs=[
            ConflictPair(
                proposal_a=(2, "a"),
                proposal_b=(2, "b"),
                error_message="conflict",
            )
        ],
    )
    assert result.success is False
    assert result.failed_proposal == (2, "b")
    assert len(result.conflicting_pairs) == 1


def test_conflict_pair_dataclass() -> None:
    """Test ConflictPair dataclass fields."""
    pair = ConflictPair(
        proposal_a=(1, "a"),
        proposal_b=(1, "b"),
        error_message="test error",
    )
    assert pair.proposal_a == (1, "a")
    assert pair.proposal_b == (1, "b")
    assert pair.error_message == "test error"


def test_format_conflict_message_single_pair() -> None:
    """Test formatting with a single conflicting pair."""
    result = ConflictCheckResult(
        success=False,
        failed_proposal=None,
        conflicting_pairs=[
            ConflictPair(
                proposal_a=(2, "a"),
                proposal_b=(2, "b"),
                error_message="patch conflict",
            )
        ],
    )
    message = format_conflict_message(result)
    lines = message.split("\n")
    assert len(lines) == 2
    assert lines[0] == "Conflicting pair: (2a) and (2b)"
    assert (
        lines[1]
        == "Accept aborted. Try accepting non-conflicting proposals separately."
    )


def test_accept_workflow_conflict_result_initially_none() -> None:
    """Test that AcceptWorkflow.conflict_result is None initially."""
    from sase.accept_workflow import AcceptWorkflow

    workflow = AcceptWorkflow(
        proposals=[("2a", None)],
        cl_name="test-cl",
    )
    assert workflow.conflict_result is None

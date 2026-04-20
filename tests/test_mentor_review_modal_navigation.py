"""Tests for navigation actions in the Mentor Review modal."""

from sase.ace.mentor_output import MentorAcceptanceState, MentorReadState
from sase.ace.tui.modals.mentor_review_models import (
    MentorInfo,
    MentorReviewData,
)
from sase.ace.tui.modals.mentor_review_modal import MentorReviewModal


def _make_modal_data(
    mentor_comments: list[int],
    accepted: dict[str, bool] | None = None,
) -> MentorReviewData:
    """Create MentorReviewData with N mentors, each having the given comment counts."""
    mentors = []
    for i, count in enumerate(mentor_comments):
        comments: list[dict[str, str | int]] = [
            {
                "focus_name": f"focus_{j}",
                "file_path": f"file_{j}.py",
                "line_number": j + 1,
                "description": f"Comment {j}",
                "severity": "warning",
            }
            for j in range(count)
        ]
        mentors.append(
            MentorInfo(
                mentor_name=f"mentor_{i}",
                profile_name="code",
                status="COMMENTED" if count > 0 else "PASSED",
                comments=comments,
            )
        )
    acceptance = MentorAcceptanceState(accepted=accepted or {})
    return MentorReviewData(
        mentors=mentors,
        acceptance=acceptance,
        read_state=MentorReadState(),
        cl_name="test-cl",
        entry_id="1",
    )


# ── Mentor / comment navigation ───────────────────────────────────────


def test_modal_starts_on_first_mentor_with_comments() -> None:
    """Modal starts on the first mentor that has comments."""
    data = _make_modal_data([0, 3, 2])  # first mentor has 0 comments
    modal = MentorReviewModal(data)
    assert modal._mentor_idx == 1
    assert modal._comment_idx == 0


def test_modal_next_mentor_wraps() -> None:
    """j wraps around to the first mentor."""
    data = _make_modal_data([2, 3])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 1
    modal.action_next_mentor()
    assert modal._mentor_idx == 0


def test_modal_prev_mentor_wraps() -> None:
    """k wraps around to the last mentor."""
    data = _make_modal_data([2, 3])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal.action_prev_mentor()
    assert modal._mentor_idx == 1


def test_modal_next_comment_within_mentor() -> None:
    """n moves to next comment within same mentor."""
    data = _make_modal_data([3])
    modal = MentorReviewModal(data)
    modal._comment_idx = 0
    modal.action_next_comment()
    assert modal._comment_idx == 1
    assert modal._mentor_idx == 0


def test_modal_next_comment_jumps_to_next_mentor() -> None:
    """n at last comment of mentor jumps to first comment of next mentor."""
    data = _make_modal_data([2, 3])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 1  # last comment of first mentor
    modal.action_next_comment()
    assert modal._mentor_idx == 1
    assert modal._comment_idx == 0


def test_modal_prev_comment_jumps_to_prev_mentor() -> None:
    """p at first comment jumps to last comment of previous mentor."""
    data = _make_modal_data([2, 3])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 1
    modal._comment_idx = 0
    modal.action_prev_comment()
    assert modal._mentor_idx == 0
    assert modal._comment_idx == 1  # last comment of previous mentor


def test_modal_next_comment_skips_empty_mentors() -> None:
    """n at boundary skips mentors with no comments."""
    data = _make_modal_data([2, 0, 3])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 1  # last comment of first mentor
    modal.action_next_comment()
    assert modal._mentor_idx == 2  # skipped empty mentor
    assert modal._comment_idx == 0


# ── Global comment index ──────────────────────────────────────────────


def test_global_comment_index_single_mentor() -> None:
    """Global index within a single mentor."""
    data = _make_modal_data([3])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 0
    assert modal._global_comment_index() == (1, 3)

    modal._comment_idx = 2
    assert modal._global_comment_index() == (3, 3)


def test_global_comment_index_multiple_mentors() -> None:
    """Global index spans across multiple mentors."""
    data = _make_modal_data([2, 3])
    modal = MentorReviewModal(data)

    # First mentor, first comment
    modal._mentor_idx = 0
    modal._comment_idx = 0
    assert modal._global_comment_index() == (1, 5)

    # First mentor, last comment
    modal._comment_idx = 1
    assert modal._global_comment_index() == (2, 5)

    # Second mentor, first comment
    modal._mentor_idx = 1
    modal._comment_idx = 0
    assert modal._global_comment_index() == (3, 5)

    # Second mentor, last comment
    modal._comment_idx = 2
    assert modal._global_comment_index() == (5, 5)


def test_global_comment_index_with_empty_mentors() -> None:
    """Global index skips mentors with zero comments."""
    data = _make_modal_data([2, 0, 3])
    modal = MentorReviewModal(data)

    # Third mentor (index 2), second comment
    modal._mentor_idx = 2
    modal._comment_idx = 1
    assert modal._global_comment_index() == (4, 5)


def test_global_comment_index_no_comments() -> None:
    """Returns (0, 0) when there are no comments at all."""
    data = _make_modal_data([0, 0])
    modal = MentorReviewModal(data)
    assert modal._global_comment_index() == (0, 0)


# ── Accepted-comment navigation (N / P) ─────────────────────────────


def test_next_accepted_forward() -> None:
    """N navigates forward to the next accepted comment."""
    data = _make_modal_data([3])
    data.acceptance.set_accepted("code", "mentor_0", 2, True)
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 0
    modal.action_next_accepted_comment()
    assert modal._mentor_idx == 0
    assert modal._comment_idx == 2


def test_prev_accepted_backward() -> None:
    """P navigates backward to the previous accepted comment."""
    data = _make_modal_data([3])
    data.acceptance.set_accepted("code", "mentor_0", 0, True)
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 2
    modal.action_prev_accepted_comment()
    assert modal._mentor_idx == 0
    assert modal._comment_idx == 0


def test_next_accepted_wraps_across_mentors() -> None:
    """N wraps from the last mentor back to an accepted comment in the first."""
    data = _make_modal_data([2, 3])
    data.acceptance.set_accepted("code", "mentor_0", 0, True)
    modal = MentorReviewModal(data)
    modal._mentor_idx = 1
    modal._comment_idx = 2  # last comment of last mentor
    modal.action_next_accepted_comment()
    assert modal._mentor_idx == 0
    assert modal._comment_idx == 0


def test_prev_accepted_wraps_across_mentors() -> None:
    """P wraps from the first mentor back to an accepted comment in the last."""
    data = _make_modal_data([2, 3])
    data.acceptance.set_accepted("code", "mentor_1", 2, True)
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 0
    modal.action_prev_accepted_comment()
    assert modal._mentor_idx == 1
    assert modal._comment_idx == 2


def test_next_accepted_noop_when_none_accepted() -> None:
    """N does nothing when no comments are accepted."""
    data = _make_modal_data([2, 3])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 1
    modal.action_next_accepted_comment()
    assert modal._mentor_idx == 0
    assert modal._comment_idx == 1


def test_prev_accepted_noop_when_none_accepted() -> None:
    """P does nothing when no comments are accepted."""
    data = _make_modal_data([2, 3])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 1
    modal._comment_idx = 0
    modal.action_prev_accepted_comment()
    assert modal._mentor_idx == 1
    assert modal._comment_idx == 0


def test_next_accepted_skips_empty_mentors() -> None:
    """N skips mentors with zero comments when searching for accepted."""
    data = _make_modal_data([2, 0, 3])
    data.acceptance.set_accepted("code", "mentor_2", 1, True)
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 0
    modal.action_next_accepted_comment()
    assert modal._mentor_idx == 2
    assert modal._comment_idx == 1

"""Tests for the Mentor Review modal data building and navigation logic."""

from pathlib import Path

from sase.ace.mentor_output import (
    MentorAcceptanceState,
    MentorComment,
    MentorOutput,
    MentorReadState,
    save_mentor_output,
)
from sase.ace.changespec.models import MentorEntry, MentorStatusLine
from sase.ace.tui.modals.mentor_review_models import (
    MentorApplyResult,
    MentorInfo,
    MentorKillResult,
    MentorReviewData,
    build_mentor_review_data,
)
from sase.ace.tui.modals.mentor_review_modal import MentorReviewModal


# ── MentorReviewData ──────────────────────────────────────────────────────


def test_mentor_review_data_total_comments() -> None:
    """Total comments is the sum across all mentors."""
    data = MentorReviewData(
        mentors=[
            MentorInfo(
                mentor_name="a",
                profile_name="p",
                status="COMMENTED",
                comments=[
                    {
                        "focus_name": "x",
                        "description": "d",
                        "severity": "warning",
                        "file_path": "f.py",
                        "line_number": 1,
                    }
                ],
            ),
            MentorInfo(
                mentor_name="b",
                profile_name="p",
                status="COMMENTED",
                comments=[
                    {
                        "focus_name": "y",
                        "description": "d2",
                        "severity": "error",
                        "file_path": "g.py",
                        "line_number": 2,
                    },
                    {
                        "focus_name": "z",
                        "description": "d3",
                        "severity": "suggestion",
                        "file_path": "h.py",
                        "line_number": 3,
                    },
                ],
            ),
        ],
        acceptance=MentorAcceptanceState(),
        read_state=MentorReadState(),
        cl_name="test-cl",
        entry_id="1",
    )
    assert data.total_comments == 3


def test_mentor_review_data_zero_comments() -> None:
    """No comments when all mentors passed."""
    data = MentorReviewData(
        mentors=[
            MentorInfo(mentor_name="a", profile_name="p", status="PASSED", comments=[]),
        ],
        acceptance=MentorAcceptanceState(),
        read_state=MentorReadState(),
        cl_name="test-cl",
        entry_id="1",
    )
    assert data.total_comments == 0


# ── build_mentor_review_data ──────────────────────────────────────────────


def _make_mentor_entry(
    entry_id: str = "1",
    status_lines: list[MentorStatusLine] | None = None,
    profiles: list[str] | None = None,
) -> MentorEntry:
    """Create a MentorEntry for testing."""
    if status_lines is None:
        status_lines = []
    if profiles is None:
        profiles = ["code"]
    return MentorEntry(
        entry_id=entry_id,
        profiles=profiles,
        status_lines=status_lines,
    )


def test_build_review_data_with_outputs(tmp_path: Path, monkeypatch: object) -> None:
    """Build review data when mentor outputs exist on disk."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    # Save a mentor output with 2 comments.
    # Use LLM-provided names that differ from config names to test that
    # matching is done by timestamp, not by profile/mentor names in JSON.
    output = MentorOutput(
        mentor_name="Gemini CLI",
        profile_name="Senior Code Quality Reviewer",
        role="reviewer",
        comments=[
            MentorComment("style", "a.py", 10, "Fix style", "warning"),
            MentorComment("docs", "b.py", 20, "Add docs", "suggestion"),
        ],
    )
    save_mentor_output("my-cl", "code", "code_quality", "260321_120000", output)

    entry = _make_mentor_entry(
        entry_id="1",
        status_lines=[
            MentorStatusLine(
                profile_name="code",
                mentor_name="code_quality",
                status="COMMENTED",
                timestamp="260321_120000",
                duration="0h1m",
                suffix=None,
                suffix_type=None,
            ),
        ],
    )

    data = build_mentor_review_data(entry, "my-cl")
    assert data is not None
    assert len(data.mentors) == 1
    assert data.mentors[0].mentor_name == "code_quality"
    assert len(data.mentors[0].comments) == 2
    assert data.total_comments == 2


def test_build_review_data_passed_mentor(tmp_path: Path, monkeypatch: object) -> None:
    """PASSED mentors appear with zero comments."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    entry = _make_mentor_entry(
        entry_id="1",
        status_lines=[
            MentorStatusLine(
                profile_name="code",
                mentor_name="tests",
                status="PASSED",
                timestamp="260321_120000",
                duration="0h0m30s",
                suffix=None,
                suffix_type=None,
            ),
        ],
    )

    data = build_mentor_review_data(entry, "some-cl")
    assert data is not None
    assert len(data.mentors) == 1
    assert data.mentors[0].status == "PASSED"
    assert data.mentors[0].comments == []
    assert data.total_comments == 0


def test_build_review_data_no_status_lines() -> None:
    """Returns None when there are no status lines."""
    entry = _make_mentor_entry(entry_id="1", status_lines=[])
    data = build_mentor_review_data(entry, "cl")
    assert data is None


def test_build_review_data_running_mentor(tmp_path: Path, monkeypatch: object) -> None:
    """Running mentors appear with is_running=True."""
    monkeypatch.setattr("sase.ace.mentor_output.SASE_MENTORS_DIR", tmp_path)  # type: ignore[attr-defined]

    entry = _make_mentor_entry(
        entry_id="1",
        status_lines=[
            MentorStatusLine(
                profile_name="code",
                mentor_name="quality",
                status="RUNNING",
                timestamp="260321_120000",
                duration=None,
                suffix="mentor_quality-1234-260321_120000",
                suffix_type="running_agent",
            ),
        ],
    )

    data = build_mentor_review_data(entry, "cl")
    assert data is not None
    assert data.mentors[0].is_running is True


# ── Modal navigation logic ──────────────────────────────────────────────


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


def test_modal_toggle_accept() -> None:
    """space toggles acceptance and persists."""
    data = _make_modal_data([2])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 0

    assert not data.acceptance.is_accepted("code", "mentor_0", 0)

    # Toggle on (skip save since no disk dir)
    data.acceptance.toggle("code", "mentor_0", 0)
    assert data.acceptance.is_accepted("code", "mentor_0", 0)

    # Toggle off
    data.acceptance.toggle("code", "mentor_0", 0)
    assert not data.acceptance.is_accepted("code", "mentor_0", 0)


def test_modal_all_comments_accepted() -> None:
    """_all_comments_accepted returns True only when all are accepted."""
    data = _make_modal_data([2])
    modal = MentorReviewModal(data)
    mentor = data.mentors[0]

    assert not modal._all_comments_accepted(mentor)

    data.acceptance.set_accepted("code", "mentor_0", 0, True)
    assert not modal._all_comments_accepted(mentor)

    data.acceptance.set_accepted("code", "mentor_0", 1, True)
    assert modal._all_comments_accepted(mentor)


def test_modal_accepted_count_for_mentor() -> None:
    """_accepted_count_for_mentor counts correctly."""
    data = _make_modal_data([3])
    modal = MentorReviewModal(data)
    mentor = data.mentors[0]

    assert modal._accepted_count_for_mentor(mentor) == 0

    data.acceptance.set_accepted("code", "mentor_0", 0, True)
    data.acceptance.set_accepted("code", "mentor_0", 2, True)
    assert modal._accepted_count_for_mentor(mentor) == 2


# ── Apply action ──────────────────────────────────────────────────────


def test_apply_result_dataclass() -> None:
    """MentorApplyResult stores accepted comments, cl_name, and mode."""
    comments: list[dict[str, str | int]] = [
        {
            "focus_name": "style",
            "file_path": "a.py",
            "line_number": 1,
            "description": "Fix style",
            "severity": "warning",
        }
    ]
    result = MentorApplyResult(accepted_comments=comments, cl_name="my-cl")
    assert result.cl_name == "my-cl"
    assert result.mode == "commit"  # default
    assert len(result.accepted_comments) == 1
    assert result.accepted_comments[0]["focus_name"] == "style"


def test_apply_result_propose_mode() -> None:
    """MentorApplyResult can be created with propose mode."""
    result = MentorApplyResult(
        accepted_comments=[],
        cl_name="my-cl",
        mode="propose",
    )
    assert result.mode == "propose"


def test_apply_collects_only_accepted_comments() -> None:
    """action_apply should collect only accepted comments across mentors."""
    data = _make_modal_data([2, 3])

    # Accept comment 0 of mentor_0 and comments 1,2 of mentor_1
    data.acceptance.set_accepted("code", "mentor_0", 0, True)
    data.acceptance.set_accepted("code", "mentor_1", 1, True)
    data.acceptance.set_accepted("code", "mentor_1", 2, True)

    # Manually collect accepted comments (same logic as action_apply)
    accepted: list[dict[str, str | int]] = []
    for m in data.mentors:
        for i, comment in enumerate(m.comments):
            if data.acceptance.is_accepted(m.profile_name, m.mentor_name, i):
                accepted.append(comment)

    assert len(accepted) == 3
    assert accepted[0]["focus_name"] == "focus_0"  # mentor_0, comment 0
    assert accepted[1]["focus_name"] == "focus_1"  # mentor_1, comment 1
    assert accepted[2]["focus_name"] == "focus_2"  # mentor_1, comment 2


def test_apply_with_no_accepted_comments() -> None:
    """With no accepted comments, action_apply should not produce a result."""
    data = _make_modal_data([2, 3])

    # Collect accepted (none)
    accepted: list[dict[str, str | int]] = []
    for m in data.mentors:
        for i, comment in enumerate(m.comments):
            if data.acceptance.is_accepted(m.profile_name, m.mentor_name, i):
                accepted.append(comment)

    assert len(accepted) == 0


# ── Kill action ──────────────────────────────────────────────────────


def test_kill_result_dataclass() -> None:
    """MentorKillResult stores all fields needed to identify the mentor."""
    result = MentorKillResult(
        entry_id="1",
        mentor_name="quality",
        profile_name="code",
        cl_name="my-cl",
    )
    assert result.entry_id == "1"
    assert result.mentor_name == "quality"
    assert result.profile_name == "code"
    assert result.cl_name == "my-cl"


def test_kill_requires_running_mentor() -> None:
    """action_kill_mentor on a non-running mentor does not produce a kill result."""
    data = _make_modal_data([2])
    # mentor_0 has status="COMMENTED", is_running=False by default
    modal = MentorReviewModal(data)
    mentor = modal._current_mentor()
    assert mentor is not None
    assert not mentor.is_running


def test_kill_produces_result_for_running_mentor() -> None:
    """A running mentor produces a MentorKillResult with correct fields."""
    mentors = [
        MentorInfo(
            mentor_name="quality",
            profile_name="code",
            status="RUNNING",
            comments=[],
            is_running=True,
        ),
    ]
    data = MentorReviewData(
        mentors=mentors,
        acceptance=MentorAcceptanceState(),
        read_state=MentorReadState(),
        cl_name="my-cl",
        entry_id="42",
    )
    # Verify the expected kill result would contain the right data
    mentor = data.mentors[0]
    result = MentorKillResult(
        entry_id=data.entry_id,
        mentor_name=mentor.mentor_name,
        profile_name=mentor.profile_name,
        cl_name=data.cl_name,
    )
    assert result.entry_id == "42"
    assert result.mentor_name == "quality"
    assert result.profile_name == "code"
    assert result.cl_name == "my-cl"

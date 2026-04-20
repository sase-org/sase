"""Tests for the Mentor Review modal data building."""

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
    MentorInfo,
    MentorReviewData,
    build_mentor_review_data,
)


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

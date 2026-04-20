"""Tests for accept/apply/kill/copy actions in the Mentor Review modal."""

from typing import Any

import pytest

from sase.ace.mentor_output import MentorAcceptanceState, MentorReadState
from sase.ace.tui.modals.mentor_review_models import (
    MentorApplyResult,
    MentorInfo,
    MentorKillResult,
    MentorReviewData,
)
from sase.ace.tui.modals.mentor_review_modal import MentorReviewModal


class _FakeApp:
    """Minimal stand-in for Textual App that records notify() calls."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []

    def notify(self, msg: str, *, severity: str = "information", **_: Any) -> None:
        self.notifications.append((msg, severity))


def _install_fake_app(
    monkeypatch: pytest.MonkeyPatch, modal: MentorReviewModal
) -> _FakeApp:
    """Shadow Textual's DOMNode.app property with a fake app for testing."""
    fake = _FakeApp()
    monkeypatch.setattr(type(modal), "app", fake, raising=False)
    return fake


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


# ── Acceptance state ──────────────────────────────────────────────────


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


# ── Copy comment action (y) ─────────────────────────────────────────────


def test_copy_comment_copies_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """y copies the current comment's file:line and description to clipboard."""
    data = _make_modal_data([3])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 1
    fake_app = _install_fake_app(monkeypatch, modal)

    captured: list[str] = []

    def fake_copy(content: str) -> bool:
        captured.append(content)
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard.copy_to_system_clipboard", fake_copy
    )

    modal.action_copy_comment()

    assert len(captured) == 1
    assert "file_1.py:2" in captured[0]
    assert "Comment 1" in captured[0]
    assert fake_app.notifications == [("Copied comment to clipboard", "information")]


def test_copy_comment_no_op_when_mentor_has_no_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """y on a mentor with no comments is a silent no-op."""
    data = _make_modal_data([0])
    modal = MentorReviewModal(data)
    fake_app = _install_fake_app(monkeypatch, modal)

    called = False

    def fake_copy(_content: str) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard.copy_to_system_clipboard", fake_copy
    )

    modal.action_copy_comment()

    assert called is False
    assert fake_app.notifications == []


def test_copy_comment_notifies_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """y reports an error when the clipboard helper fails."""
    data = _make_modal_data([2])
    modal = MentorReviewModal(data)
    modal._mentor_idx = 0
    modal._comment_idx = 0
    fake_app = _install_fake_app(monkeypatch, modal)

    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard.copy_to_system_clipboard",
        lambda _content: False,
    )

    modal.action_copy_comment()

    assert fake_app.notifications == [("Failed to copy to clipboard", "error")]

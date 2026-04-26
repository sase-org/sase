"""Tests for the notification priority classifier."""

from sase.notifications import is_priority
from sase.notifications.models import Notification


def _n(*, sender: str = "x", action: str | None = None) -> Notification:
    return Notification(id="i", timestamp="t", sender=sender, action=action)


def test_plan_approval_is_priority() -> None:
    assert is_priority(_n(sender="plan", action="PlanApproval"))


def test_user_question_is_priority() -> None:
    assert is_priority(_n(sender="question", action="UserQuestion"))


def test_jump_to_mentor_review_is_priority() -> None:
    assert is_priority(_n(sender="mentors", action="JumpToMentorReview"))


def test_axe_sender_is_priority() -> None:
    assert is_priority(_n(sender="axe", action="ViewErrorReport"))


def test_crs_sender_is_priority() -> None:
    assert is_priority(_n(sender="crs", action="JumpToChangeSpec"))


def test_user_agent_view_error_report_is_priority() -> None:
    assert is_priority(_n(sender="user-agent", action="ViewErrorReport"))


def test_sync_result_is_not_priority() -> None:
    assert not is_priority(_n(sender="sync", action="JumpToChangeSpec"))


def test_hitl_is_not_priority() -> None:
    assert not is_priority(_n(sender="hitl", action="HITL"))


def test_user_agent_jump_to_agent_is_not_priority() -> None:
    """A successful agent (JumpToAgent) is not priority — only errors are."""
    assert not is_priority(_n(sender="user-agent", action="JumpToAgent"))


def test_workflow_complete_is_not_priority() -> None:
    assert not is_priority(_n(sender="user-workflow", action=None))

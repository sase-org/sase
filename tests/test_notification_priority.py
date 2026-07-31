"""Tests for the notification priority/error classifiers."""

from sase.notifications import is_error, is_priority
from sase.notifications.models import Notification


def _n(*, sender: str = "x", action: str | None = None) -> Notification:
    return Notification(id="i", timestamp="t", sender=sender, action=action)


def test_plan_approval_is_priority() -> None:
    assert is_priority(_n(sender="plan", action="PlanApproval"))


def test_user_question_is_priority() -> None:
    assert is_priority(_n(sender="question", action="UserQuestion"))


def test_task_triage_is_priority() -> None:
    assert is_priority(_n(sender="bead-task-triage", action="TaskTriage"))


def test_jump_to_mentor_review_is_priority() -> None:
    assert is_priority(_n(sender="mentors", action="JumpToMentorReview"))


def test_axe_view_error_report_is_error_not_priority() -> None:
    n = _n(sender="axe", action="ViewErrorReport")
    assert is_error(n)
    assert not is_priority(n)


def test_axe_non_error_action_stays_priority() -> None:
    n = _n(sender="axe", action="JumpToChangeSpec")
    assert is_priority(n)
    assert not is_error(n)


def test_crs_sender_is_priority() -> None:
    assert is_priority(_n(sender="crs", action="JumpToChangeSpec"))


def test_user_agent_view_error_report_is_error_not_priority() -> None:
    n = _n(sender="user-agent", action="ViewErrorReport")
    assert is_error(n)
    assert not is_priority(n)


def test_file_hook_view_error_report_is_error_not_priority() -> None:
    n = _n(sender="file-hooks", action="ViewErrorReport")
    assert is_error(n)
    assert not is_priority(n)


def test_sync_result_is_not_priority() -> None:
    assert not is_priority(_n(sender="sync", action="JumpToChangeSpec"))


def test_hitl_is_not_priority() -> None:
    assert not is_priority(_n(sender="hitl", action="HITL"))


def test_user_agent_jump_to_agent_is_not_priority() -> None:
    """A successful agent (JumpToAgent) is neither priority nor error."""
    n = _n(sender="user-agent", action="JumpToAgent")
    assert not is_priority(n)
    assert not is_error(n)


def test_workflow_complete_is_not_priority() -> None:
    assert not is_priority(_n(sender="user-workflow", action=None))


def test_view_error_report_with_other_sender_is_not_error() -> None:
    """Only registered error senders' reports count as errors."""
    n = _n(sender="planner", action="ViewErrorReport")
    assert not is_error(n)

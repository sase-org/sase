"""GroupingMode: status bucketing."""

from __future__ import annotations

from sase.ace.tui.models.agent_groups import _status_bucket_for

from ._agent_groups_helpers import _agent


def test_status_bucket_done() -> None:
    assert _status_bucket_for(_agent(status="DONE")) == "Done"


def test_status_bucket_running() -> None:
    assert _status_bucket_for(_agent(status="RUNNING")) == "Running"


def test_status_bucket_planning_is_needs_attention() -> None:
    """``PLANNING`` is an active drafting state where the user is on call."""
    assert _status_bucket_for(_agent(status="PLANNING")) == "Needs Attention"


def test_status_bucket_question_is_needs_attention() -> None:
    assert _status_bucket_for(_agent(status="QUESTION")) == "Needs Attention"


def test_status_bucket_plan_approved_is_running() -> None:
    """An approved plan is actively executing → Running."""
    assert _status_bucket_for(_agent(status="PLAN APPROVED")) == "Running"


def test_status_bucket_plan_done_is_done() -> None:
    """``PLAN DONE`` is a post-plan handoff state — planning work is finished."""
    assert _status_bucket_for(_agent(status="PLAN DONE")) == "Done"


def test_status_bucket_plan_rejected_is_done() -> None:
    """``PLAN REJECTED`` is a terminal plan decision, not active planning."""
    assert _status_bucket_for(_agent(status="PLAN REJECTED")) == "Done"


def test_status_bucket_epic_created_is_done() -> None:
    """``EPIC CREATED`` is a post-plan handoff state — code work has been spun off."""
    assert _status_bucket_for(_agent(status="EPIC CREATED")) == "Done"


def test_status_bucket_waiting_without_wait_until_or_waiting_for_is_waiting() -> None:
    """All ``WAITING`` variants collapse into the ``Waiting`` bucket."""
    a = _agent(status="WAITING", wait_until=None)
    assert _status_bucket_for(a) == "Waiting"


def test_status_bucket_waiting_with_wait_until_is_waiting() -> None:
    """Timer-driven WAIT is blocked but progressing → Waiting, not Running."""
    a = _agent(status="WAITING", wait_until="2026-04-26T15:00:00")
    assert _status_bucket_for(a) == "Waiting"


def test_status_bucket_waiting_with_waiting_for_is_waiting() -> None:
    """Dependency-driven WAIT is blocked but not actionable → Waiting."""
    a = _agent(status="WAITING", wait_until=None, waiting_for=["other-agent"])
    assert _status_bucket_for(a) == "Waiting"


def test_status_bucket_failed_terminal_is_failed() -> None:
    """Every displayed ``FAILED`` status lands in the Failed bucket."""
    a = _agent(status="FAILED", retried_as_timestamp=None)
    assert _status_bucket_for(a) == "Failed"


def test_status_bucket_failed_then_retried_is_failed() -> None:
    """FAILED with a forward retry pointer is handed-off, not actionable."""
    a = _agent(status="FAILED", retried_as_timestamp="ts-child")
    assert _status_bucket_for(a) == "Failed"


def test_status_bucket_failed_retried_status_string_is_failed() -> None:
    """``FAILED (RETRIED)`` is the display status of a handed-off failure."""
    a = _agent(status="FAILED (RETRIED)", retried_as_timestamp=None)
    assert _status_bucket_for(a) == "Failed"


def test_status_bucket_unknown_status_falls_through_to_running() -> None:
    """Unrecognized states default to Running rather than disappearing."""
    a = _agent(status="WHATEVER")
    assert _status_bucket_for(a) == "Running"


def test_status_bucket_empty_status_is_running() -> None:
    a = _agent(status="")
    assert _status_bucket_for(a) == "Running"

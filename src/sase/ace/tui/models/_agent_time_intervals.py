"""Row-shape predicates and one row's own runtime interval (no descendants)."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sase.agent.status_buckets import (
    ACTIVE_PLAN_HANDOFF_STATUSES,
    APPROVED_PLAN_STATUSES,
    FEEDBACK_STATUS,
    is_pending_plan_review_status,
)
from sase.core.time import local_now
from sase.plan_chain import (
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
)

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent

_PLAN_RUNTIME_TERMINAL_STATUSES = {"DONE", "PLAN DONE", "TALE DONE"}
_ACTIVE_LEAF_STATUSES = {"RUNNING", "RETRYING", "ANSWERED"}
_SEGMENTED_FOLLOWUP_RUNTIME_STATUSES = ACTIVE_PLAN_HANDOFF_STATUSES
_WORKFLOW_PLAN_STEP_NAMES = {"plan"}
_PLANNER_PHASE_ENDED_STATUSES = {
    "PLAN DONE",
    "TALE DONE",
    "DONE",
    FEEDBACK_STATUS,
    "FAILED",
    "FAILED (RETRIED)",
    "PLAN REJECTED",
}


@dataclass(frozen=True)
class RuntimeInterval:
    """Runtime interval data before display formatting."""

    elapsed_seconds: float
    terminal_time: datetime | None
    active: bool


def should_display_runtime_suffix(agent: "Agent") -> bool:
    """Return True when an Agents-tab row should show a runtime suffix."""
    if agent.parent_workflow is None:
        return True
    return agent.step_type == "agent"


def format_finish_timestamp(
    stop: datetime, now: datetime | None = None
) -> tuple[str, str]:
    """Format a finish-time clock for the Agents-tab right-side suffix.

    Returns a ``(date_prefix, time)`` pair so the renderer can style the
    two halves differently:

    - Same calendar day: ``("", "HH:MM:SS")``.
    - Prior day, same year: ``("Mon DD ", "HH:MM")`` (trailing space owns
      the gap between the two halves).
    - Different year: ``("Mon DD 'YY", "")``.
    """
    reference = now if now is not None else local_now()
    if stop.date() == reference.date():
        return ("", stop.strftime("%H:%M:%S"))
    if stop.year == reference.year:
        return (stop.strftime("%b %-d "), stop.strftime("%H:%M"))
    return (stop.strftime("%b %-d '%y"), "")


def row_runtime_terminal_time(agent: "Agent") -> datetime | None:
    """Return the terminal timestamp to anchor a completed row runtime."""
    if agent.status == FEEDBACK_STATUS:
        return _feedback_terminal_plan_time(agent)
    if _is_planner_phase_row(agent) and agent.plan_times:
        return max(agent.plan_times)
    if agent.status in APPROVED_PLAN_STATUSES and agent.plan_times:
        return max(agent.plan_times)
    if agent.stop_time is not None:
        return agent.stop_time
    if agent.status in _PLAN_RUNTIME_TERMINAL_STATUSES and agent.plan_times:
        return max(agent.plan_times)
    if is_pending_plan_review_status(agent.status) and agent.plan_times:
        return max(agent.plan_times)
    if agent.status == "QUESTION" and agent.questions_times:
        return max(agent.questions_times)
    return None


def _feedback_terminal_plan_time(agent: "Agent") -> datetime | None:
    """Return the plan submission that was resolved by latest feedback."""
    if agent.feedback_times and agent.plan_times:
        latest_feedback = max(agent.feedback_times)
        submitted_before_feedback = [
            plan_time for plan_time in agent.plan_times if plan_time <= latest_feedback
        ]
        if submitted_before_feedback:
            return max(submitted_before_feedback)
    if agent.plan_times:
        return max(agent.plan_times)
    return agent.stop_time


def _is_planner_phase_row(agent: "Agent") -> bool:
    """Return whether a row's own runtime should end at plan submission."""
    if agent.status in {"PLAN DONE", "TALE DONE"}:
        return True
    if agent.parent_workflow is None or agent.step_type != "agent":
        return False
    if agent.stop_time is None and agent.status not in _PLANNER_PHASE_ENDED_STATUSES:
        return False
    if canonical_plan_chain_suffix(agent.role_suffix) == PLAN_CHAIN_PLAN_SUFFIX:
        return True
    return agent.step_name in _WORKFLOW_PLAN_STEP_NAMES


def is_code_phase_row(agent: "Agent") -> bool:
    return (
        agent_family_role_for_suffix(
            agent.role_suffix,
            agent_family_role=agent.agent_family_role,
        )
        == "code"
    )


def segmented_followup_plan_time(agent: "Agent") -> datetime | None:
    """Return the plan timestamp that anchors a follow-up runtime segment."""
    if not agent.plan_times:
        return None
    if agent.code_time is None:
        return None
    submitted_before_code = [
        plan_time for plan_time in agent.plan_times if plan_time <= agent.code_time
    ]
    if submitted_before_code:
        return max(submitted_before_code)
    return max(agent.plan_times)


def _segmented_followup_runtime_interval(
    agent: "Agent", effective_start: datetime, now: datetime
) -> RuntimeInterval | None:
    """Return active runtime for a plan row with a running follow-up.

    The approval gap between plan submission and code launch is not active
    runtime, so the row displays ``RUN -> PLAN`` plus ``CODE -> now``.
    """
    if agent.status not in _SEGMENTED_FOLLOWUP_RUNTIME_STATUSES:
        return None
    if agent.code_time is None:
        return None
    plan_time = segmented_followup_plan_time(agent)
    if plan_time is None:
        return None
    elapsed_seconds = max(0.0, (plan_time - effective_start).total_seconds())
    elapsed_seconds += max(0.0, (now - agent.code_time).total_seconds())
    return RuntimeInterval(
        elapsed_seconds=elapsed_seconds,
        terminal_time=None,
        active=True,
    )


def is_active_approved_followup_coder(agent: "Agent") -> bool:
    """Return True for a linked code follow-up hidden behind approval status."""
    return (
        agent.status in _SEGMENTED_FOLLOWUP_RUNTIME_STATUSES
        and bool(agent.parent_timestamp)
        and agent.parent_workflow is None
        and agent.run_start_time is not None
        and agent.stop_time is None
        and is_code_phase_row(agent)
    )


def leaf_runtime_interval(agent: "Agent", now: datetime) -> RuntimeInterval | None:
    """Return the row's own runtime interval, excluding aggregate children."""
    if agent.start_time is None:
        return None

    terminal_time = row_runtime_terminal_time(agent)
    effective_start = agent.run_start_time
    if effective_start is None:
        if terminal_time is None:
            return None
        effective_start = agent.start_time

    if agent.is_monitor and agent.monitor_state == "running":
        return RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    if terminal_time is not None:
        return RuntimeInterval(
            elapsed_seconds=(terminal_time - effective_start).total_seconds(),
            terminal_time=terminal_time,
            active=False,
        )

    segmented_interval = _segmented_followup_runtime_interval(
        agent, effective_start, now
    )
    if segmented_interval is not None:
        return segmented_interval

    if is_active_approved_followup_coder(agent):
        return RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    if (
        agent.status in _SEGMENTED_FOLLOWUP_RUNTIME_STATUSES
        and agent.stop_time is None
        and agent.run_start_time is not None
        and (
            (agent.parent_workflow is not None and agent.step_type == "agent")
            or is_code_phase_row(agent)
        )
    ):
        return RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    if agent.status == "WAITING":
        if agent.run_start_time is None:
            return None
        return RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    if agent.status in _ACTIVE_LEAF_STATUSES:
        return RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    return None

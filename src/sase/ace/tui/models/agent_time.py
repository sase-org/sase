"""Time/duration formatting helpers for the Agent model."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sase.core.time import get_timezone, local_now, parse_local, to_local
from sase.core.agent_runtime_facade import aggregate_clan_runtime
from sase.core.agent_runtime_wire import ClanRuntimeMemberWire
from sase.agent.status_buckets import (
    ACTIVE_PLAN_HANDOFF_STATUSES,
    APPROVED_PLAN_STATUSES,
    FEEDBACK_STATUS,
    is_pending_plan_review_status,
)
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
class _RuntimeInterval:
    """Runtime interval data before display formatting."""

    elapsed_seconds: float
    terminal_time: datetime | None
    active: bool


def should_display_runtime_suffix(agent: "Agent") -> bool:
    """Return True when an Agents-tab row should show a runtime suffix."""
    if agent.parent_workflow is None:
        return True
    return agent.step_type == "agent"


def wait_until_target_and_reference(
    iso_str: str, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Return a wait target and timezone-compatible reference time."""
    target = datetime.fromisoformat(iso_str)
    if now is not None:
        reference = now
        if target.tzinfo is not None and reference.tzinfo is None:
            reference = reference.astimezone(get_timezone())
        elif target.tzinfo is None and reference.tzinfo is not None:
            target = target.replace(tzinfo=reference.tzinfo)
        return target, reference

    if target.tzinfo is not None:
        return target, datetime.now(target.tzinfo)
    return target, local_now()


def format_wait_until(iso_str: str, now: datetime | None = None) -> str:
    """Format an ISO 8601 target time for display.

    Same day: ``"14:30"`` (just the time).
    Different day: ``"Apr 11 14:30"`` (short month + day + time).
    """
    target, now = wait_until_target_and_reference(iso_str, now=now)
    if target.date() == now.date():
        return target.strftime("%H:%M")
    return target.strftime("%b %-d %H:%M")


def format_compact_duration(seconds: float) -> str:
    """Format seconds as a compact duration string (e.g., '4m32s', '1h5m').

    Shows the two most significant non-zero units:
    - >= 1h: 'Xh Ym'
    - >= 1m: 'Xm Ys'
    - < 1m: 'Xs'
    """
    total = max(0, int(seconds))
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}h{m:02d}m" if m else f"{h}h"
    if m > 0:
        return f"{m}m{s:02d}s" if s else f"{m}m"
    return f"{s}s"


def queued_for_label(
    requested_at: str | None,
    now: datetime | None = None,
) -> str | None:
    """Return a compact elapsed label for a runner-slot request timestamp.

    ``requested_at`` is a stored ``slot_requested_at`` marker value. Both sides
    are normalized to the naive configured-tz arithmetic convention before
    subtracting, matching the rest of the TUI agent time model.
    """
    if not requested_at:
        return None
    parsed = parse_local(requested_at)
    if parsed is None:
        return None
    reference = local_now() if now is None else now
    elapsed = max(0.0, (to_local(reference) - to_local(parsed)).total_seconds())
    return format_compact_duration(elapsed)


def wait_display_agent(agent: "Agent") -> "Agent":
    """Return the row whose wait fields should drive display for *agent*."""
    return agent.wait_display_source or agent


def _reference_for_target(target: datetime, now: datetime | None) -> datetime:
    """Return a timezone-compatible reference time for *target*."""
    if now is not None:
        reference = now
    elif target.tzinfo is not None:
        reference = datetime.now(target.tzinfo)
    else:
        reference = local_now()

    if target.tzinfo is not None and reference.tzinfo is None:
        return reference.astimezone(get_timezone())
    if target.tzinfo is None and reference.tzinfo is not None:
        return reference.replace(tzinfo=None)
    return reference


def wait_remaining_seconds(agent: "Agent", now: datetime | None = None) -> float | None:
    """Return seconds left on an agent's wait time floor, if one is known."""
    wait_agent = wait_display_agent(agent)
    if wait_agent.wait_until:
        target, reference = wait_until_target_and_reference(
            wait_agent.wait_until,
            now=now,
        )
        return (target - reference).total_seconds()
    if wait_agent.wait_duration is None or wait_agent.start_time is None:
        return None
    if wait_agent.waiting_for or wait_agent.waiting_for_beads:
        return None
    target = wait_agent.start_time + timedelta(seconds=wait_agent.wait_duration)
    reference = _reference_for_target(target, now)
    return (target - reference).total_seconds()


def _format_finish_timestamp(
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


def _row_runtime_terminal_time(agent: "Agent") -> datetime | None:
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


def _is_code_phase_row(agent: "Agent") -> bool:
    return (
        agent_family_role_for_suffix(
            agent.role_suffix,
            agent_family_role=agent.agent_family_role,
        )
        == "code"
    )


def _segmented_followup_plan_time(agent: "Agent") -> datetime | None:
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
) -> _RuntimeInterval | None:
    """Return active runtime for a plan row with a running follow-up.

    The approval gap between plan submission and code launch is not active
    runtime, so the row displays ``RUN -> PLAN`` plus ``CODE -> now``.
    """
    if agent.status not in _SEGMENTED_FOLLOWUP_RUNTIME_STATUSES:
        return None
    if agent.code_time is None:
        return None
    plan_time = _segmented_followup_plan_time(agent)
    if plan_time is None:
        return None
    elapsed_seconds = max(0.0, (plan_time - effective_start).total_seconds())
    elapsed_seconds += max(0.0, (now - agent.code_time).total_seconds())
    return _RuntimeInterval(
        elapsed_seconds=elapsed_seconds,
        terminal_time=None,
        active=True,
    )


def _is_active_approved_followup_coder(agent: "Agent") -> bool:
    """Return True for a linked code follow-up hidden behind approval status."""
    return (
        agent.status in _SEGMENTED_FOLLOWUP_RUNTIME_STATUSES
        and bool(agent.parent_timestamp)
        and agent.parent_workflow is None
        and agent.run_start_time is not None
        and agent.stop_time is None
        and _is_code_phase_row(agent)
    )


def _leaf_runtime_interval(agent: "Agent", now: datetime) -> _RuntimeInterval | None:
    """Return the row's own runtime interval, excluding aggregate children."""
    if agent.start_time is None:
        return None

    terminal_time = _row_runtime_terminal_time(agent)
    effective_start = agent.run_start_time
    if effective_start is None:
        if terminal_time is None:
            return None
        effective_start = agent.start_time

    if agent.is_monitor and agent.monitor_state == "running":
        return _RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    if terminal_time is not None:
        return _RuntimeInterval(
            elapsed_seconds=(terminal_time - effective_start).total_seconds(),
            terminal_time=terminal_time,
            active=False,
        )

    segmented_interval = _segmented_followup_runtime_interval(
        agent, effective_start, now
    )
    if segmented_interval is not None:
        return segmented_interval

    if _is_active_approved_followup_coder(agent):
        return _RuntimeInterval(
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
            or _is_code_phase_row(agent)
        )
    ):
        return _RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    if agent.status == "WAITING":
        if agent.run_start_time is None:
            return None
        return _RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    if agent.status in _ACTIVE_LEAF_STATUSES:
        return _RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    return None


def _aggregates_family_shells(agent: "Agent") -> bool:
    """Return whether *agent*'s aggregate owns durable family-shell runtime.

    This is container-ness, not ``stop_time``. A settled family container
    still records ``stopped_at`` on the root artifacts dir, but it must keep
    spanning a running shell grandchild. Concrete agent shells only own their
    own interval; the shell already has its own roster row.
    """
    return agent.is_clan_container or agent.is_family_container_row


def _represented_by_descendants(agent: "Agent", eligible: tuple["Agent", ...]) -> bool:
    """Return whether *agent*'s runtime is carried by descendant rows."""
    if not (
        _aggregates_family_shells(agent)
        or any(
            child.is_workflow_step_child
            for child in getattr(agent, "runtime_children", ())
        )
    ):
        return False
    return not eligible or any(not row.is_monitor for row in eligible)


def _runtime_child_rows(
    agent: "Agent",
    *,
    include_monitor_shells: bool,
    _seen: set[int] | None = None,
) -> tuple["Agent", ...]:
    """Return the child rows whose runtime an ancestor row may absorb.

    A gate shell owns a human decision window rather than agent runtime, so
    it never contributes its own interval to an ancestor at any level. Its
    own children are yielded in its place, so an agent a gate started is not
    dropped along with the gate. Monitor shells still contribute, but only to
    family and clan container rows.
    """
    if _seen is None:
        _seen = {id(agent)}
    rows: list[Agent] = []
    for child in getattr(agent, "runtime_children", ()):
        child_id = id(child)
        if child_id in _seen:
            continue
        _seen.add(child_id)
        if child.is_gate:
            rows.extend(
                _runtime_child_rows(
                    child,
                    include_monitor_shells=include_monitor_shells,
                    _seen=_seen,
                )
            )
            continue
        if child.is_monitor and not include_monitor_shells:
            continue
        rows.append(child)
    return tuple(rows)


def _aggregate_runtime(
    agent: "Agent", now: datetime, seen: set[int]
) -> _RuntimeInterval | None:
    """Return the aggregate interval from direct runtime children."""
    children = getattr(agent, "runtime_children", ())
    if not children:
        return None

    include_monitor_shells = _aggregates_family_shells(agent)
    runtime_members: list[ClanRuntimeMemberWire] = []
    terminal_times: list[datetime] = []
    saw_non_monitor_member = False

    def timestamp(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()

    def append_member_wire(child: "Agent") -> None:
        nonlocal saw_non_monitor_member
        if not child.is_monitor:
            saw_non_monitor_member = True
        terminal = _row_runtime_terminal_time(child)
        if terminal is not None:
            terminal_times.append(terminal)
        pending_question = (
            max(child.questions_times)
            if child.questions_times
            and child.question_response_path is None
            and (
                child.runner_slot_yielded
                or child.status in {"QUESTION", "WAITING INPUT"}
            )
            else None
        )
        runtime_members.append(
            ClanRuntimeMemberWire(
                run_started_at=timestamp(
                    child.run_start_time or (child.start_time if terminal else None)
                ),
                stopped_at=timestamp(terminal),
                plan_submitted_at=[
                    timestamp(value) or "" for value in child.plan_times
                ],
                feedback_submitted_at=[
                    timestamp(value) or "" for value in child.feedback_times
                ],
                plan_approved=child.status in APPROVED_PLAN_STATUSES,
                questions_submitted_at=[
                    timestamp(value) or "" for value in child.questions_times
                ],
                question_response_path=child.question_response_path,
                pending_question_submitted_at=timestamp(pending_question),
            )
        )

    def append_runtime_member(child: "Agent") -> None:
        child_id = id(child)
        if child_id in seen:
            return
        seen.add(child_id)
        eligible = _runtime_child_rows(
            child, include_monitor_shells=include_monitor_shells
        )
        for grandchild in eligible:
            append_runtime_member(grandchild)
        if getattr(child, "runtime_children", ()) and _represented_by_descendants(
            child, eligible
        ):
            return
        append_member_wire(child)

    for child in _runtime_child_rows(
        agent, include_monitor_shells=include_monitor_shells
    ):
        append_runtime_member(child)

    if runtime_members and not saw_non_monitor_member and not agent.is_clan_container:
        append_member_wire(agent)

    if not runtime_members:
        return None
    runtime = aggregate_clan_runtime(runtime_members, now=now)
    return _RuntimeInterval(
        elapsed_seconds=runtime.wall_clock_seconds,
        terminal_time=None if runtime.active else max(terminal_times, default=None),
        active=runtime.active,
    )


def _runtime_interval(
    agent: "Agent", now: datetime, seen: set[int] | None = None
) -> _RuntimeInterval | None:
    """Return aggregate runtime when available, otherwise leaf runtime."""
    if not should_display_runtime_suffix(agent):
        return None
    if seen is None:
        seen = set()
    agent_id = id(agent)
    if agent_id in seen:
        return None
    seen.add(agent_id)

    aggregate = _aggregate_runtime(agent, now, seen)
    if aggregate is not None:
        return aggregate
    return _leaf_runtime_interval(agent, now)


def compute_row_runtime(
    agent: "Agent",
    now: datetime | None = None,
) -> tuple[tuple[str, str] | None, str | None]:
    """Compute the right-side ``(timestamp, elapsed)`` suffix pair for a row.

    - ``(None, None)`` when no suffix should render (missing ``start_time``
      or pre-run ``WAITING`` with no ``run_start_time``).
    - Active rows: ``(None, "<dur>")``.
    - Finished rows: ``((date_prefix, time), "<dur>")`` where the
      ``(date_prefix, time)`` pair follows the tiers in
      :func:`_format_finish_timestamp`.

    Elapsed uses ``run_start_time`` so a long STARTING/WAITING period doesn't
    inflate what reads as runtime. Historical terminal rows without
    ``run_start_time`` fall back to ``start_time`` for compatibility.
    """
    reference = now if now is not None else local_now()
    interval = _runtime_interval(agent, reference)
    if interval is None:
        return (None, None)
    if interval.terminal_time is not None:
        return (
            _format_finish_timestamp(interval.terminal_time, now=now),
            format_compact_duration(interval.elapsed_seconds),
        )
    return (None, format_compact_duration(interval.elapsed_seconds))


def compute_leaf_row_runtime(
    agent: "Agent",
    now: datetime | None = None,
) -> tuple[tuple[str, str] | None, str | None]:
    """Compute one row's own runtime suffix pair, excluding descendants."""
    if not should_display_runtime_suffix(agent):
        return (None, None)
    reference = now if now is not None else local_now()
    interval = _leaf_runtime_interval(agent, reference)
    if interval is None:
        return (None, None)
    if interval.terminal_time is not None:
        return (
            _format_finish_timestamp(interval.terminal_time, now=reference),
            format_compact_duration(interval.elapsed_seconds),
        )
    return (None, format_compact_duration(interval.elapsed_seconds))


def compute_lowest_row_runtime(
    rows: Sequence["Agent"],
    now: datetime | None = None,
) -> str | None:
    """Return the smallest still-active total duration among *rows*.

    Each row contributes the same total its own row displays -- the aggregate
    across its descendants -- so a family row contributes the family total,
    not the runtime of the shell currently executing inside it. A row whose
    aggregate is not live falls back to its own interval, so a live row is
    never dropped just because its descendants have not started.
    """
    reference = now if now is not None else local_now()
    lowest: float | None = None
    for row in rows:
        if not should_display_runtime_suffix(row):
            continue
        interval = _runtime_interval(row, reference)
        if interval is None or not interval.active:
            interval = _leaf_runtime_interval(row, reference)
        if (
            interval is None
            or not interval.active
            or interval.terminal_time is not None
        ):
            continue
        if lowest is None or interval.elapsed_seconds < lowest:
            lowest = interval.elapsed_seconds
    if lowest is None:
        return None
    return format_compact_duration(lowest)


def runtime_suffix_ticks(
    agent: "Agent",
    _seen: set[int] | None = None,
    *,
    _include_monitor_shells: bool | None = None,
) -> bool:
    """Return True when *agent* renders a runtime suffix that can tick."""
    if _seen is None:
        _seen = set()
    agent_id = id(agent)
    if agent_id in _seen:
        return False
    _seen.add(agent_id)

    include_monitor_shells = (
        _aggregates_family_shells(agent)
        if _include_monitor_shells is None
        else _include_monitor_shells
    )

    if not should_display_runtime_suffix(agent):
        return False
    for child in _runtime_child_rows(
        agent, include_monitor_shells=include_monitor_shells
    ):
        if runtime_suffix_ticks(
            child, _seen, _include_monitor_shells=include_monitor_shells
        ):
            return True
    if agent.stop_time is not None:
        return False
    if agent.is_monitor and agent.monitor_state == "running":
        return agent.run_start_time is not None
    if agent.is_gate and agent.gate_state == "settling":
        return agent.run_start_time is not None
    if agent.status in APPROVED_PLAN_STATUSES and agent.plan_times:
        return False
    if (
        agent.run_start_time is not None
        and _segmented_followup_plan_time(agent) is not None
    ):
        return agent.status in _SEGMENTED_FOLLOWUP_RUNTIME_STATUSES
    if _is_active_approved_followup_coder(agent):
        return True
    if (
        agent.status in _SEGMENTED_FOLLOWUP_RUNTIME_STATUSES
        and agent.run_start_time is not None
        and (
            (agent.parent_workflow is not None and agent.step_type == "agent")
            or _is_code_phase_row(agent)
        )
    ):
        return True
    if agent.status in _ACTIVE_LEAF_STATUSES:
        return agent.run_start_time is not None
    return agent.status == "WAITING" and agent.run_start_time is not None


def wait_countdown_ticks(agent: "Agent") -> bool:
    """Return True when a ``WAITING`` row has a time floor countdown."""
    if agent.status != "WAITING":
        return False
    wait_agent = wait_display_agent(agent)
    if wait_agent.wait_until:
        return True
    return (
        wait_agent.wait_duration is not None
        and wait_agent.start_time is not None
        and not wait_agent.waiting_for
        and not wait_agent.waiting_for_beads
    )


def row_runtime_or_wait_ticks(
    agent: "Agent",
    _seen: set[int] | None = None,
    *,
    _include_monitor_shells: bool | None = None,
) -> bool:
    """Return True when any visible time text for *agent* can tick."""
    if _seen is None:
        _seen = set()
    agent_id = id(agent)
    if agent_id in _seen:
        return False
    _seen.add(agent_id)

    include_monitor_shells = (
        _aggregates_family_shells(agent)
        if _include_monitor_shells is None
        else _include_monitor_shells
    )

    if runtime_suffix_ticks(agent, _include_monitor_shells=include_monitor_shells):
        return True
    if wait_countdown_ticks(agent):
        return True
    for child in _runtime_child_rows(
        agent, include_monitor_shells=include_monitor_shells
    ):
        if row_runtime_or_wait_ticks(
            child, _seen, _include_monitor_shells=include_monitor_shells
        ):
            return True
    return False

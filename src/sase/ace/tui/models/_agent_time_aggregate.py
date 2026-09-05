"""Aggregate runtime across a row's family/clan descendant rows."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sase.agent.status_buckets import APPROVED_PLAN_STATUSES
from sase.core.agent_runtime_facade import aggregate_clan_runtime
from sase.core.agent_runtime_wire import ClanRuntimeMemberWire

from ._agent_time_intervals import (
    RuntimeInterval,
    leaf_runtime_interval,
    row_runtime_terminal_time,
    should_display_runtime_suffix,
)

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent


def aggregates_family_shells(agent: "Agent") -> bool:
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
        aggregates_family_shells(agent)
        or any(
            child.is_workflow_step_child
            for child in getattr(agent, "runtime_children", ())
        )
    ):
        return False
    return not eligible or any(not row.is_monitor for row in eligible)


def runtime_child_rows(
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
                runtime_child_rows(
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
) -> RuntimeInterval | None:
    """Return the aggregate interval from direct runtime children."""
    children = getattr(agent, "runtime_children", ())
    if not children:
        return None

    include_monitor_shells = aggregates_family_shells(agent)
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
        terminal = row_runtime_terminal_time(child)
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
        eligible = runtime_child_rows(
            child, include_monitor_shells=include_monitor_shells
        )
        for grandchild in eligible:
            append_runtime_member(grandchild)
        if getattr(child, "runtime_children", ()) and _represented_by_descendants(
            child, eligible
        ):
            return
        append_member_wire(child)

    for child in runtime_child_rows(
        agent, include_monitor_shells=include_monitor_shells
    ):
        append_runtime_member(child)

    if runtime_members and not saw_non_monitor_member and not agent.is_clan_container:
        append_member_wire(agent)

    if not runtime_members:
        return None
    runtime = aggregate_clan_runtime(runtime_members, now=now)
    return RuntimeInterval(
        elapsed_seconds=runtime.wall_clock_seconds,
        terminal_time=None if runtime.active else max(terminal_times, default=None),
        active=runtime.active,
    )


def runtime_interval(
    agent: "Agent", now: datetime, seen: set[int] | None = None
) -> RuntimeInterval | None:
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
    return leaf_runtime_interval(agent, now)

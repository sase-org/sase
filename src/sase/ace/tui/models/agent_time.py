"""Time/duration formatting helpers for the Agent model.

This module is the stable import facade. Wait/duration formatting, row-shape
predicates and leaf-interval computation, and family/clan aggregation live in
focused sibling modules; the top-level per-row computations agent.py and the
Agents-tab widgets call remain here.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from sase.agent.status_buckets import APPROVED_PLAN_STATUSES
from sase.core.time import local_now

from ._agent_time_aggregate import (
    aggregates_family_shells as _aggregates_family_shells,
    runtime_child_rows as _runtime_child_rows,
    runtime_interval as _runtime_interval,
)
from ._agent_time_intervals import (
    _ACTIVE_LEAF_STATUSES,
    _SEGMENTED_FOLLOWUP_RUNTIME_STATUSES,
    format_finish_timestamp as _format_finish_timestamp,
    is_active_approved_followup_coder as _is_active_approved_followup_coder,
    is_code_phase_row as _is_code_phase_row,
    leaf_runtime_interval as _leaf_runtime_interval,
    segmented_followup_plan_time as _segmented_followup_plan_time,
    should_display_runtime_suffix as should_display_runtime_suffix,
)
from ._agent_time_wait import (
    format_compact_duration as format_compact_duration,
    format_wait_until as format_wait_until,
    queued_for_label as queued_for_label,
    wait_countdown_ticks as wait_countdown_ticks,
    wait_display_agent as wait_display_agent,
    wait_remaining_seconds as wait_remaining_seconds,
    wait_until_target_and_reference as wait_until_target_and_reference,
)

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent


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

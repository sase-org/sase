"""Aggregate runtime across a row's agent session/clan descendant rows."""

from collections import OrderedDict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sase.agent.status_buckets import APPROVED_PLAN_STATUSES
from sase.core.agent_runtime_facade import aggregate_clan_runtime
from sase.core.agent_runtime_wire import ClanRuntimeMemberWire

from ._agent_time_intervals import (
    RuntimeInterval,
    leaf_runtime_interval,
    row_runtime_terminal_time,
    should_display_runtime_suffix,
)

_AGGREGATE_WIRES_CACHE_MAX = 256
_aggregate_wires_cache: OrderedDict[tuple[Any, ...], tuple[Any, ...]] = OrderedDict()

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent


def aggregates_agent_session_turns(agent: "Agent") -> bool:
    """Return whether *agent*'s aggregate owns durable session-turn runtime.

    This is container-ness, not ``stop_time``. A settled session container
    still records ``stopped_at`` on the root artifacts dir, but it must keep
    spanning a running turn grandchild. Concrete agent turns only own their
    own interval; the turn already has its own roster row.
    """
    return agent.is_clan_container or agent.is_agent_session_container_row


def _represented_by_descendants(agent: "Agent", eligible: tuple["Agent", ...]) -> bool:
    """Return whether *agent*'s runtime is carried by descendant rows."""
    if not (
        aggregates_agent_session_turns(agent)
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
    include_monitor_turns: bool,
    _seen: set[int] | None = None,
) -> tuple["Agent", ...]:
    """Return the child rows whose runtime an ancestor row may absorb.

    A gate turn owns a human decision window rather than agent runtime, so
    it never contributes its own interval to an ancestor at any level. Its
    own children are yielded in its place, so an agent a gate started is not
    dropped along with the gate. Monitor turns still contribute, but only to
    agent session and clan container rows.
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
                    include_monitor_turns=include_monitor_turns,
                    _seen=_seen,
                )
            )
            continue
        if child.is_monitor and not include_monitor_turns:
            continue
        rows.append(child)
    return tuple(rows)


def _member_fingerprint(child: "Agent") -> tuple[Any, ...]:
    """Return the wire-relevant inputs of one aggregate member row.

    Raw values only (no isoformat): the cached wires are rebuilt exactly
    when this tuple changes. Covers every field ``_build_member_wires``
    reads, including the status-dependent terminal/pending-question inputs.
    """
    try:
        plan_times = tuple(child.plan_times)
    except Exception:  # noqa: BLE001 - defensive fingerprint only.
        plan_times = ()
    try:
        feedback_times = tuple(child.feedback_times)
    except Exception:  # noqa: BLE001 - defensive fingerprint only.
        feedback_times = ()
    try:
        questions_times = tuple(child.questions_times)
    except Exception:  # noqa: BLE001 - defensive fingerprint only.
        questions_times = ()
    try:
        identity = child.identity
    except Exception:  # noqa: BLE001 - defensive fingerprint only.
        identity = None
    return (
        identity,
        getattr(child, "run_start_time", None),
        getattr(child, "start_time", None),
        getattr(child, "stop_time", None),
        plan_times,
        feedback_times,
        getattr(child, "status", None),
        questions_times,
        getattr(child, "question_response_path", None),
        bool(getattr(child, "question_answered", False)),
        bool(getattr(child, "runner_slot_yielded", False)),
        bool(getattr(child, "is_monitor", False)),
    )


def _collect_aggregate_member_rows(
    agent: "Agent",
    include_monitor_turns: bool,
    seen: set[int],
) -> list["Agent"]:
    """Collect member rows in the same order ``_aggregate_runtime`` wires them."""
    members: list[Agent] = []

    def collect(child: "Agent") -> None:
        child_id = id(child)
        if child_id in seen:
            return
        seen.add(child_id)
        eligible = runtime_child_rows(
            child, include_monitor_turns=include_monitor_turns
        )
        for grandchild in eligible:
            collect(grandchild)
        if getattr(child, "runtime_children", ()) and _represented_by_descendants(
            child, eligible
        ):
            return
        members.append(child)

    for child in runtime_child_rows(agent, include_monitor_turns=include_monitor_turns):
        collect(child)
    if members and not any(not row.is_monitor for row in members):
        if not agent.is_clan_container:
            members.append(agent)
    return members


def _aggregate_cache_key(
    agent: "Agent",
    members: list["Agent"],
) -> tuple[Any, ...]:
    """Return the cache key for one container's now-independent wires.

    Keyed by the container identity plus the member runtime inputs. The
    roster generation is represented implicitly: any roster assignment or
    in-place mutation that changes wire inputs changes the fingerprint (or
    the container identity), so a stale generation can never hit. Unrelated
    roster bumps with identical inputs correctly hit instead of rebuilding.
    """
    identity: Any
    try:
        identity = agent.identity
    except Exception:  # noqa: BLE001 - defensive cache key only.
        identity = id(agent)
    return (
        identity,
        bool(getattr(agent, "is_clan_container", False)),
        bool(getattr(agent, "is_agent_session_container_row", False)),
        tuple(_member_fingerprint(row) for row in members),
    )


def _build_member_wires(
    members: list["Agent"],
) -> tuple[tuple[ClanRuntimeMemberWire, ...], tuple[datetime, ...], bool]:
    """Build now-independent wires, terminal times, and monitor flag."""
    runtime_members: list[ClanRuntimeMemberWire] = []
    terminal_times: list[datetime] = []
    saw_non_monitor_member = False

    def timestamp(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()

    for child in members:
        if not child.is_monitor:
            saw_non_monitor_member = True
        terminal = row_runtime_terminal_time(child)
        if terminal is not None:
            terminal_times.append(terminal)
        pending_question = (
            max(child.questions_times)
            if child.questions_times
            and child.question_response_path is None
            and not child.question_answered
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
    return tuple(runtime_members), tuple(terminal_times), saw_non_monitor_member


def _aggregate_runtime(
    agent: "Agent", now: datetime, seen: set[int]
) -> RuntimeInterval | None:
    """Return the aggregate interval from direct runtime children.

    Caches the now-independent member wires per container identity plus
    member runtime inputs (phase ``runtime-tick-caches``); only the
    ``now``-dependent Rust aggregation runs per tick.
    """
    children = getattr(agent, "runtime_children", ())
    if not children:
        return None

    include_monitor_turns = aggregates_agent_session_turns(agent)
    members = _collect_aggregate_member_rows(agent, include_monitor_turns, seen)
    if not members:
        return None
    key = _aggregate_cache_key(agent, members)
    hit = _aggregate_wires_cache.get(key)
    if hit is not None:
        try:
            _aggregate_wires_cache.move_to_end(key)
        except Exception:  # noqa: BLE001 - LRU touch is best-effort.
            pass
        runtime_members, terminal_times, _saw = hit
    else:
        runtime_members, terminal_times, _saw = _build_member_wires(members)
        _aggregate_wires_cache[key] = (runtime_members, terminal_times, _saw)
        while len(_aggregate_wires_cache) > _AGGREGATE_WIRES_CACHE_MAX:
            try:
                _aggregate_wires_cache.popitem(last=False)
            except KeyError:
                break
    runtime = aggregate_clan_runtime(list(runtime_members), now=now)
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

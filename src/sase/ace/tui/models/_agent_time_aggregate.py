"""Aggregate runtime across a row's agent session/clan descendant rows."""

from collections import OrderedDict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
import weakref

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

#: Bound on per-row display-bucket results. Keyed by the same membership
#: signature as the wires cache; each entry holds
#: ``(quantum, bucket, interval)`` where ``(quantum, bucket)`` is the
#: displayed-time bucket the interval was computed for (phase
#: ``tick-compare-skip``).
_AGGREGATE_RESULT_CACHE_MAX = 512
_aggregate_result_cache: OrderedDict[
    tuple[Any, ...], tuple[int, int, RuntimeInterval]
] = OrderedDict()

# Roster applies and in-place row patches advance this cheap invalidation
# token. A stable tick can then reuse the last displayed interval without
# walking every clan member to rebuild a content fingerprint.
_runtime_input_revision = 0
_AGGREGATE_FAST_CACHE_MAX = 512
_aggregate_fast_cache: OrderedDict[
    tuple[Any, ...],
    tuple[
        weakref.ReferenceType[Any],
        int,
        int,
        int,
        RuntimeInterval,
        tuple[int, ...],
    ],
] = OrderedDict()

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent


def bump_runtime_input_revision() -> int:
    """Invalidate cheap clan-runtime hits after Agent rows change."""
    global _runtime_input_revision
    _runtime_input_revision += 1
    return _runtime_input_revision


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
    visited_ids: list[int] | None = None,
) -> list["Agent"]:
    """Collect member rows in the same order ``_aggregate_runtime`` wires them."""
    members: list[Agent] = []

    def collect(child: "Agent") -> None:
        child_id = id(child)
        if child_id in seen:
            return
        seen.add(child_id)
        if visited_ids is not None:
            visited_ids.append(child_id)
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


def _aggregate_fast_cache_key(agent: "Agent") -> tuple[Any, ...]:
    """Return the cheap identity key checked before walking runtime members."""
    try:
        identity: Any = agent.identity
    except Exception:  # noqa: BLE001 - defensive cache key only.
        identity = id(agent)
    return (
        identity,
        id(agent),
        bool(getattr(agent, "is_clan_container", False)),
        bool(getattr(agent, "is_agent_session_container_row", False)),
    )


def _remember_fast_aggregate(
    key: tuple[Any, ...],
    agent: "Agent",
    revision: int,
    interval: RuntimeInterval,
    now_epoch: float,
    covered_member_ids: tuple[int, ...],
) -> None:
    quantum, bucket = _display_bucket(now_epoch, interval.elapsed_seconds)
    _aggregate_fast_cache[key] = (
        weakref.ref(agent),
        revision,
        quantum,
        bucket,
        interval,
        covered_member_ids,
    )
    _aggregate_fast_cache.move_to_end(key)
    while len(_aggregate_fast_cache) > _AGGREGATE_FAST_CACHE_MAX:
        try:
            _aggregate_fast_cache.popitem(last=False)
        except KeyError:
            break


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


def _display_bucket(now_epoch: float, elapsed_hint: float | None) -> tuple[int, int]:
    """Return the ``(quantum, bucket)`` the displayed duration ticks on.

    Sub-hour durations render second granularity (``"59s"``, ``"4m32s"``);
    hour-plus durations render minute granularity (``"2h05m"``), so the
    bucket only advances once a minute there. The hint is the row's last
    computed elapsed; a quantum change forces exactly one recompute at the
    hour boundary.
    """
    quantum = 60 if elapsed_hint is not None and elapsed_hint >= 3600 else 1
    return (quantum, int(now_epoch // quantum))


def _aggregate_runtime(
    agent: "Agent", now: datetime, seen: set[int]
) -> RuntimeInterval | None:
    """Return the aggregate interval from direct runtime children.

    Caches the now-independent member wires per container identity plus
    member runtime inputs (phase ``runtime-tick-caches``). Phase
    ``tick-compare-skip`` additionally keys the computed interval on
    ``(membership signature, displayed bucket)``: a repeated tick in the
    same bucket reuses the interval without the ``asdict()`` + Rust
    aggregation, and a settled (inactive) interval is reused for any
    bucket since it is ``now``-independent. Interval-union semantics are
    unchanged: any wire-input change misses and recomputes.
    """
    children = getattr(agent, "runtime_children", ())
    if not children:
        return None

    try:
        now_epoch = now.timestamp()
    except Exception:  # noqa: BLE001 - defensive clock read only.
        now_epoch = -1.0

    fast_key = (
        _aggregate_fast_cache_key(agent)
        if bool(getattr(agent, "is_clan_container", False))
        else None
    )
    revision = _runtime_input_revision
    fast_hit = _aggregate_fast_cache.get(fast_key) if fast_key is not None else None
    if (
        fast_key is not None
        and fast_hit is not None
        and fast_hit[0]() is agent
        and fast_hit[1] == revision
    ):
        try:
            _aggregate_fast_cache.move_to_end(fast_key)
        except Exception:  # noqa: BLE001 - LRU touch is best-effort.
            pass
        _, _, quantum, bucket, interval, covered_member_ids = fast_hit
        if not interval.active:
            seen.update(covered_member_ids)
            return interval
        if _display_bucket(now_epoch, interval.elapsed_seconds) == (quantum, bucket):
            seen.update(covered_member_ids)
            return interval

    include_monitor_turns = aggregates_agent_session_turns(agent)
    visited_ids: list[int] | None = [] if fast_key is not None else None
    members = _collect_aggregate_member_rows(
        agent,
        include_monitor_turns,
        seen,
        visited_ids=visited_ids,
    )
    if not members:
        return None
    key = _aggregate_cache_key(agent, members)
    result_hit = _aggregate_result_cache.get(key)
    if result_hit is not None:
        try:
            _aggregate_result_cache.move_to_end(key)
        except Exception:  # noqa: BLE001 - LRU touch is best-effort.
            pass
        quantum, bucket, interval = result_hit
        if not interval.active:
            if fast_key is not None:
                _remember_fast_aggregate(
                    fast_key,
                    agent,
                    revision,
                    interval,
                    now_epoch,
                    tuple(visited_ids or ()),
                )
            return interval
        if _display_bucket(now_epoch, interval.elapsed_seconds) == (quantum, bucket):
            if fast_key is not None:
                _remember_fast_aggregate(
                    fast_key,
                    agent,
                    revision,
                    interval,
                    now_epoch,
                    tuple(visited_ids or ()),
                )
            return interval
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
    interval = RuntimeInterval(
        elapsed_seconds=runtime.wall_clock_seconds,
        terminal_time=None if runtime.active else max(terminal_times, default=None),
        active=runtime.active,
    )
    _aggregate_result_cache[key] = (
        *_display_bucket(now_epoch, interval.elapsed_seconds),
        interval,
    )
    while len(_aggregate_result_cache) > _AGGREGATE_RESULT_CACHE_MAX:
        try:
            _aggregate_result_cache.popitem(last=False)
        except KeyError:
            break
    if fast_key is not None:
        _remember_fast_aggregate(
            fast_key,
            agent,
            revision,
            interval,
            now_epoch,
            tuple(visited_ids or ()),
        )
    return interval


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

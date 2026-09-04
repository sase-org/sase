"""Session-scoped launch records for last-launch agent actions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult


MAX_SESSION_LAUNCH_RECORDS = 8


class LaunchRecordState(StrEnum):
    """Lifecycle state for an accepted launch recorded by this ACE session."""

    IN_FLIGHT = "in_flight"
    RESOLVED = "resolved"
    RESOLVED_ACTION_PENDING = "resolved_action_pending"
    FAILED = "failed"
    KILL_PENDING = "kill_pending"
    CONSUMED = "consumed"


@dataclass(frozen=True)
class LaunchRecordContext:
    """Minimal launch context needed to restore an editable launch prompt."""

    display_name: str
    project_file: str
    cl_name: str
    is_project_agent: bool


@dataclass
class LaunchRecord:
    """One accepted launch gesture tracked for this UI session."""

    proc_ids: tuple[str, ...]
    prompt: str
    context: LaunchRecordContext
    submitted_prompts: dict[str, str] = field(default_factory=dict)
    results: dict[str, tuple[AgentLaunchResult, ...]] = field(default_factory=dict)
    failed_proc_ids: set[str] = field(default_factory=set)
    state: LaunchRecordState = LaunchRecordState.IN_FLIGHT

    @property
    def display_name(self) -> str:
        """Return the user-facing target label for this launch record."""
        return self.context.display_name


def push_launch_record(
    app: object,
    *,
    proc_ids: Sequence[str],
    prompt: str,
    context: LaunchRecordContext,
    submitted_prompts: Mapping[str, str] | None = None,
) -> LaunchRecord | None:
    """Append one accepted launch to *app*'s bounded session stack."""
    normalized_proc_ids = _unique_nonempty_proc_ids(proc_ids)
    if not normalized_proc_ids:
        return None
    record = LaunchRecord(
        proc_ids=normalized_proc_ids,
        prompt=prompt,
        context=context,
        submitted_prompts=dict(submitted_prompts or {}),
    )
    stack = _launch_record_stack(app)
    stack.append(record)
    if len(stack) > MAX_SESSION_LAUNCH_RECORDS:
        del stack[: len(stack) - MAX_SESSION_LAUNCH_RECORDS]
    return record


def stamp_launch_record_results(
    app: object,
    proc_id: str,
    results: Sequence[AgentLaunchResult | None],
) -> LaunchRecord | None:
    """Stamp successful terminal results for *proc_id* on its own record."""
    record = launch_record_for_proc_id(app, proc_id)
    if record is None:
        return None
    record.results[proc_id] = tuple(result for result in results if result is not None)
    _refresh_launch_record_state(record)
    return record


def stamp_launch_record_failure(app: object, proc_id: str) -> LaunchRecord | None:
    """Stamp terminal failure for *proc_id* on its own record."""
    record = launch_record_for_proc_id(app, proc_id)
    if record is None:
        return None
    record.failed_proc_ids.add(proc_id)
    _refresh_launch_record_state(record)
    return record


def latest_live_launch_record(app: object) -> LaunchRecord | None:
    """Return the newest launch record that can still be targeted."""
    for record in reversed(_launch_record_stack(app)):
        if record.state not in (
            LaunchRecordState.CONSUMED,
            LaunchRecordState.FAILED,
        ):
            return record
    return None


def consume_launch_record(record: LaunchRecord) -> LaunchRecord:
    """Mark *record* as consumed and return it for call-site convenience."""
    record.state = LaunchRecordState.CONSUMED
    return record


def begin_resolved_launch_action(record: LaunchRecord) -> LaunchRecord:
    """Hold a resolved record while its kill-and-edit action is in progress."""
    if record.state is LaunchRecordState.RESOLVED:
        record.state = LaunchRecordState.RESOLVED_ACTION_PENDING
    return record


def release_resolved_launch_action(record: LaunchRecord) -> LaunchRecord:
    """Make an unacted resolved record targetable again."""
    if record.state is LaunchRecordState.RESOLVED_ACTION_PENDING:
        record.state = LaunchRecordState.RESOLVED
    return record


def launch_record_for_proc_id(app: object, proc_id: str) -> LaunchRecord | None:
    """Return the record that owns *proc_id*, if this session has one."""
    if not proc_id:
        return None
    for record in reversed(_launch_record_stack(app)):
        if proc_id in record.proc_ids:
            return record
    return None


def has_pending_launch_kill(app: object) -> bool:
    """Return whether any session launch record is waiting to be killed at T4."""
    return any(
        record.state is LaunchRecordState.KILL_PENDING
        for record in _launch_record_stack(app)
    )


def record_procs_are_terminal(record: LaunchRecord) -> bool:
    """Return whether every proc on *record* has results or a failure stamp."""
    return all(
        proc_id in record.results or proc_id in record.failed_proc_ids
        for proc_id in record.proc_ids
    )


def release_kill_pending_launch_record(record: LaunchRecord) -> LaunchRecord:
    """Drop ``KILL_PENDING`` so later stamps can move *record* to a terminal state."""
    if record.state is LaunchRecordState.KILL_PENDING:
        record.state = LaunchRecordState.IN_FLIGHT
        _refresh_launch_record_state(record)
    return record


def _launch_record_stack(app: object) -> list[LaunchRecord]:
    stack = getattr(app, "_session_launch_records", None)
    if isinstance(stack, list):
        return stack
    stack = []
    cast(Any, app)._session_launch_records = stack
    return stack


def _refresh_launch_record_state(record: LaunchRecord) -> None:
    if record.state in (
        LaunchRecordState.KILL_PENDING,
        LaunchRecordState.RESOLVED_ACTION_PENDING,
        LaunchRecordState.CONSUMED,
    ):
        return
    if record.failed_proc_ids:
        record.state = LaunchRecordState.FAILED
        return
    if all(proc_id in record.results for proc_id in record.proc_ids):
        record.state = LaunchRecordState.RESOLVED
        return
    record.state = LaunchRecordState.IN_FLIGHT


def _unique_nonempty_proc_ids(proc_ids: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for proc_id in proc_ids:
        if not proc_id or proc_id in seen:
            continue
        normalized.append(proc_id)
        seen.add(proc_id)
    return tuple(normalized)


__all__ = [
    "LaunchRecord",
    "LaunchRecordContext",
    "LaunchRecordState",
    "MAX_SESSION_LAUNCH_RECORDS",
    "begin_resolved_launch_action",
    "consume_launch_record",
    "has_pending_launch_kill",
    "latest_live_launch_record",
    "launch_record_for_proc_id",
    "push_launch_record",
    "record_procs_are_terminal",
    "release_resolved_launch_action",
    "release_kill_pending_launch_record",
    "stamp_launch_record_failure",
    "stamp_launch_record_results",
]

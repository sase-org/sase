"""Per-record admission/occupancy predicates and agent-session grouping."""

from __future__ import annotations

from collections.abc import Iterable

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    AgentSessionTurnWire,
)
from sase.monitor_state import is_real_monitor_member

from ._admission_ordering import normalize_wait_priority
from ._admission_types import RecordLiveness

GATE_AGENT_SESSION_ROLE = "gate"


def _agent_session_turn_of_kind(
    meta: AgentMetaWire | None, kind: str
) -> AgentSessionTurnWire | None:
    shell = None if meta is None else meta.agent_session_turn
    return shell if shell is not None and shell.kind == kind else None


def is_root_user_agent_record(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record* represents a top-level user agent."""
    if record.workflow_dir_name != "ace-run" or record.has_done_marker:
        return False
    meta = record.agent_meta
    if meta is None or meta.parent_timestamp:
        return False
    state = record.workflow_state
    return state is None or state.appears_as_agent


def is_runner_slot_user_agent_record(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record* may itself be parked and queued at the gate.

    This answers the *admission* question only: a live root or a live
    parallel agent-session member waits for its own slot, while a serial
    agent-session member (a non-parallel child, a monitor, or a monitor
    follow-up) rides the slot its agent session already holds and is exempt
    from waiting. It does not answer the *occupancy* question of how many
    slots are in use -- see `is_runner_slot_occupying_record` /
    `running_agent_slot_count` for that, which is decided per agent session
    rather than per record.
    """
    if record.workflow_dir_name != "ace-run" or record.has_done_marker:
        return False
    meta = record.agent_meta
    if meta is None or (meta.parent_timestamp and not meta.agent_session_parallel):
        return False
    state = record.workflow_state
    return state is None or state.appears_as_agent


def better_priority_agent_pending(
    records: Iterable[AgentArtifactRecordWire],
    is_live: RecordLiveness,
    *,
    priority: int,
    me: str,
) -> bool:
    """Return whether a live unparked agent could soon outrank *me*."""
    for record in records:
        meta = record.agent_meta
        waiting = record.waiting
        if (
            not is_runner_slot_user_agent_record(record)
            or record.artifact_dir == me
            or meta is None
            or not is_live(record)
            or bool(meta.run_started_at)
            or (waiting is not None and bool(waiting.slot_requested_at))
        ):
            continue
        if normalize_wait_priority(meta.wait_priority) < priority:
            return True
    return False


def is_runner_slot_occupying_record(
    record: AgentArtifactRecordWire,
    is_live: RecordLiveness,
) -> bool:
    """Return whether *record* is, on its own, occupying a runner slot now.

    This is the primitive `running_agent_slot_count` groups and sums per
    agent session; unlike `is_runner_slot_user_agent_record`, it
    intentionally ignores lineage (``parent_timestamp``), because a live
    serial child, a live monitor member, or a live post-handoff follow-up
    agent can each be the shell currently holding an agent session's slot in
    place of a dead root.

    ``pending_question.json`` is the authoritative marker for a shell that
    has temporarily yielded its slot while awaiting a user answer. The
    marker is retained if an answer is ready but the shell is queued to
    reacquire capacity, and removed only by its successful locked claim.

    "Started" is monitor-aware. An ordinary agent shell needs
    ``agent_meta.run_started_at``, as today. A real monitor member
    (``agent_meta.agent_session_role == "monitor"`` plus a non-empty
    ``agent_meta.monitor_id``) only needs a recorded ``pid``: the supervisor
    pid is written before the starter's runner group is killed, while
    ``run_started_at`` is not written until the monitored command itself
    launches -- requiring it here would open a window across the handoff where
    the starter is already dead and the monitor does not yet count, letting a
    queued agent slip in. Agents that merely inherited ``monitor_id`` still
    use ordinary started semantics.
    """
    if record.workflow_dir_name != "ace-run" or record.has_done_marker:
        return False
    state = record.workflow_state
    if state is not None and not state.appears_as_agent:
        return False
    if record.pending_question is not None:
        return False
    meta = record.agent_meta
    if meta is None:
        return False
    gate_turn = _agent_session_turn_of_kind(meta, "gate")
    if (
        is_real_gate_member_record(record)
        and gate_turn is not None
        and (gate_turn.state or "").strip() == "pending"
    ):
        return False
    monitor_turn = _agent_session_turn_of_kind(meta, "monitor")
    monitor_id = monitor_turn.id if monitor_turn is not None else None
    monitor = is_real_monitor_member(meta.agent_session_role, monitor_id)
    started = meta.pid is not None if monitor else bool(meta.run_started_at)
    if not started:
        return False
    return is_live(record)


def is_real_gate_member_record(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record* is the durable gate-shell member."""
    meta = record.agent_meta
    if (
        meta is None
        or (meta.agent_session_role or "").strip() != GATE_AGENT_SESSION_ROLE
    ):
        return False
    gate_turn = _agent_session_turn_of_kind(meta, "gate")
    gate_id = gate_turn.id if gate_turn is not None else None
    return bool((gate_id or "").strip())


def runner_slot_agent_session_key(record: AgentArtifactRecordWire) -> tuple[str, str]:
    """Return the per-agent-session occupancy grouping key for *record*.

    Grouped by ``(project_name, agent_session)``. A record with no
    ``agent_session`` falls back to its own ``timestamp``, which keeps
    standalone agents and independently launched clan members counting
    individually instead of collapsing into one group.
    """
    meta = record.agent_meta
    # legacy agent-family spelling: pre-rename wires carry ``agent_family``;
    # ``AgentMetaWire`` now declares only ``agent_session`` and its hydrator
    # reads either spelling.
    session = meta.agent_session if meta is not None and meta.agent_session else None
    return (record.project_name, session or record.timestamp)


def group_records_by_runner_slot_agent_session(
    records: Iterable[AgentArtifactRecordWire],
) -> dict[tuple[str, str], list[AgentArtifactRecordWire]]:
    """Group *records* by the agent session `running_agent_slot_count` decides over.

    Exposed so display code (the ACE capacity chip, agent listings) can
    reuse this grouping instead of reimplementing it.
    """
    groups: dict[tuple[str, str], list[AgentArtifactRecordWire]] = {}
    for record in records:
        groups.setdefault(runner_slot_agent_session_key(record), []).append(record)
    return groups

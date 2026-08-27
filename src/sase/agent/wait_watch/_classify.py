"""Classify wait target state from one artifact snapshot."""

from __future__ import annotations

from collections.abc import Sequence

from sase.agent.names._common import is_process_alive
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanWire,
)
from sase.core.dismissed_agent_completion import (
    FAILURE_OUTCOMES,
    KNOWN_DONE_OUTCOMES,
    WAIT_SUCCESS_OUTCOMES,
    effective_done_outcome,
)

from ._resolve import LivenessChecker, record_is_live, record_name, target_records
from ._types import (
    WaitMemberState,
    WaitState,
    WaitTarget,
    WaitTargetKind,
    WaitTargetState,
    is_blocked_state,
)


def classify_wait_targets(
    targets: Sequence[WaitTarget],
    snapshot: AgentArtifactScanWire,
    *,
    wait_blocked: bool = False,
    liveness_checker: LivenessChecker = is_process_alive,
) -> tuple[WaitTargetState, ...]:
    """Classify every target from a single already-loaded artifact snapshot."""

    records = tuple(snapshot.records)
    return tuple(
        classify_wait_target(
            target,
            records,
            wait_blocked=wait_blocked,
            liveness_checker=liveness_checker,
        )
        for target in targets
    )


def classify_wait_target(
    target: WaitTarget,
    records: Sequence[AgentArtifactRecordWire],
    *,
    wait_blocked: bool = False,
    liveness_checker: LivenessChecker = is_process_alive,
) -> WaitTargetState:
    """Classify one target from the same snapshot used for its peers."""

    target_member_records = _member_records_for_target(target, records)
    if not target_member_records:
        return WaitTargetState(
            target=target,
            state=WaitState.STALLED,
            reason="target artifact is missing",
        )
    member_states = tuple(
        _classify_record(record, liveness_checker) for record in target_member_records
    )
    target_state = _aggregate_member_states(member_states, wait_blocked=wait_blocked)
    return WaitTargetState(
        target=target,
        state=target_state,
        members=member_states,
        reason=_target_reason(target_state, member_states),
    )


def _member_records_for_target(
    target: WaitTarget,
    records: Sequence[AgentArtifactRecordWire],
) -> tuple[AgentArtifactRecordWire, ...]:
    selected = target_records(target, records)
    if target.kind is not WaitTargetKind.AGENT:
        return selected
    if not selected:
        return ()
    return (_follow_retry_chain(selected[0], records),)


def _classify_record(
    record: AgentArtifactRecordWire,
    liveness_checker: LivenessChecker,
) -> WaitMemberState:
    outcome = _record_done_outcome(record)
    if record.has_done_marker:
        if outcome in WAIT_SUCCESS_OUTCOMES:
            return _member(record, WaitState.SUCCEEDED, outcome)
        if outcome in FAILURE_OUTCOMES:
            return _member(record, WaitState.FAILED, outcome)
        if outcome in KNOWN_DONE_OUTCOMES or outcome is not None:
            return _member(record, WaitState.TERMINAL_OTHER, outcome)
        return _member(record, WaitState.TERMINAL_OTHER, None, "unreadable done marker")

    live = record_is_live(record, liveness_checker)
    if record.pending_question is not None:
        return _member(record, WaitState.NEEDS_INPUT, reason="pending question")
    if live and _waiting_slot_requested(record):
        return _member(record, WaitState.QUEUED, reason="runner slot requested")
    if live and _wait_dependencies(record):
        return _member(record, WaitState.WAITING, reason="waiting on dependencies")
    if not live and _has_plan_path(record):
        return _member(record, WaitState.NEEDS_REVIEW, reason="plan awaits review")
    if not live:
        return _member(record, WaitState.STALLED, reason="process exited without done")
    state = WaitState.RUNNING if _has_started(record) else WaitState.STARTING
    return _member(record, state)


def _aggregate_member_states(
    members: Sequence[WaitMemberState],
    *,
    wait_blocked: bool,
) -> WaitState:
    member_states = tuple(member.state for member in members)
    if any(state is WaitState.FAILED for state in member_states):
        return WaitState.FAILED
    if any(state is WaitState.TERMINAL_OTHER for state in member_states):
        return WaitState.TERMINAL_OTHER
    if any(is_blocked_state(state) for state in member_states):
        if not wait_blocked or all(
            state is WaitState.SUCCEEDED or is_blocked_state(state)
            for state in member_states
        ):
            return _first_present(
                member_states,
                (WaitState.NEEDS_INPUT, WaitState.NEEDS_REVIEW, WaitState.STALLED),
            )
    if all(state is WaitState.SUCCEEDED for state in member_states):
        return WaitState.SUCCEEDED
    return _first_present(
        member_states,
        (WaitState.QUEUED, WaitState.WAITING, WaitState.RUNNING, WaitState.STARTING),
    )


def _first_present(
    states: Sequence[WaitState],
    precedence: Sequence[WaitState],
) -> WaitState:
    for state in precedence:
        if state in states:
            return state
    return states[0] if states else WaitState.STALLED


def _target_reason(
    state: WaitState,
    members: Sequence[WaitMemberState],
) -> str | None:
    if len(members) == 1:
        return members[0].reason
    for member in members:
        if member.state is state and member.reason:
            return f"{member.name}: {member.reason}"
    return None


def _follow_retry_chain(
    record: AgentArtifactRecordWire,
    records: Sequence[AgentArtifactRecordWire],
) -> AgentArtifactRecordWire:
    by_project_workflow_timestamp = {
        (
            candidate.project_name,
            candidate.workflow_dir_name,
            candidate.timestamp,
        ): candidate
        for candidate in records
    }
    current = record
    seen: set[tuple[str, str, str]] = set()
    while True:
        key = (current.project_name, current.workflow_dir_name, current.timestamp)
        if key in seen:
            return current
        seen.add(key)
        retry_timestamp = _retry_successor_timestamp(current)
        if retry_timestamp is None:
            return current
        successor = by_project_workflow_timestamp.get(
            (current.project_name, current.workflow_dir_name, retry_timestamp)
        )
        if successor is None:
            return current
        current = successor


def _retry_successor_timestamp(record: AgentArtifactRecordWire) -> str | None:
    if record.done is not None and record.done.retried_as_timestamp:
        return record.done.retried_as_timestamp
    if record.agent_meta is not None and record.agent_meta.retried_as_timestamp:
        return record.agent_meta.retried_as_timestamp
    return None


def _record_done_outcome(record: AgentArtifactRecordWire) -> str | None:
    if record.done is None:
        return None
    shell = record.done.family_shell
    monitor_state = (
        shell.state if shell is not None and shell.kind == "monitor" else None
    )
    return effective_done_outcome(
        {
            "outcome": record.done.outcome,
            "monitor_state": monitor_state,
        }
    )


def _member(
    record: AgentArtifactRecordWire,
    state: WaitState,
    outcome: str | None = None,
    reason: str | None = None,
) -> WaitMemberState:
    return WaitMemberState(
        name=record_name(record),
        artifact_dir=record.artifact_dir,
        state=state,
        outcome=outcome,
        project_name=record.project_name,
        timestamp=record.timestamp,
        reason=reason,
    )


def _waiting_slot_requested(record: AgentArtifactRecordWire) -> bool:
    return bool(record.waiting is not None and record.waiting.slot_requested_at)


def _wait_dependencies(record: AgentArtifactRecordWire) -> bool:
    if record.waiting is not None and (
        record.waiting.waiting_for or record.waiting.wait_for_beads
    ):
        return True
    meta = record.agent_meta
    return bool(meta is not None and (meta.wait_for or meta.wait_for_beads))


def _has_plan_path(record: AgentArtifactRecordWire) -> bool:
    if record.plan_path is not None and record.plan_path.plan_path:
        return True
    meta = record.agent_meta
    return bool(meta is not None and meta.plan_path)


def _has_started(record: AgentArtifactRecordWire) -> bool:
    meta = record.agent_meta
    if meta is None:
        return False
    return bool(meta.run_started_at or meta.wait_completed_at)

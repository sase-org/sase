"""Per-target live-wait rows: status, why-column, and terminal-blocker warnings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sase.agent.names._common import is_process_alive
from sase.agent.running_listing import active_status_for_record
from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    status_bucket_for_values,
)
from sase.agent.wait_watch import (
    WaitState,
    WaitTargetState,
    is_terminal_state,
    record_is_live,
)
from sase.agents._wait_render_plain import format_duration
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
)
from sase.core.runner_slots import (
    live_runner_slot_waiters,
    runner_slot_queue_display_key,
    running_agent_slot_count,
)
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    dependency_resolution_status,
)
from sase.monitor_state import is_monitor_member_role
from sase.monitor_status import (
    DEFAULT_MONITOR_STOP_STATUS,
    MonitorStatusPair,
    clamp_monitor_status_or_default,
    monitor_status_pair,
)
from sase.project_display_names import (
    humanize_vcs_refs_in_text,
    project_display_name_for,
)

_PROMPT_WHY_MAX_CHARS = 40

_WAIT_STATE_STATUS: dict[WaitState, tuple[str, str]] = {
    WaitState.SUCCEEDED: ("DONE", "Done"),
    WaitState.FAILED: ("FAILED", "Failed"),
    WaitState.TERMINAL_OTHER: ("DONE", "Done"),
    WaitState.QUEUED: ("QUEUED", "Queued"),
    WaitState.WAITING: ("WAITING", "Waiting"),
    WaitState.NEEDS_INPUT: ("QUESTION", "Stopped"),
    WaitState.STALLED: ("STALLED", "Stopped"),
    WaitState.NEEDS_REVIEW: ("PLAN", "Stopped"),
    WaitState.RUNNING: ("RUNNING", "Running"),
    WaitState.STARTING: ("STARTING", "Starting"),
}


@dataclass(frozen=True)
class WaitLiveRow:
    """One rendered live-wait row, matching ``sase agent list`` columns."""

    name: str
    project: str
    workspace: str
    model: str
    status: str
    status_bucket: str
    duration: str
    why: str
    succeeded: bool
    failed: bool
    blocked: bool
    error: str | None = None
    blocked_reason: str | None = None
    inspect_commands: tuple[str, ...] = ()
    unblock_command: str | None = None
    monitor: MonitorStatusPair | None = None
    monitor_state: str | None = None

    @property
    def glyph(self) -> str:
        return AGENT_STATUS_BUCKET_GLYPHS.get(self.status_bucket, "")

    @property
    def unfinished(self) -> bool:
        return not self.succeeded and not self.failed


@dataclass(frozen=True)
class _QueueContext:
    position_by_dir: Mapping[str, int]
    queue_size: int
    slots_in_use: int


def build_wait_live_rows(
    target_states: Sequence[WaitTargetState],
    snapshot: AgentArtifactScanWire,
    *,
    elapsed_seconds: float,
) -> tuple[WaitLiveRow, ...]:
    """Return live-panel rows for *target_states*, unfinished first."""

    records_by_dir = {record.artifact_dir: record for record in snapshot.records}
    queue = _queue_context(snapshot.records)
    rows: list[WaitLiveRow] = []
    for target_state in target_states:
        rows.extend(
            _rows_for_target(
                target_state,
                records_by_dir,
                queue=queue,
                elapsed_seconds=elapsed_seconds,
            )
        )
    rows.sort(key=lambda row: (not row.unfinished, row.name))
    return tuple(rows)


def format_elapsed_clock(seconds: float) -> str:
    """Return ``MM:SS`` (or ``HH:MM:SS``) elapsed clock text."""

    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def terminal_blocker_warnings(
    target_states: Sequence[WaitTargetState],
    snapshot: AgentArtifactScanWire,
) -> tuple[str, ...]:
    """Return warnings for WAITING targets blocked by a failed dependency."""

    index = _index_from_snapshot(snapshot)
    records_by_dir = {record.artifact_dir: record for record in snapshot.records}
    warnings: list[str] = []
    seen: set[str] = set()
    for target_state in target_states:
        members = target_state.members or ()
        if not members:
            continue
        for member in members:
            if member.state is not WaitState.WAITING:
                continue
            record = records_by_dir.get(member.artifact_dir)
            if record is None:
                continue
            waiting_for = _wait_for_names(record)
            if not waiting_for:
                continue
            status = dependency_resolution_status(
                index,
                waiting_for,
                self_artifact_dir=record.artifact_dir,
            )
            if status.resolved:
                continue
            for name in status.blocked_on:
                for blocker in index.terminal_blocking_artifacts_for_name(
                    name,
                    exclude_artifact_dir=record.artifact_dir,
                ):
                    if not blocker.is_failed:
                        continue
                    text = (
                        f"{member.name} waits on {name}, which FAILED"
                        " — it will not start"
                    )
                    if text not in seen:
                        seen.add(text)
                        warnings.append(text)
    return tuple(warnings)


def _rows_for_target(
    target_state: WaitTargetState,
    records_by_dir: Mapping[str, AgentArtifactRecordWire],
    *,
    queue: _QueueContext,
    elapsed_seconds: float,
) -> list[WaitLiveRow]:
    members = target_state.members
    if len(members) > 1:
        return [
            _row_for_member(
                member.name,
                member.state,
                reason=member.reason,
                record=records_by_dir.get(member.artifact_dir),
                queue=queue,
                elapsed_seconds=elapsed_seconds,
            )
            for member in members
        ]
    record = records_by_dir.get(members[0].artifact_dir) if members else None
    return [
        _row_for_member(
            target_state.target.name,
            target_state.state,
            reason=target_state.reason,
            record=record,
            queue=queue,
            elapsed_seconds=elapsed_seconds,
        )
    ]


def _row_for_member(
    name: str,
    state: WaitState,
    *,
    reason: str | None,
    record: AgentArtifactRecordWire | None,
    queue: _QueueContext,
    elapsed_seconds: float,
) -> WaitLiveRow:
    meta = None if record is None else record.agent_meta
    done = None if record is None else record.done
    succeeded = state is WaitState.SUCCEEDED
    failed = is_terminal_state(state) and not succeeded
    blocked = state in {
        WaitState.NEEDS_INPUT,
        WaitState.NEEDS_REVIEW,
        WaitState.STALLED,
    }
    status, bucket, monitor, monitor_state = _display_status(state, record)
    error = _error_text(done, reason, failed=failed)
    blocked_reason = reason if blocked else None
    return WaitLiveRow(
        name=name,
        project=_project_label(record),
        workspace=_workspace_label(meta, done),
        model=_model_label(meta, done),
        status=status,
        status_bucket=bucket,
        duration=format_duration(elapsed_seconds),
        why=_why_column(
            state,
            record,
            queue=queue,
            error=error,
            reason=reason,
        ),
        succeeded=succeeded,
        failed=failed,
        blocked=blocked,
        error=error,
        blocked_reason=blocked_reason,
        inspect_commands=_inspect_commands(name, failed=failed, blocked=blocked),
        unblock_command=_unblock_command(state),
        monitor=monitor,
        monitor_state=monitor_state,
    )


def _display_status(
    state: WaitState,
    record: AgentArtifactRecordWire | None,
) -> tuple[str, str, MonitorStatusPair | None, str | None]:
    fallback_status, fallback_bucket = _WAIT_STATE_STATUS.get(
        state, ("RUNNING", "Running")
    )
    if record is None:
        return fallback_status, fallback_bucket, None, None
    meta = record.agent_meta
    done = record.done
    monitor = _monitor_pair(meta, done)
    monitor_state = _monitor_state(meta, done)
    if _is_monitor(meta):
        if record.has_done_marker:
            status = clamp_monitor_status_or_default(
                (None if done is None else done.status_label)
                or (None if meta is None else meta.monitor_stop_status),
                default=DEFAULT_MONITOR_STOP_STATUS,
            )
        else:
            status = active_status_for_record(record)
        bucket = status_bucket_for_values(status)
        return status, bucket, monitor, monitor_state
    if record.has_done_marker:
        status = fallback_status
        if done is not None and done.outcome in {"failed", "epic_launch_failed"}:
            status = "FAILED"
        elif state is WaitState.FAILED:
            status = "FAILED"
        elif state is WaitState.SUCCEEDED:
            status = "DONE"
        return status, status_bucket_for_values(status), monitor, monitor_state
    if state is WaitState.QUEUED:
        return "QUEUED", "Queued", monitor, monitor_state
    if state is WaitState.WAITING:
        return "WAITING", "Waiting", monitor, monitor_state
    if state is WaitState.NEEDS_INPUT:
        return "QUESTION", "Stopped", monitor, monitor_state
    if state is WaitState.NEEDS_REVIEW:
        return "PLAN", "Stopped", monitor, monitor_state
    if state is WaitState.STALLED:
        return "STALLED", "Stopped", monitor, monitor_state
    status = active_status_for_record(record)
    return status, status_bucket_for_values(status), monitor, monitor_state


def _why_column(
    state: WaitState,
    record: AgentArtifactRecordWire | None,
    *,
    queue: _QueueContext,
    error: str | None,
    reason: str | None,
) -> str:
    if state in {WaitState.FAILED, WaitState.TERMINAL_OTHER} and error:
        return error
    if state is WaitState.WAITING:
        names = _wait_for_names(record) if record is not None else ()
        if names:
            return f"waits on {', '.join(names)}"
        beads = _wait_for_beads(record) if record is not None else ()
        if beads:
            return f"waits on beads {', '.join(beads)}"
        return reason or "waiting on dependencies"
    if state is WaitState.QUEUED:
        artifact_dir = "" if record is None else record.artifact_dir
        position = queue.position_by_dir.get(artifact_dir)
        if position is not None and queue.queue_size:
            return f"slot {position} of {queue.queue_size}"
        if position is not None and queue.slots_in_use:
            return f"slot {position} of {queue.slots_in_use}"
        return reason or "queued for a runner slot"
    if record is not None and _is_monitor(record.agent_meta):
        command = _monitor_command(record)
        if command:
            if state is WaitState.SUCCEEDED:
                exit_code = _monitor_exit_code(record)
                if exit_code is not None:
                    return f"exit {exit_code}"
            return command
    if state in {WaitState.NEEDS_INPUT, WaitState.NEEDS_REVIEW, WaitState.STALLED}:
        return reason or ""
    if record is not None and not (
        state is WaitState.SUCCEEDED or state is WaitState.FAILED
    ):
        snippet = _prompt_snippet(record)
        if snippet:
            return snippet
    return reason or ""


def _inspect_commands(name: str, *, failed: bool, blocked: bool) -> tuple[str, ...]:
    if failed or blocked:
        return (f"sase agent show {name}", f"sase chat {name}")
    return ()


def _unblock_command(state: WaitState) -> str | None:
    if state is WaitState.NEEDS_INPUT:
        return "sase questions"
    if state is WaitState.NEEDS_REVIEW:
        return "sase plan approve"
    return None


def _queue_context(records: Sequence[AgentArtifactRecordWire]) -> _QueueContext:
    is_live = _record_is_live
    slots_in_use = running_agent_slot_count(records, is_live)
    waiters = sorted(
        live_runner_slot_waiters(records, is_live),
        key=lambda waiter: runner_slot_queue_display_key(
            running_count=slots_in_use,
            threshold=waiter.threshold,
            priority=waiter.priority,
            slot_requested_at=waiter.slot_requested_at,
            timestamp=waiter.timestamp,
            artifact_dir=waiter.artifact_dir,
        ),
    )
    return _QueueContext(
        position_by_dir={
            waiter.artifact_dir: index for index, waiter in enumerate(waiters, 1)
        },
        queue_size=len(waiters),
        slots_in_use=slots_in_use,
    )


def _record_is_live(record: AgentArtifactRecordWire) -> bool:
    return record_is_live(record, is_process_alive)


def _index_from_snapshot(snapshot: AgentArtifactScanWire) -> WaitDependencyIndex:
    index = WaitDependencyIndex.empty()
    for record in snapshot.records:
        meta = asdict(record.agent_meta) if record.agent_meta is not None else {}
        done_data: dict[str, Any] | None
        if record.done is not None and record.has_done_marker:
            done_data = asdict(record.done)
        elif record.has_done_marker:
            done_data = {}
        else:
            done_data = None
        index.add_scan_record(
            Path(record.artifact_dir),
            meta,
            project_name=record.project_name,
            done_data=done_data,
        )
    return index


def _wait_for_names(record: AgentArtifactRecordWire) -> tuple[str, ...]:
    waiting = record.waiting
    if waiting is not None and waiting.waiting_for:
        return tuple(waiting.waiting_for)
    meta = record.agent_meta
    if meta is not None and meta.wait_for:
        return tuple(meta.wait_for)
    return ()


def _wait_for_beads(record: AgentArtifactRecordWire) -> tuple[str, ...]:
    waiting = record.waiting
    if waiting is not None and waiting.wait_for_beads:
        return tuple(waiting.wait_for_beads)
    meta = record.agent_meta
    if meta is not None and meta.wait_for_beads:
        return tuple(meta.wait_for_beads)
    return ()


def _project_label(record: AgentArtifactRecordWire | None) -> str:
    if record is None:
        return "-"
    return project_display_name_for(record.project_name) or record.project_name


def _workspace_label(meta: AgentMetaWire | None, done: DoneMarkerWire | None) -> str:
    workspace = None if meta is None else meta.workspace_num
    if workspace is None and done is not None:
        workspace = done.workspace_num
    return "-" if workspace is None else str(workspace)


def _model_label(meta: AgentMetaWire | None, done: DoneMarkerWire | None) -> str:
    model = None if meta is None else meta.model
    if not model and done is not None:
        model = done.model
    return model or "-"


def _is_monitor(meta: AgentMetaWire | None) -> bool:
    if meta is None:
        return False
    return is_monitor_member_role(meta.agent_family_role, meta.role_suffix)


def _monitor_pair(
    meta: AgentMetaWire | None, done: DoneMarkerWire | None
) -> MonitorStatusPair | None:
    if not _is_monitor(meta):
        return None
    start = None if meta is None else meta.monitor_start_status
    stop = None if done is None else done.status_label
    if not stop and meta is not None:
        stop = meta.monitor_stop_status
    if not start and not stop:
        return None
    return monitor_status_pair(start, stop)


def _monitor_state(
    meta: AgentMetaWire | None, done: DoneMarkerWire | None
) -> str | None:
    if done is not None and done.monitor_state:
        return done.monitor_state
    if meta is not None:
        return meta.monitor_state
    return None


def _monitor_command(record: AgentArtifactRecordWire) -> str | None:
    meta = record.agent_meta
    if meta is None:
        return None
    return meta.monitor_command


def _monitor_exit_code(record: AgentArtifactRecordWire) -> int | None:
    done = record.done
    if done is not None and done.monitor_exit_code is not None:
        return done.monitor_exit_code
    meta = record.agent_meta
    if meta is not None:
        return meta.monitor_exit_code
    return None


def _error_text(
    done: DoneMarkerWire | None, reason: str | None, *, failed: bool
) -> str | None:
    if not failed:
        return None
    if done is not None and done.error:
        return done.error
    return reason


def _prompt_snippet(record: AgentArtifactRecordWire) -> str:
    raw = record.raw_prompt_snippet
    if not raw:
        return ""
    text = humanize_vcs_refs_in_text(raw).replace("\n", " ").strip()
    if len(text) <= _PROMPT_WHY_MAX_CHARS:
        return text
    return text[: max(_PROMPT_WHY_MAX_CHARS - 1, 1)] + "…"


__all__ = [
    "WaitLiveRow",
    "build_wait_live_rows",
    "format_elapsed_clock",
    "terminal_blocker_warnings",
]

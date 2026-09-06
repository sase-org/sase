"""Shared helpers for snapshot-backed running-agent listings."""

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.agent.listing_snapshot import snapshot_trace_bytes
from sase.agent.names import is_process_alive
from sase.agent.status_buckets import valid_status_bucket
from sase.core.agent_scan_wire import AgentArtifactRecordWire, AgentArtifactScanWire
from sase.core.runner_slots import (
    group_records_by_runner_slot_family,
    is_runner_slot_occupying_record,
)
from sase.core.time import get_timezone
from sase.monitor_state import is_monitor_member_role, monitor_state_bucket
from sase.monitor_status import (
    DEFAULT_MONITOR_START_STATUS,
    DEFAULT_MONITOR_STOP_STATUS,
    clamp_monitor_status_or_default,
)

from ._running_listing_types import ListingDecodeCounters

ProcessAliveProbe = Callable[[dict[str, object], Path], bool]
RecordLiveProbe = Callable[[AgentArtifactRecordWire], bool]


def finish_decode_trace(
    extra: dict[str, Any],
    *,
    snapshot: AgentArtifactScanWire,
    result_count: int,
    counters: ListingDecodeCounters,
) -> None:
    extra.update(
        {
            "record_count": len(snapshot.records),
            "result_count": result_count,
            "liveness_checks": counters.liveness_checks,
        }
    )
    snapshot_bytes = snapshot_trace_bytes(snapshot)
    if snapshot_bytes is not None:
        extra["decode_bytes"] = snapshot_bytes


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h{minutes}m"
    if minutes > 0:
        return f"{minutes}m{secs}s"
    return f"{secs}s"


def parse_started_at(timestamp: str) -> datetime | None:
    try:
        return datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=get_timezone()
        )
    except ValueError:
        return None


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=get_timezone())
    return parsed


def record_is_live(
    record: AgentArtifactRecordWire,
    *,
    process_alive: ProcessAliveProbe = is_process_alive,
) -> bool:
    meta = record.agent_meta
    pid = None if meta is None else meta.pid
    if pid is None and record.running is not None:
        pid = record.running.pid
    liveness: dict[str, object] = {}
    if pid is not None:
        liveness["pid"] = pid
    if meta is not None:
        if meta.stopped_at is not None:
            liveness["stopped_at"] = meta.stopped_at
        process_identity = getattr(meta, "process_identity", None)
        if process_identity is not None:
            liveness["process_identity"] = process_identity
    if (
        "process_identity" not in liveness
        and record.running is not None
        and getattr(record.running, "process_identity", None) is not None
    ):
        liveness["process_identity"] = record.running.process_identity
    return process_alive(liveness, Path(record.artifact_dir))


def runner_slot_holder_dirs(
    records: Iterable[AgentArtifactRecordWire],
    *,
    record_is_live: RecordLiveProbe = record_is_live,
) -> frozenset[str]:
    """Return the artifact_dir of each shell credited with holding a slot.

    Mirrors `running_agent_slot_count`'s per-family dedup so this listing's
    summed `holds_runner_slot` flags match the admission gate's occupancy
    count for the same snapshot: a serial family holds one slot no matter
    how many of its shells are simultaneously live (an overlapping root and
    a successor mid-handoff, for instance), so only one representative
    shell is credited per family. Each live parallel member still holds its
    own slot and is credited individually.
    """
    holders: set[str] = set()
    for group in group_records_by_runner_slot_family(records).values():
        serial_holder: str | None = None
        for candidate in group:
            if not is_runner_slot_occupying_record(candidate, record_is_live):
                continue
            meta = candidate.agent_meta
            if meta is not None and meta.agent_family_parallel:
                holders.add(candidate.artifact_dir)
            elif serial_holder is None:
                serial_holder = candidate.artifact_dir
        if serial_holder is not None:
            holders.add(serial_holder)
    return frozenset(holders)


def recorded_monitor_status(value: str | None) -> str | None:
    """Clamp a stored monitor label, or return ``None`` when missing/invalid."""
    if value is None:
        return None
    return clamp_monitor_status_or_default(value, default="") or None


def is_monitor_member_meta(meta: object | None) -> bool:
    return bool(
        meta is not None
        and is_monitor_member_role(
            getattr(meta, "agent_family_role", None),
            getattr(meta, "role_suffix", None),
        )
    )


def monitor_shell_field(source: object | None, field: str) -> Any:
    """Read a shared ``family_shell`` field, only when *source* is a monitor shell."""
    shell = getattr(source, "family_shell", None)
    if shell is not None and getattr(shell, "kind", None) == "monitor":
        return getattr(shell, field, None)
    return None


def monitor_sub_field(source: object | None, field: str) -> Any:
    """Read a monitor-only ``family_shell.monitor`` field."""
    shell = getattr(source, "family_shell", None)
    if shell is not None and getattr(shell, "kind", None) == "monitor":
        monitor = getattr(shell, "monitor", None)
        if monitor is not None:
            return getattr(monitor, field, None)
    return None


def active_status_for_record(record: AgentArtifactRecordWire) -> str:
    if record.waiting is not None:
        return "WAITING"
    pending_question = record.pending_question
    if pending_question is not None:
        request_path = pending_question.request_path
        if request_path:
            try:
                if Path(request_path).with_name("question_response.json").exists():
                    return "ANSWERED"
            except OSError:
                pass
        return "QUESTION"
    meta = record.agent_meta
    if meta is not None and is_monitor_member_meta(meta):
        if meta.run_started_at or meta.wait_completed_at:
            return clamp_monitor_status_or_default(
                monitor_shell_field(meta, "start_status"),
                default=DEFAULT_MONITOR_START_STATUS,
            )
        return "STARTING"
    if meta is not None and (meta.run_started_at or meta.wait_completed_at):
        return "RUNNING"
    return "STARTING"


def record_is_running_monitor(record: AgentArtifactRecordWire) -> bool:
    meta = record.agent_meta
    return bool(
        meta is not None
        and monitor_shell_field(meta, "id")
        and is_monitor_member_meta(meta)
        and monitor_shell_field(meta, "state") == "running"
    )


def record_status_bucket(
    raw_bucket: str | None,
    meta: object | None,
    done: object | None,
) -> str | None:
    monitor_state = monitor_shell_field(done, "state") or monitor_shell_field(
        meta, "state"
    )
    if is_monitor_member_meta(meta):
        return monitor_state_bucket(monitor_state)
    return valid_status_bucket(raw_bucket)


__all__ = [
    "ProcessAliveProbe",
    "RecordLiveProbe",
    "finish_decode_trace",
    "format_duration",
    "is_monitor_member_meta",
    "monitor_shell_field",
    "monitor_sub_field",
    "parse_iso_datetime",
    "parse_started_at",
    "record_is_live",
    "record_is_running_monitor",
    "record_status_bucket",
    "recorded_monitor_status",
    "runner_slot_holder_dirs",
    "active_status_for_record",
]

"""Presentation-neutral rich agent list projections for integrations."""

from __future__ import annotations

from collections.abc import Mapping
from collections import Counter
from dataclasses import replace
from datetime import datetime

from sase.agent.running import RunningAgentInfo, list_all_agents, list_running_agents
from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKETS,
    AGENT_STATUS_BUCKET_GLYPHS,
    PRE_RUN_WAIT_STATUSES,
    runner_slot_display_status,
    status_bucket_for_values,
)
from sase.config.core import get_max_running_agents
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.paths import sase_projects_dir
from sase.core.runner_slots import (
    runner_capacity_snapshot,
    runner_slot_queue_display_key,
    runner_slot_waiter_sort_key,
)
from sase.core.time import get_timezone

from ._agent_list_entry_builder import (
    artifact_timestamp,
    build_agent_list_entry as _build_agent_list_entry,
    record_status_bucket,
)
from ._agent_list_entry_models import (
    AgentChildrenSummary as _AgentChildrenSummary,
    AgentListEntry as AgentListEntry,
    AgentRetryInfo as _AgentRetryInfo,
    AgentWaitInfo as _AgentWaitInfo,
)

__all__ = [
    "AgentListEntry",
    "agent_list_entries",
]

_CHILD_SUMMARY_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    only_workflow_dirs=("ace-run",),
    include_workflow_state=False,
)


def agent_list_entries(
    *,
    include_recent: bool = False,
    project: str | None = None,
) -> list[AgentListEntry]:
    """Return rich agent list entries for active and optionally recent agents."""
    agents = list_all_agents() if include_recent else list_running_agents()
    # The listing layer has already filtered to live roots plus slot-relevant
    # family children and carries exact source-record occupancy. The status
    # fallback preserves compatibility for integrations that construct
    # RunningAgentInfo directly.
    runner_slot_holders = tuple(
        agent.name
        for agent in agents
        if _holds_runner_slot(agent) and agent.name is not None
    )
    runner_slots_in_use = sum(_holds_runner_slot(agent) for agent in agents)
    runner_capacity = _runner_capacity_snapshot_from_listing(
        agents,
        snapshot=getattr(agents, "artifact_snapshot", None),
    )
    now = datetime.now(get_timezone())
    snapshot = getattr(agents, "artifact_snapshot", None)
    records_by_dir = (
        {record.artifact_dir: record for record in snapshot.records}
        if snapshot is not None
        else {}
    )
    child_summaries = (
        _children_by_parent_timestamp(snapshot=snapshot, project=project)
        if agents
        else {}
    )
    entries: list[AgentListEntry] = []
    for agent in agents:
        timestamp = artifact_timestamp(agent)
        children = (
            child_summaries.get((agent.project, timestamp))
            if timestamp is not None
            else None
        )
        entries.append(
            _build_agent_list_entry(
                agent,
                record=records_by_dir.get(agent.artifacts_dir or ""),
                now=now,
                children=children,
            )
        )
    entries = _attach_runner_slot_context(
        entries,
        runner_slots_in_use,
        runner_capacity=runner_capacity,
        runner_slot_holders=runner_slot_holders,
    )
    if project:
        entries = [entry for entry in entries if entry.project == project]
    return entries


def _attach_runner_slot_context(
    entries: list[AgentListEntry],
    runner_slots_in_use: int,
    *,
    runner_capacity: dict[str, object] | None = None,
    runner_slot_holders: tuple[str, ...] = (),
) -> list[AgentListEntry]:
    (
        runner_slots_in_use,
        occupied_capacity,
        effective_limit,
        positions,
        queue_size,
        blockers,
    ) = _runner_slot_context(
        entries,
        runner_slots_in_use=runner_slots_in_use,
        runner_capacity=runner_capacity,
    )
    contextualized: list[AgentListEntry] = []
    for entry in entries:
        slot_queued = id(entry) in positions
        status = runner_slot_display_status(
            entry.status,
            slot_queued=slot_queued,
        )
        bucket = (
            entry.status_bucket
            if status == entry.status
            else status_bucket_for_values(status, entry.retry.retried_as_timestamp)
        )
        wait = entry.wait
        if wait.slot_requested_at:
            wait = replace(
                wait,
                runner_slots_in_use=runner_slots_in_use,
                runner_slot_queue_position=positions.get(id(entry)),
                runner_slot_queue_size=queue_size,
                runner_occupied_capacity=occupied_capacity,
                runner_effective_limit=effective_limit,
                runner_capacity_blockers=blockers.get(id(entry), ()),
                runner_slot_holders=runner_slot_holders,
            )
        contextualized.append(
            replace(
                entry,
                status=status,
                status_bucket=bucket,
                status_glyph=AGENT_STATUS_BUCKET_GLYPHS.get(bucket, ""),
                wait=wait,
            )
        )
    return contextualized


def _runner_capacity_snapshot_from_listing(
    agents: list[RunningAgentInfo],
    *,
    snapshot: AgentArtifactScanWire | None,
) -> dict[str, object] | None:
    if snapshot is None:
        return None
    live_dirs = {
        agent.artifacts_dir
        for agent in agents
        if agent.artifacts_dir is not None
        and agent.pid is not None
        and agent.status not in {"DONE", "FAILED", "FAILED (RETRIED)", "MONITORED"}
    }
    return runner_capacity_snapshot(
        snapshot.records,
        lambda record: record.artifact_dir in live_dirs,
        effective_limit=float(get_max_running_agents()),
    )


def _runner_slot_context(
    entries: list[AgentListEntry],
    *,
    runner_slots_in_use: int,
    runner_capacity: dict[str, object] | None,
) -> tuple[
    int,
    float | None,
    float | None,
    dict[int, int],
    int,
    dict[int, tuple[dict[str, object], ...]],
]:
    if runner_capacity is None:
        fallback_waiters = sorted(
            (entry for entry in entries if _is_live_slot_waiter(entry)),
            key=lambda entry: _runner_slot_waiter_sort_key(
                entry,
                running_count=runner_slots_in_use,
            ),
        )
        return (
            runner_slots_in_use,
            None,
            None,
            {id(entry): index for index, entry in enumerate(fallback_waiters, 1)},
            len(fallback_waiters),
            {},
        )

    by_artifact_dir = {
        entry.artifacts_dir: entry for entry in entries if entry.artifacts_dir
    }
    positions: dict[int, int] = {}
    blockers: dict[int, tuple[dict[str, object], ...]] = {}
    snapshot_waiters = sorted(
        _mapping_tuple(runner_capacity.get("waiters")),
        key=_snapshot_waiter_display_key,
    )
    for index, waiter in enumerate(snapshot_waiters, 1):
        artifact_dir = waiter.get("artifact_dir")
        entry = (
            by_artifact_dir.get(artifact_dir) if isinstance(artifact_dir, str) else None
        )
        if entry is None:
            continue
        positions[id(entry)] = index
        blockers[id(entry)] = _blocker_tuple(waiter.get("blockers"))
    occupied_lanes = runner_capacity.get("occupied_lanes")
    return (
        occupied_lanes if type(occupied_lanes) is int else runner_slots_in_use,
        _finite_float(runner_capacity.get("occupied_capacity")),
        _finite_float(runner_capacity.get("effective_limit")),
        positions,
        len(snapshot_waiters),
        blockers,
    )


def _is_live_slot_waiter(entry: AgentListEntry) -> bool:
    return bool(
        entry.pid is not None
        and entry.wait.slot_requested_at
        and entry.status in PRE_RUN_WAIT_STATUSES
    )


def _runner_slot_waiter_sort_key(
    entry: AgentListEntry,
    *,
    running_count: int,
) -> tuple[int, int, int, int, datetime, str, str]:
    return runner_slot_queue_display_key(
        running_count=running_count,
        threshold=entry.wait.wait_runners,
        priority=entry.wait.wait_priority,
        slot_requested_at=entry.wait.slot_requested_at,
        timestamp=entry.timestamp,
        artifact_dir=entry.artifacts_dir,
    )


def _holds_runner_slot(agent: RunningAgentInfo) -> bool:
    if agent.holds_runner_slot is not None:
        return agent.holds_runner_slot
    return agent.status == "RUNNING"


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) < float("inf") else None


def _blocker_tuple(value: object) -> tuple[dict[str, object], ...]:
    return _mapping_tuple(value)


def _mapping_tuple(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(
        {key: item for key, item in mapping.items() if isinstance(key, str)}
        for mapping in value
        if isinstance(mapping, Mapping)
    )


def _snapshot_waiter_display_key(
    waiter: dict[str, object],
) -> tuple[int, int, int, int, datetime, str, str]:
    parked = _snapshot_waiter_is_parked(waiter)
    threshold = _largest_runner_threshold(waiter)
    return (
        1 if parked else 0,
        -threshold if parked else 0,
        *runner_slot_waiter_sort_key(
            priority=waiter.get("priority"),
            slot_requested_at=_text_value(waiter.get("slot_requested_at")),
            timestamp=_text_value(waiter.get("timestamp")),
            artifact_dir=_text_value(waiter.get("artifact_dir")),
        ),
    )


def _snapshot_waiter_is_parked(waiter: dict[str, object]) -> bool:
    if waiter.get("eligible") is True:
        return False
    blockers = _blocker_tuple(waiter.get("blockers"))
    return any(blocker.get("code") != "queue-order" for blocker in blockers)


def _largest_runner_threshold(waiter: dict[str, object]) -> int:
    threshold = waiter.get("wait_runners")
    values = [threshold] if type(threshold) is int and threshold >= 0 else []
    for blocker in _blocker_tuple(waiter.get("blockers")):
        blocker_threshold = blocker.get("runner_threshold")
        if type(blocker_threshold) is int and blocker_threshold >= 0:
            values.append(blocker_threshold)
    return max(values, default=0)


def _text_value(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _children_by_parent_timestamp(
    *,
    snapshot: AgentArtifactScanWire | None = None,
    project: str | None = None,
) -> dict[tuple[str, str], _AgentChildrenSummary]:
    if snapshot is None:
        from sase.core.agent_scan_facade import scan_agent_artifacts

        snapshot = scan_agent_artifacts(
            sase_projects_dir(),
            _CHILD_SUMMARY_SCAN_OPTIONS,
        )
    counts: dict[tuple[str, str], Counter[str]] = {}
    for record in snapshot.records:
        meta = record.agent_meta
        if meta is None or not meta.parent_timestamp:
            continue
        if project and record.project_name != project:
            continue
        if meta.parent_timestamp == record.timestamp:
            continue
        key = (record.project_name, meta.parent_timestamp)
        counts.setdefault(key, Counter()).update([record_status_bucket(record)])
    return {
        key: _AgentChildrenSummary(
            count=sum(bucket_counts.values()),
            status_counts=tuple(
                (bucket, bucket_counts[bucket])
                for bucket in AGENT_STATUS_BUCKETS
                if bucket_counts.get(bucket)
            ),
        )
        for key, bucket_counts in counts.items()
    }

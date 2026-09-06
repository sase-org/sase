"""Presentation-neutral rich agent list projections for integrations."""

from __future__ import annotations

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
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.paths import sase_projects_dir
from sase.core.runner_slots import runner_slot_queue_display_key
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
    if project:
        agents = (
            list_all_agents(project=project)
            if include_recent
            else list_running_agents(project=project)
        )
    else:
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
        runner_slot_holders=runner_slot_holders,
    )
    if project:
        entries = [entry for entry in entries if entry.project == project]
    return entries


def _attach_runner_slot_context(
    entries: list[AgentListEntry],
    runner_slots_in_use: int,
    *,
    runner_slot_holders: tuple[str, ...] = (),
) -> list[AgentListEntry]:
    waiters = sorted(
        (entry for entry in entries if _is_live_slot_waiter(entry)),
        key=lambda entry: _runner_slot_waiter_sort_key(
            entry,
            running_count=runner_slots_in_use,
        ),
    )
    positions = {id(entry): index for index, entry in enumerate(waiters, 1)}
    queue_size = len(waiters)
    contextualized: list[AgentListEntry] = []
    for entry in entries:
        status = runner_slot_display_status(
            entry.status,
            slot_queued=_is_live_slot_waiter(entry),
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

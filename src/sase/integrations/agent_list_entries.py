"""Presentation-neutral rich agent list projections for integrations."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime

from sase.agent.running import RunningAgentInfo, list_all_agents, list_running_agents
from sase.agent.status_buckets import AGENT_STATUS_BUCKETS
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_projects_dir
from sase.core.time import get_timezone

from ._agent_list_entry_builder import (
    artifact_timestamp,
    build_agent_list_entry as _build_agent_list_entry,
    parse_iso_datetime,
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
    now = datetime.now(get_timezone())
    child_summaries = _children_by_parent_timestamp(project=project) if agents else {}
    entries: list[AgentListEntry] = []
    for agent in agents:
        timestamp = artifact_timestamp(agent)
        children = (
            child_summaries.get((agent.project, timestamp))
            if timestamp is not None
            else None
        )
        entries.append(_build_agent_list_entry(agent, now=now, children=children))
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
        (
            entry
            for entry in entries
            if entry.wait.slot_requested_at
            and entry.wait.wait_runners is not None
            and runner_slots_in_use <= entry.wait.wait_runners
        ),
        key=lambda entry: (
            parse_iso_datetime(entry.wait.slot_requested_at)
            or datetime.max.replace(tzinfo=get_timezone()),
            entry.timestamp or "",
            entry.artifacts_dir or "",
        ),
    )
    positions = {id(entry): index for index, entry in enumerate(waiters, 1)}
    queue_size = len(waiters)
    return [
        replace(
            entry,
            wait=replace(
                entry.wait,
                runner_slots_in_use=runner_slots_in_use,
                runner_slot_queue_position=positions.get(id(entry)),
                runner_slot_queue_size=queue_size,
                runner_slot_holders=runner_slot_holders,
            ),
        )
        if entry.wait.slot_requested_at
        else entry
        for entry in entries
    ]


def _holds_runner_slot(agent: RunningAgentInfo) -> bool:
    if agent.holds_runner_slot is not None:
        return agent.holds_runner_slot
    return agent.status == "RUNNING"


def _children_by_parent_timestamp(
    *, project: str | None = None
) -> dict[tuple[str, str], _AgentChildrenSummary]:
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

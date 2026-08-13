"""Index-backed lookups and control for monitor family members.

There is no dedicated monitor store: everything here is a query over the
existing agent artifact index (the same one that backs the Agents tab and
``sase agent`` listing), filtered to monitor family members
(``agent_meta.agent_family_role == "monitor"``).
"""

from __future__ import annotations

import json
import os
import signal
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_projects_dir
from sase.plan_chain import agent_family_base

from .identity import supervisor_is_alive
from .models import MonitorLaneError, MonitorRecord, MonitorRefError
from .naming import short_monitor_id

_DEAD_SUPERVISOR_ERROR = "monitor supervisor died without reporting"

#: How long ``stop_monitor`` waits for the supervisor to leave ``running``.
_STOP_WAIT_SECONDS = 10.0
_STOP_POLL_SECONDS = 0.1

#: Mirrors :data:`sase.tasks.ids.MIN_TASK_REF_LENGTH` for monitor id prefixes.
MIN_MONITOR_REF_LENGTH = 3


@dataclass(frozen=True)
class LaneContext:
    """The lane's newest family member, resolved for a monitor start."""

    lane: str
    project_name: str
    record: AgentArtifactRecordWire


def default_lane(env: Mapping[str, str] | None = None) -> str | None:
    """Return the calling agent's lane from its environment, if any."""
    current_env = env if env is not None else os.environ
    name = current_env.get("SASE_AGENT_NAME")
    if not name:
        return None
    return agent_family_base(name) or name


def resolve_lane(project_name: str, lane: str) -> LaneContext:
    """Resolve *lane* to its newest family member's artifact record."""
    records = [
        record
        for record in _project_records(project_name)
        if _record_in_lane(record, lane)
    ]
    if not records:
        raise MonitorLaneError(
            f"no agent artifacts found for lane {lane!r} in project {project_name!r}"
        )
    newest = max(records, key=lambda record: record.timestamp)
    return LaneContext(lane=lane, project_name=project_name, record=newest)


def active_monitor_for_lane(
    project_name: str, lane: str
) -> AgentArtifactRecordWire | None:
    """Return the not-yet-terminal monitor member for *lane*, if any."""
    candidates: list[AgentArtifactRecordWire] = []
    for record in _monitor_records(project_name):
        meta = record.agent_meta
        if meta is None or meta.agent_family != lane:
            continue
        try:
            monitor = MonitorRecord.from_record(record)
        except ValueError:
            continue
        if not monitor.is_terminal:
            candidates.append(record)
    if not candidates:
        return None
    return max(candidates, key=lambda record: record.timestamp)


def has_any_monitor(project_name: str, lane: str) -> bool:
    """Return whether *lane* has ever had a monitor member."""
    return any(
        record.agent_meta is not None and record.agent_meta.agent_family == lane
        for record in _monitor_records(project_name)
    )


def stop_monitor(record: MonitorRecord) -> MonitorRecord:
    """Terminate a running monitor's supervisor and wait for it to settle.

    A dead supervisor pid is reconciled in place rather than treated as an
    error, mirroring the durable-task store's dead-supervisor handling.
    """
    if record.monitor_state != "running":
        return record
    pid = record.pid
    if pid is None or not supervisor_is_alive(pid, record.supervisor_identity):
        return _reconcile_dead_supervisor(record)

    # The supervisor's own SIGTERM handler forwards to the monitored
    # command's process group; signal the supervisor pid directly rather
    # than its group, mirroring ``sase.tasks.runner.kill_task``.
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return _reconcile_dead_supervisor(record)

    deadline = time.monotonic() + _STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        current = get_monitor(record.project_name, record.artifacts_dir)
        if current is None or current.monitor_state != "running":
            return current if current is not None else record
        if not supervisor_is_alive(pid, record.supervisor_identity):
            return _reconcile_dead_supervisor(record)
        time.sleep(_STOP_POLL_SECONDS)

    return record


def _reconcile_dead_supervisor(record: MonitorRecord) -> MonitorRecord:
    """Mark a monitor failed after its supervisor died without reporting."""
    meta_path = os.path.join(record.artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return record
    if meta.get("monitor_state") != "running":
        current = get_monitor(record.project_name, record.artifacts_dir)
        return current if current is not None else record

    meta["monitor_state"] = "failed"
    write_agent_meta_atomic(
        record.artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )
    write_done_marker_and_update_index(
        record.artifacts_dir,
        {
            "outcome": "monitored",
            "monitor_state": "failed",
            "error": _DEAD_SUPERVISOR_ERROR,
            "status_label": meta.get("monitor_stop_status") or "MONITORED",
        },
    )
    current = get_monitor(record.project_name, record.artifacts_dir)
    return current if current is not None else record


def get_monitor(project_name: str, artifacts_dir: str) -> MonitorRecord | None:
    """Return the current record for one monitor member's artifacts dir."""
    for record in _monitor_records(project_name):
        if record.artifact_dir == artifacts_dir:
            return MonitorRecord.from_record(record)
    return None


def list_monitors(*, project: str | None = None) -> list[MonitorRecord]:
    """Return every monitor record, newest first.

    *project* scopes the scan to one project; ``None`` (the default) scans
    every project, mirroring how ``sase agent list`` scans across projects
    when no ``--project`` filter is given.
    """
    records = [
        MonitorRecord.from_record(record) for record in _monitor_records(project)
    ]
    records.sort(key=lambda record: record.timestamp, reverse=True)
    return records


def resolve_monitor_ref(ref: str, records: Sequence[MonitorRecord]) -> MonitorRecord:
    """Resolve *ref* against *records* by id prefix, member name, or lane.

    A member agent name or lane name must match exactly; a lane name with
    more than one monitor resolves to its active monitor, else its newest.
    Anything else is tried as a monitor-id prefix of at least
    :data:`MIN_MONITOR_REF_LENGTH` characters.
    """
    query = ref.strip()
    if not query:
        raise MonitorRefError("monitor reference must not be empty")

    by_name = [record for record in records if record.member_agent_name == query]
    if len(by_name) == 1:
        return by_name[0]

    by_lane = [record for record in records if record.lane == query]
    if by_lane:
        active = [record for record in by_lane if not record.is_terminal]
        if active:
            return max(active, key=lambda record: record.timestamp)
        return max(by_lane, key=lambda record: record.timestamp)

    lowered = query.lower()
    if len(lowered) < MIN_MONITOR_REF_LENGTH:
        raise MonitorRefError(
            f"no monitor matches reference {ref!r}; a bare id reference must "
            f"be at least {MIN_MONITOR_REF_LENGTH} characters"
        )
    by_id = [record for record in records if record.monitor_id.startswith(lowered)]
    if len(by_id) == 1:
        return by_id[0]
    if not by_id:
        raise MonitorRefError(f"no monitor matches reference {ref!r}")
    candidates = ", ".join(
        f"{short_monitor_id(record.monitor_id)} ({record.label})" for record in by_id
    )
    raise MonitorRefError(
        f"monitor reference {ref!r} is ambiguous; candidates: {candidates}"
    )


def _record_in_lane(record: AgentArtifactRecordWire, lane: str) -> bool:
    meta = record.agent_meta
    if meta is None:
        return False
    if meta.agent_family == lane or meta.workflow_name == lane:
        return True
    return meta.name == lane or agent_family_base(meta.name) == lane


def _monitor_records(project_name: str | None) -> list[AgentArtifactRecordWire]:
    return [
        record
        for record in _project_records(project_name, only_monitors=True)
        if record.agent_meta is not None
        and record.agent_meta.agent_family_role == "monitor"
    ]


def _project_records(
    project_name: str | None, *, only_monitors: bool = False
) -> list[AgentArtifactRecordWire]:
    projects_root = sase_projects_dir()
    options = AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        only_projects=(project_name,) if project_name else (),
    )
    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=True,
        active_limit=None,
        recent_completed_limit=None,
        include_hidden=True,
        only_monitors=only_monitors,
    )
    index_path = default_agent_artifact_index_path()
    if index_path.is_file():
        try:
            scan = query_agent_artifact_index(index_path, projects_root, query, options)
            return list(scan.records)
        except (OSError, RuntimeError, ValueError, ImportError, AttributeError):
            pass
    scan = scan_agent_artifacts(projects_root, options)
    return list(scan.records)


__all__ = [
    "MIN_MONITOR_REF_LENGTH",
    "LaneContext",
    "active_monitor_for_lane",
    "default_lane",
    "get_monitor",
    "has_any_monitor",
    "list_monitors",
    "resolve_lane",
    "resolve_monitor_ref",
    "stop_monitor",
]

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
from typing import Any

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
from sase.core.agent_scan_wire_markers import AgentMetaWire, DoneMarkerWire
from sase.core.paths import sase_projects_dir
from sase.core.wire import known_field_kwargs
from sase.plan_chain import agent_family_base

from .identity import supervisor_is_alive
from .models import (
    MonitorLaneError,
    MonitorRecord,
    MonitorRefError,
    is_monitor_member_record,
)
from .naming import short_monitor_id
from .proc_adapter import overlay_proc_on_monitor, proc_shell_owns
from .reconcile import (
    reconcile_dead_supervisor,
    reconcile_dead_supervisors_for_records,
    should_reconcile_dead_supervisor,
)

#: How long ``stop_monitor`` waits for the supervisor to leave ``running``.
_STOP_WAIT_SECONDS = 10.0
_STOP_POLL_SECONDS = 0.1

#: Mirrors :data:`sase.procs.ids.MIN_PROC_REF_LENGTH` for monitor id prefixes.
MIN_MONITOR_REF_LENGTH = 3


@dataclass(frozen=True)
class LaneContext:
    """A resolved agent artifact used as a monitor parent or lane member."""

    lane: str
    project_name: str
    record: AgentArtifactRecordWire


def default_caller(env: Mapping[str, str] | None = None) -> str | None:
    """Return the calling agent's exact name from its environment, if any.

    Unlike :func:`default_lane`, this does not collapse the name through
    :func:`~sase.plan_chain.agent_family_base`. Implicit monitor starts use
    this exact identity so a phase name such as ``sase-m6.6.1.5`` is not
    rewritten into a broader family lane.
    """
    current_env = env if env is not None else os.environ
    name = current_env.get("SASE_AGENT_NAME")
    if not name:
        return None
    name = name.strip()
    return name or None


def default_lane(env: Mapping[str, str] | None = None) -> str | None:
    """Return the calling agent's family-oriented lane from its environment.

    Used by monitor inspection and stop when no explicit target is given.
    Implicit monitor start reads :func:`default_caller` instead and then
    derives the durable lane from the selected artifact.
    """
    name = default_caller(env)
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


def resolve_exact_agent(project_name: str, agent_name: str) -> LaneContext:
    """Resolve *agent_name* to the newest artifact with that exact name."""
    records = [
        record
        for record in _project_records(project_name)
        if _record_has_name(record, agent_name)
    ]
    if not records:
        raise MonitorLaneError(
            f"no agent artifacts found for agent {agent_name!r} "
            f"in project {project_name!r}"
        )
    newest = max(records, key=lambda record: record.timestamp)
    return LaneContext(lane=agent_name, project_name=project_name, record=newest)


def durable_lane_for_record(record: AgentArtifactRecordWire, *, fallback: str) -> str:
    """Return the durable monitor lane for *record*.

    Prefers persisted ``agent_family`` metadata. A still-bare agent falls
    back to *fallback* (the exact caller name or an explicit lane) rather
    than guessing from the spelling of ``name``.
    """
    meta = record.agent_meta
    if meta is not None:
        family = (meta.agent_family or "").strip()
        if family:
            return family
    return fallback


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
        if should_reconcile_dead_supervisor(monitor):
            monitor = reconcile_dead_supervisor(monitor, get_monitor=get_monitor)
        if not monitor.is_terminal:
            candidates.append(record)
    if not candidates:
        return None
    return max(candidates, key=lambda record: record.timestamp)


def monitor_blocking_start_for_lane(
    project_name: str,
    lane: str,
) -> MonitorRecord | None:
    """Return the monitor that prevents starting a new one in *lane*.

    Same-boot dead supervisors are reconciled to terminal ``failed`` records
    and do not block replacement. Pre-reboot monitors reconcile to ``lost``
    and do block replacement because the command's effect is unknown.
    """
    candidates: list[MonitorRecord] = []
    for record in _monitor_records(project_name):
        meta = record.agent_meta
        if meta is None or meta.agent_family != lane:
            continue
        try:
            monitor = MonitorRecord.from_record(record)
        except ValueError:
            continue
        if monitor.is_terminal:
            continue
        if should_reconcile_dead_supervisor(monitor):
            monitor = reconcile_dead_supervisor(monitor, get_monitor=get_monitor)
        if monitor.monitor_state == "lost" or not monitor.is_terminal:
            candidates.append(monitor)
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
    error, mirroring the durable-proc store's dead-supervisor handling.
    Proc-backed monitors stop through the shared proc service; live legacy
    monitors keep the historical supervisor path and are never copied into
    a new proc row.
    """
    if record.monitor_state != "running":
        return record
    from sase.procs.service import stop_proc_shell
    from sase.procs.store import get_proc

    proc = get_proc(record.monitor_id)
    if proc is not None and proc_shell_owns(record.monitor_id):
        stop_proc_shell(proc)
        current = read_monitor_marker(record.project_name, record.artifacts_dir)
        return current if current is not None else record
    pid = record.pid
    if pid is None or not supervisor_is_alive(pid, record.supervisor_identity):
        return reconcile_dead_supervisor(record, get_monitor=get_monitor)

    # The supervisor's own SIGTERM handler forwards to the monitored
    # command's process group; signal the supervisor pid directly rather
    # than its group, mirroring ``sase.procs.runner.kill_proc``.
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return reconcile_dead_supervisor(record, get_monitor=get_monitor)

    deadline = time.monotonic() + _STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        current = read_monitor_marker(record.project_name, record.artifacts_dir)
        if current is None or current.monitor_state != "running":
            return current if current is not None else record
        if not supervisor_is_alive(pid, record.supervisor_identity):
            return reconcile_dead_supervisor(record, get_monitor=get_monitor)
        time.sleep(_STOP_POLL_SECONDS)

    return record


def get_monitor(project_name: str, artifacts_dir: str) -> MonitorRecord | None:
    """Return the current record for one monitor member's artifacts dir."""
    for record in _monitor_records(project_name):
        if record.artifact_dir == artifacts_dir:
            converted = _monitor_record_from_wire(record)
            if converted is None:
                return None
            return _with_proc_projection(converted)
    return None


def read_monitor_marker(project_name: str, artifacts_dir: str) -> MonitorRecord | None:
    """Read one monitor member's own markers directly, without an index query.

    ``get_monitor()`` runs a full-history, unlimited, hidden-inclusive index
    query (or a full filesystem scan when the index is unavailable) to find
    one record it already knows the path to. Tight polling loops that
    already hold the member's ``artifacts_dir`` -- ``--follow``,
    ``stop_monitor()``'s wait loop, and callers waiting for a monitor to go
    terminal -- should read that member's own ``agent_meta.json`` and
    ``done.json`` directly instead.
    """
    raw_meta = _read_json_object(os.path.join(artifacts_dir, "agent_meta.json"))
    if raw_meta is None:
        return None
    raw_done = _read_json_object(os.path.join(artifacts_dir, "done.json"))

    record = AgentArtifactRecordWire(
        project_name=project_name,
        project_dir="",
        project_file="",
        workflow_dir_name="",
        artifact_dir=artifacts_dir,
        timestamp=os.path.basename(artifacts_dir.rstrip("/")),
        agent_meta=AgentMetaWire(**known_field_kwargs(AgentMetaWire, raw_meta)),
        done=(
            DoneMarkerWire(**known_field_kwargs(DoneMarkerWire, raw_done))
            if raw_done is not None
            else None
        ),
    )
    try:
        projected = MonitorRecord.from_record(record)
    except ValueError:
        return None
    return _with_proc_projection(projected)


def _read_json_object(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def list_monitors(*, project: str | None = None) -> list[MonitorRecord]:
    """Return every monitor record, newest first.

    *project* scopes the scan to one project; ``None`` (the default) scans
    every project, mirroring how ``sase agent list`` scans across projects
    when no ``--project`` filter is given.
    """
    from sase.procs.service import reconcile_proc_shells

    reconcile_proc_shells()
    reconcile_dead_supervisors(project=project)
    records = [
        _with_proc_projection(converted)
        for converted in (
            _monitor_record_from_wire(record) for record in _monitor_records(project)
        )
        if converted is not None
    ]
    records.sort(key=lambda record: record.timestamp, reverse=True)
    return records


def reconcile_dead_supervisors(*, project: str | None = None) -> list[MonitorRecord]:
    """Reconcile all running monitors whose supervisors are no longer alive."""
    return reconcile_dead_supervisors_for_records(
        _monitor_records(project),
        get_monitor=get_monitor,
    )


def _with_proc_projection(record: MonitorRecord) -> MonitorRecord:
    """Overlay proc-shell execution state; never invent a proc for a legacy row."""
    from sase.procs.store import get_proc

    if not proc_shell_owns(record.monitor_id):
        return record
    proc = get_proc(record.monitor_id)
    if proc is None:
        return record
    return overlay_proc_on_monitor(record, proc)


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


def _record_has_name(record: AgentArtifactRecordWire, agent_name: str) -> bool:
    meta = record.agent_meta
    return meta is not None and meta.name == agent_name


def _monitor_record_from_wire(
    record: AgentArtifactRecordWire,
) -> MonitorRecord | None:
    """Convert a scan row, skipping historical false-positive monitor roles."""
    try:
        return MonitorRecord.from_record(record)
    except ValueError:
        return None


def _monitor_records(project_name: str | None) -> list[AgentArtifactRecordWire]:
    return [
        record
        for record in _project_records(project_name, only_monitors=True)
        if is_monitor_member_record(record)
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
    "default_caller",
    "default_lane",
    "durable_lane_for_record",
    "get_monitor",
    "has_any_monitor",
    "list_monitors",
    "monitor_blocking_start_for_lane",
    "read_monitor_marker",
    "reconcile_dead_supervisors",
    "resolve_exact_agent",
    "resolve_lane",
    "resolve_monitor_ref",
    "stop_monitor",
]

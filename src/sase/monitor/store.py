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
from collections.abc import Sequence
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
from sase.core.agent_scan_wire_family_shell import family_shell_from_mapping
from sase.core.agent_scan_wire_markers import AgentMetaWire, DoneMarkerWire
from sase.core.paths import sase_projects_dir
from sase.core.wire import known_field_kwargs
from sase.procs.models import ProcStoreSnapshot

from .identity import supervisor_is_alive
from .models import MonitorRecord, MonitorRefError, is_monitor_member_record
from .naming import short_monitor_id
from .proc_adapter import overlay_proc_on_monitor, proc_shell_owns
from .reconcile import reconcile_dead_supervisor, reconcile_dead_supervisors_for_records

#: How long ``stop_monitor`` waits for the supervisor to leave ``running``.
_STOP_WAIT_SECONDS = 10.0
_STOP_POLL_SECONDS = 0.1
_RECONCILE_ACTIVE_MONITOR_LIMIT = 1000

#: Mirrors :data:`sase.procs.ids.MIN_PROC_REF_LENGTH` for monitor id prefixes.
MIN_MONITOR_REF_LENGTH = 3


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
        return reconcile_dead_supervisor(record, get_monitor=read_monitor_marker)

    # The supervisor's own SIGTERM handler forwards to the monitored
    # command's process group; signal the supervisor pid directly rather
    # than its group, mirroring ``sase.procs.runner.kill_proc``.
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return reconcile_dead_supervisor(record, get_monitor=read_monitor_marker)

    deadline = time.monotonic() + _STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        current = read_monitor_marker(record.project_name, record.artifacts_dir)
        if current is None or current.monitor_state != "running":
            return current if current is not None else record
        if not supervisor_is_alive(pid, record.supervisor_identity):
            return reconcile_dead_supervisor(record, get_monitor=read_monitor_marker)
        time.sleep(_STOP_POLL_SECONDS)

    return record


def get_monitor(project_name: str, artifacts_dir: str) -> MonitorRecord | None:
    """Return the current record for one monitor member's artifacts dir."""
    for record in monitor_records(project_name):
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
    one record it already knows the path to. Tight polling loops and locked
    re-reads that already hold the member's ``artifacts_dir`` -- ``--follow``,
    ``stop_monitor()``'s wait loop, dead-supervisor reconciliation, and
    callers waiting for a monitor to go terminal -- should read that
    member's own ``agent_meta.json`` and ``done.json`` directly instead.
    """
    raw_meta = _read_json_object(os.path.join(artifacts_dir, "agent_meta.json"))
    if raw_meta is None:
        return None
    raw_done = _read_json_object(os.path.join(artifacts_dir, "done.json"))

    meta_kwargs = known_field_kwargs(AgentMetaWire, raw_meta)
    meta_kwargs["family_shell"] = family_shell_from_mapping(raw_meta)
    done_kwargs = None
    if raw_done is not None:
        done_kwargs = known_field_kwargs(DoneMarkerWire, raw_done)
        done_kwargs["family_shell"] = family_shell_from_mapping(raw_done)
    record = AgentArtifactRecordWire(
        project_name=project_name,
        project_dir="",
        project_file="",
        workflow_dir_name="",
        artifact_dir=artifacts_dir,
        timestamp=os.path.basename(artifacts_dir.rstrip("/")),
        agent_meta=AgentMetaWire(**meta_kwargs),
        done=DoneMarkerWire(**done_kwargs) if done_kwargs is not None else None,
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
    from sase.procs.store import read_proc_snapshot

    reconcile_proc_shells()
    snapshot = read_proc_snapshot()
    reconcile_dead_supervisors(project=project, snapshot=snapshot)
    wire_records = list(monitor_records(project))
    if reconcile_terminal_deliveries(project=project, records=wire_records):
        wire_records = list(monitor_records(project))
    records = [
        _with_proc_projection(converted, snapshot=snapshot)
        for converted in (_monitor_record_from_wire(record) for record in wire_records)
        if converted is not None
    ]
    records.sort(key=lambda record: record.timestamp, reverse=True)
    return records


def reconcile_terminal_deliveries(
    *,
    project: str | None = None,
    records: Sequence[AgentArtifactRecordWire] | None = None,
) -> list[MonitorRecord]:
    """Recover terminal monitors that already own pending delivery records."""

    from .resume import reconcile_terminal_delivery

    reconciled: list[MonitorRecord] = []
    source_records = records if records is not None else monitor_records(project)
    for record in (_monitor_record_from_wire(item) for item in source_records):
        if record is None or not record.is_terminal:
            continue
        result = reconcile_terminal_delivery(record)
        if result is None:
            continue
        current = read_monitor_marker(record.project_name, record.artifacts_dir)
        reconciled.append(current if current is not None else record)
    return reconciled


def reconcile_dead_supervisors(
    *,
    project: str | None = None,
    snapshot: ProcStoreSnapshot | None = None,
) -> list[MonitorRecord]:
    """Reconcile all running monitors whose supervisors are no longer alive."""
    return reconcile_dead_supervisors_for_records(
        _reconciliation_monitor_records(project),
        get_monitor=read_monitor_marker,
        snapshot=snapshot,
    )


def _with_proc_projection(
    record: MonitorRecord,
    *,
    snapshot: ProcStoreSnapshot | None = None,
) -> MonitorRecord:
    """Overlay proc-shell execution state; never invent a proc for a legacy row."""
    from sase.procs.store import get_proc, read_proc_snapshot

    procs = snapshot if snapshot is not None else read_proc_snapshot()
    if not proc_shell_owns(record.monitor_id, snapshot=procs):
        return record
    proc = get_proc(record.monitor_id, snapshot=procs)
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


def _monitor_record_from_wire(
    record: AgentArtifactRecordWire,
) -> MonitorRecord | None:
    """Convert a scan row, skipping historical false-positive monitor roles."""
    try:
        return MonitorRecord.from_record(record)
    except ValueError:
        return None


def monitor_records(project_name: str | None) -> list[AgentArtifactRecordWire]:
    return [
        record
        for record in project_records(project_name, only_monitors=True)
        if is_monitor_member_record(record)
    ]


def _reconciliation_monitor_records(
    project_name: str | None,
) -> list[AgentArtifactRecordWire]:
    return [
        record
        for record in _reconciliation_project_records(project_name)
        if is_monitor_member_record(record)
    ]


def _scan_options(
    project_name: str | None,
    *,
    max_records: int | None = None,
    newest_first: bool = False,
) -> AgentArtifactScanOptionsWire:
    return AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        only_projects=(project_name,) if project_name else (),
        max_records=max_records,
        newest_first=newest_first,
    )


def _reconciliation_project_records(
    project_name: str | None,
) -> list[AgentArtifactRecordWire]:
    projects_root = sase_projects_dir()
    options = _scan_options(
        project_name,
        max_records=0,
        newest_first=True,
    )
    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=False,
        include_full_history=False,
        active_limit=_RECONCILE_ACTIVE_MONITOR_LIMIT,
        recent_completed_limit=0,
        include_hidden=True,
        only_monitors=True,
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


def project_records(
    project_name: str | None, *, only_monitors: bool = False
) -> list[AgentArtifactRecordWire]:
    projects_root = sase_projects_dir()
    options = _scan_options(project_name)
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
    "get_monitor",
    "list_monitors",
    "monitor_records",
    "project_records",
    "read_monitor_marker",
    "reconcile_dead_supervisors",
    "reconcile_terminal_deliveries",
    "resolve_monitor_ref",
    "stop_monitor",
]
